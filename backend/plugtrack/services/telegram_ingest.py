# backend/plugtrack/services/telegram_ingest.py
"""Telegram ingest handlers: photo -> stage, callback -> commit/discard.

Collaborators are injected via IngestContext so the handlers unit-test
without a live bot or OpenAI. The long-poll runner (Task B7) builds a real
IngestContext and dispatches updates to these functions.
"""
from __future__ import annotations

import hashlib
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
