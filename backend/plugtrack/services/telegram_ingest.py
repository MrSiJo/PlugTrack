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
from dataclasses import dataclass, field
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
    extractor: Callable[[bytes], Awaitable[Any]]   # -> ExtractionResult
    resolve_target: Callable[[], tuple[int, int]]  # -> (user_id, car_id)
    allowed_user_ids: set[int]
    public_base_url: Optional[str] = None
    input_price_p: Optional[float] = None
    output_price_p: Optional[float] = None
    health_check: Optional[Callable[[int], Awaitable[Any]]] = None


@dataclass
class BotConfig:
    token: str
    openai_key: str
    model: str
    allowed: set[int]
    car_id: int
    user_id: int
    public_base_url: Optional[str] = None
    input_price_p: Optional[float] = None
    output_price_p: Optional[float] = None


@dataclass
class ConfigProblem:
    reasons: list[str] = field(default_factory=list)


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in {"true", "1", "yes", "on"}


def _parse_ids(v: Optional[str]) -> set[int]:
    return {int(x) for x in (v or "").replace(" ", "").split(",") if x}


def _to_float(v: Optional[str]) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


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
        ppk = f"{m.cost_per_kwh_pence:.0f}p/kWh" if m.cost_per_kwh_pence else "?p/kWh"
        soc = f"{m.soc_start}→{m.soc_end}%" if m.soc_start is not None else "SoC ?"
        loc = m.location_name or "?"
        addr = f" ({m.location_address})" if m.location_address else ""
        net = m.network or "?"
        when = f"{m.start_at:%d %b %H:%M}"
        end = f"–{m.end_at:%H:%M}" if m.end_at else ""
        warn = " ⚠ low confidence" if m.confidence < 0.6 else ""
        warn += " ⚠ SoC missing" if m.soc_start is None else ""
        lines.append(
            f"⚡ {kwh} · {cost} · {ppk}\n   {soc} · {net} · {loc}{addr}\n"
            f"   {when}{end} · conf {m.confidence:.2f}{warn}"
        )
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

        result = await ctx.extractor(image)
        extraction = result.extraction
        row = ScreenshotImport(
            user_id=user_id,
            telegram_file_id=file_id,
            telegram_message_id=message_id,
            image_sha256=sha,
            source=extraction.source,
            extracted=extraction.__dict__,
            status="staged",
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            reasoning_tokens=result.usage.reasoning_tokens,
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
        created_ids: list[int] = []
        for m in merged:
            cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=m)
            if cs is not None:
                created_ids.append(cs.id)
        for r in staged:
            r.status = "committed"
        await s.commit()

    await ctx.telegram.answer_callback(callback_id, "Saved")
    lines = [f"Saved {len(created_ids)} session(s)."]
    if ctx.public_base_url:
        base = ctx.public_base_url.rstrip("/")
        lines += [f"{base}/sessions/{sid}" for sid in created_ids]
    await ctx.telegram.send_message(chat_id=chat_id, text="\n".join(lines))


_COMMANDS = {"/test", "/start", "/ping", "test", "ping"}


async def handle_text(ctx: IngestContext, *, from_id: int, chat_id: int, text: str) -> None:
    if from_id not in ctx.allowed_user_ids:
        return
    cmd = (text or "").strip().lower()
    if cmd in _COMMANDS and ctx.health_check is not None:
        from .telegram_health import format_health_text
        report = await ctx.health_check(from_id)
        await ctx.telegram.send_message(chat_id=chat_id, text=format_health_text(report))
        return
    await ctx.telegram.send_message(
        chat_id=chat_id, text="Send me a charge screenshot, or /test to check status.")


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
    if msg and msg.get("text"):
        await handle_text(
            ctx, from_id=msg["from"]["id"], chat_id=msg["chat"]["id"], text=msg["text"]
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


async def load_bot_config(sessionmaker):
    """Read+decrypt settings into BotConfig, or ConfigProblem(reasons)."""
    from sqlalchemy import select as _select
    from ..bootstrap import get_settings
    from ..models import Car, Setting
    from ..security.crypto import decrypt_secret

    async with sessionmaker() as s:
        rows = {r.key: r.value for r in (await s.execute(_select(Setting))).scalars().all()}

    reasons: list[str] = []
    if not _truthy(rows.get("telegram_bot_enabled")):
        reasons.append("Telegram bot disabled (telegram_bot_enabled is off)")
    if not rows.get("telegram_bot_token"):
        reasons.append("telegram_bot_token not set")
    if not rows.get("openai_api_key"):
        reasons.append("openai_api_key not set")
    allowed = _parse_ids(rows.get("telegram_allowed_user_ids"))
    if not allowed:
        reasons.append("no allowed Telegram user IDs")
    car_id = int(rows["telegram_default_car_id"]) if rows.get("telegram_default_car_id") else None
    if car_id is None:
        reasons.append("telegram_default_car_id not set")
    if reasons:
        return ConfigProblem(reasons=reasons)

    secret = get_settings().app_secret_key
    async with sessionmaker() as s:
        car = (await s.execute(_select(Car).where(Car.id == car_id))).scalar_one_or_none()
    if car is None:
        return ConfigProblem(reasons=[f"car {car_id} not found"])

    return BotConfig(
        token=decrypt_secret(rows["telegram_bot_token"], secret),
        openai_key=decrypt_secret(rows["openai_api_key"], secret),
        model=rows.get("openai_model") or "gpt-5-mini",
        allowed=allowed,
        car_id=car_id,
        user_id=car.user_id,
        public_base_url=(rows.get("public_base_url") or None),
        input_price_p=_to_float(rows.get("openai_input_price_per_1k_pence")),
        output_price_p=_to_float(rows.get("openai_output_price_per_1k_pence")),
    )


async def read_raw_credentials(sessionmaker):
    """Return (token, openai_key, model) decrypted from settings, or Nones.

    Unlike `load_bot_config`, this never gates on the full config being
    complete — it just surfaces the raw secrets so the health check can
    validate the token/key independently (e.g. mid-setup, bot not running).
    """
    from sqlalchemy import select as _select

    from ..bootstrap import get_settings
    from ..models import Setting
    from ..security.crypto import decrypt_secret

    async with sessionmaker() as s:
        rows = {r.key: r.value for r in (await s.execute(_select(Setting))).scalars().all()}

    secret = get_settings().app_secret_key
    token = decrypt_secret(rows["telegram_bot_token"], secret) if rows.get("telegram_bot_token") else None
    openai_key = decrypt_secret(rows["openai_api_key"], secret) if rows.get("openai_api_key") else None
    model = rows.get("openai_model") or None
    return token, openai_key, model


def build_ingest_context(config: BotConfig, *, sessionmaker, health_check=None) -> "IngestContext":
    from .screenshot_extraction import ExtractionResult, call_openai
    from .telegram_client import TelegramClient

    telegram = TelegramClient(token=config.token)

    async def extractor(image: bytes) -> ExtractionResult:
        return await call_openai(image, api_key=config.openai_key, model=config.model)

    return IngestContext(
        telegram=telegram,
        sessionmaker=sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (config.user_id, config.car_id),
        allowed_user_ids=config.allowed,
        public_base_url=config.public_base_url,
        input_price_p=config.input_price_p,
        output_price_p=config.output_price_p,
        health_check=health_check,
    )
