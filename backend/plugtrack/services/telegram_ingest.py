# backend/plugtrack/services/telegram_ingest.py
"""Telegram ingest handlers: photo -> stage, callback -> commit/discard.

Collaborators are injected via IngestContext so the handlers unit-test
without a live bot or OpenAI. The long-poll runner (Task B7) builds a real
IngestContext and dispatches updates to these functions.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from ..models import ScreenshotImport
from .screenshot_correlation import MergedSession, correlate
from .screenshot_commit import commit_merged_session
from .screenshot_extraction import Extraction, parse_extraction

# Group recently-staged screenshots from the last STAGING_WINDOW_MIN minutes.
STAGING_WINDOW_MIN = 720  # 12h, so a late MyCupra/Tesla shot still attaches


@dataclass
class IngestContext:
    telegram: Any                                  # TelegramClient-shaped
    sessionmaker: Any                              # async_sessionmaker
    extractor: Callable[[bytes], Awaitable[Extraction]]
    resolve_target: Callable[[], tuple[int, int]]  # -> (user_id, car_id)
    allowed_user_ids: set[int]


def _kb() -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "✓ Save", "callback_data": "save"},
            {"text": "🗑️ Discard", "callback_data": "discard"},
        ]]
    }


def _summarise(merged: list[MergedSession]) -> str:
    lines = [f"Staged {len(merged)} session(s):"]
    for m in merged:
        kwh = f"{m.energy_kwh:.2f} kWh" if m.energy_kwh else "? kWh"
        cost = f"£{m.cost_total_pence/100:.2f}" if m.cost_total_pence else "£?"
        soc = f"{m.soc_start}->{m.soc_end}%" if m.soc_start is not None else "SoC ?"
        net = m.network or "?"
        lines.append(f"⚡ {kwh} · {cost} · {soc} · {net} · {m.start_at:%d %b %H:%M}")
    return "\n".join(lines)


async def handle_photo(
    ctx: IngestContext, *, from_id: int, chat_id: int, message_id: int, file_id: str
) -> None:
    if from_id not in ctx.allowed_user_ids:
        return
    user_id, _car_id = ctx.resolve_target()
    path = await ctx.telegram.get_file_path(file_id)
    image = await ctx.telegram.download_file(path)
    sha = hashlib.sha256(image).hexdigest()

    async with ctx.sessionmaker() as s:
        exists = (
            await s.execute(
                select(ScreenshotImport).where(
                    ScreenshotImport.user_id == user_id, ScreenshotImport.image_sha256 == sha
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            await ctx.telegram.send_message(chat_id=chat_id, text="Already have that screenshot.")
            return

        extraction = await ctx.extractor(image)
        row = ScreenshotImport(
            user_id=user_id,
            telegram_file_id=file_id,
            telegram_message_id=message_id,
            image_sha256=sha,
            source=extraction.source,
            extracted=extraction.__dict__,
            status="staged",
        )
        s.add(row)
        await s.commit()

        staged = (
            await s.execute(
                select(ScreenshotImport).where(
                    ScreenshotImport.user_id == user_id, ScreenshotImport.status == "staged"
                )
            )
        ).scalars().all()

    extractions = [parse_extraction(r.extracted) for r in staged]
    merged = correlate(extractions)
    await ctx.telegram.send_message(chat_id=chat_id, text=_summarise(merged), reply_markup=_kb())


async def handle_callback(
    ctx: IngestContext, *, from_id: int, callback_id: str, data: str, chat_id: int
) -> None:
    if from_id not in ctx.allowed_user_ids:
        return
    user_id, car_id = ctx.resolve_target()

    async with ctx.sessionmaker() as s:
        staged = (
            await s.execute(
                select(ScreenshotImport).where(
                    ScreenshotImport.user_id == user_id, ScreenshotImport.status == "staged"
                )
            )
        ).scalars().all()

        if data == "discard":
            for r in staged:
                r.status = "discarded"
            await s.commit()
            await ctx.telegram.answer_callback(callback_id, "Discarded")
            await ctx.telegram.send_message(chat_id=chat_id, text="Discarded staged screenshots.")
            return

        # data == "save"
        merged = correlate([parse_extraction(r.extracted) for r in staged])
        created = 0
        for m in merged:
            cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=m)
            if cs is not None:
                created += 1
        for r in staged:
            r.status = "committed"
        await s.commit()

    await ctx.telegram.answer_callback(callback_id, "Saved")
    await ctx.telegram.send_message(chat_id=chat_id, text=f"Saved {created} session(s).")


logger = logging.getLogger(__name__)


async def dispatch_update(*, ctx: Optional[IngestContext], update: dict[str, Any]) -> None:
    msg = update.get("message")
    if msg and msg.get("photo"):
        photos = msg["photo"]
        await handle_photo(
            ctx,
            from_id=msg["from"]["id"],
            chat_id=msg["chat"]["id"],
            message_id=msg["message_id"],
            file_id=photos[-1]["file_id"],  # largest size
        )
        return
    cb = update.get("callback_query")
    if cb:
        await handle_callback(
            ctx,
            from_id=cb["from"]["id"],
            callback_id=cb["id"],
            data=cb.get("data", ""),
            chat_id=cb["message"]["chat"]["id"],
        )


async def run_bot(ctx: IngestContext, *, stop: asyncio.Event) -> None:
    """Long-poll getUpdates until `stop` is set."""
    offset = 0
    while not stop.is_set():
        try:
            updates = await ctx.telegram.get_updates(offset=offset, timeout=50)
            for u in updates:
                offset = max(offset, u["update_id"] + 1)
                try:
                    await dispatch_update(ctx=ctx, update=u)
                except Exception:  # noqa: BLE001
                    logger.exception("telegram update handling failed")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("telegram long-poll error; backing off")
            await asyncio.sleep(5)


async def build_context(sessionmaker) -> Optional[IngestContext]:
    """Assemble an IngestContext from DB settings, or None if not configured."""
    from sqlalchemy import select as _select

    from ..bootstrap import get_settings
    from ..models import Setting
    from ..security.crypto import decrypt_secret
    from .screenshot_extraction import call_openai
    from .telegram_client import TelegramClient

    async with sessionmaker() as s:
        rows = {r.key: r.value for r in (await s.execute(_select(Setting))).scalars().all()}

    if (rows.get("telegram_bot_enabled") or "").lower() not in {"true", "1", "yes", "on"}:
        return None
    token_enc = rows.get("telegram_bot_token")
    openai_enc = rows.get("openai_api_key")
    if not token_enc or not openai_enc:
        return None

    secret = get_settings().app_secret_key
    token = decrypt_secret(token_enc, secret)
    openai_key = decrypt_secret(openai_enc, secret)
    model = rows.get("openai_model") or "gpt-5.5"
    allowed = {
        int(x)
        for x in (rows.get("telegram_allowed_user_ids") or "").replace(" ", "").split(",")
        if x
    }
    car_id = int(rows["telegram_default_car_id"]) if rows.get("telegram_default_car_id") else None
    if car_id is None or not allowed:
        return None

    from ..models import Car

    async with sessionmaker() as s:
        car = (await s.execute(_select(Car).where(Car.id == car_id))).scalar_one_or_none()
    if car is None:
        return None
    user_id = car.user_id

    telegram = TelegramClient(token=token)

    async def extractor(image: bytes) -> Extraction:
        return await call_openai(image, api_key=openai_key, model=model)

    return IngestContext(
        telegram=telegram,
        sessionmaker=sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids=allowed,
    )
