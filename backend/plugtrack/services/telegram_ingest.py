# backend/plugtrack/services/telegram_ingest.py
"""Telegram ingest handlers: photo -> stage, callback -> commit/discard.

Collaborators are injected via IngestContext so the handlers unit-test
without a live bot or OpenAI. The long-poll runner (Task B7) builds a real
IngestContext and dispatches updates to these functions.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from ..models import ScreenshotImport
from .screenshot_correlation import MergedSession, correlate_batch
from .screenshot_commit import commit_merged_session, preview_merged_session
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
    extractor_text: Optional[Callable[[str], Awaitable[Any]]] = None


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


def _summarise(merged: list[MergedSession], projected: Optional[list[dict]] = None) -> str:
    """Render the confirm card. When `projected` is supplied (per-session dicts
    with kwh_added/cost_pence/cost_basis from a commit preview), show the kWh and
    £ the Save will actually produce — including the home/location rate — instead
    of the raw extracted values (which carry no cost for home charges)."""
    lines = [f"Staged {len(merged)} session(s):"]
    for i, m in enumerate(merged):
        proj = projected[i] if (projected and i < len(projected)) else None
        kwh = (proj.get("kwh_added") if proj else None) or m.energy_kwh
        cost_pence = (proj.get("cost_pence") if proj else None)
        if cost_pence is None:
            cost_pence = m.cost_total_pence
        basis = proj.get("cost_basis") if proj else None

        # Build each line from only the fields we actually have — omit unknowns
        # rather than print "?" placeholders.
        head = [f"⚡ {kwh:.2f} kWh"] if kwh else ["⚡ energy derived from SoC on save"]
        if cost_pence is not None:
            head.append(f"£{cost_pence / 100:.2f}" + (f" ({basis})" if basis else ""))
            if kwh:
                head.append(f"~{cost_pence / kwh:.0f}p/kWh")

        detail: list[str] = []
        if m.soc_start is not None and m.soc_end is not None:
            detail.append(f"{m.soc_start}→{m.soc_end}%")
        is_dc = bool(m.network) or m.cost_total_pence is not None
        if is_dc:
            detail.append("DC")
        elif m.soc_start is not None:
            detail.append("AC/home")
        if m.network:
            detail.append(m.network)
        if m.location_name:
            detail.append(m.location_name + (f" ({m.location_address})" if m.location_address else ""))
        elif m.location_address:
            detail.append(m.location_address)

        when = f"{m.start_at:%d %b %H:%M}"
        if m.end_at:
            when += f"–{m.end_at:%H:%M}"
        meta = [when, f"conf {m.confidence:.2f}"]
        if m.confidence < 0.6:
            meta.append("⚠ low confidence")

        parts = [" · ".join(head)]
        if detail:
            parts.append("   " + " · ".join(detail))
        parts.append("   " + " · ".join(meta))
        lines.append("\n".join(parts))
    return "\n".join(lines)


def _committed_dupe_text(ctx: IngestContext, existing: "ScreenshotImport") -> str:
    sid = existing.created_session_id
    when = existing.created_at.strftime("%d %b") if existing.created_at else ""
    msg = "⚠️ Looks like I've already saved this screenshot"
    if sid:
        msg += f" (session #{sid}{', ' + when if when else ''})"
    msg += ". Re-sending a saved charge never duplicates it — edit the existing one instead"
    if ctx.public_base_url and sid:
        msg += f":\n{ctx.public_base_url.rstrip('/')}/sessions/{sid}"
    else:
        msg += "."
    return msg


async def _staged_rows(s, user_id):
    return (
        await s.execute(
            select(ScreenshotImport).where(
                ScreenshotImport.user_id == user_id,
                ScreenshotImport.status == "staged",
            )
        )
    ).scalars().all()


async def _stage_and_card(
    ctx: IngestContext, *, user_id, chat_id, extraction, usage,
    telegram_file_id, message_id, sha,
) -> None:
    """Single dedupe authority. By (user_id, sha) — which is UNIQUE:
      - committed  -> warn, don't touch the saved row (commit guard also blocks dupes).
      - staged     -> already in the current batch; re-show the card, no duplicate row.
      - discarded  -> re-stage by REUSING the row (can't insert a 2nd same-sha row).
      - none       -> insert a fresh staged row.
    """
    prefix = ""
    async with ctx.sessionmaker() as s:
        existing = (
            await s.execute(
                select(ScreenshotImport).where(
                    ScreenshotImport.user_id == user_id,
                    ScreenshotImport.image_sha256 == sha,
                )
            )
        ).scalar_one_or_none()

        if existing is not None and existing.status == "committed":
            await ctx.telegram.send_message(
                chat_id=chat_id, text=_committed_dupe_text(ctx, existing))
            return

        if existing is not None and existing.status == "staged":
            prefix = "That's already staged — use Save/Discard below.\n"
        elif existing is not None:  # discarded -> reuse the row (unique sha)
            existing.status = "staged"
            existing.source = extraction.source
            existing.extracted = extraction.__dict__
            existing.input_tokens = usage.input_tokens
            existing.output_tokens = usage.output_tokens
            existing.reasoning_tokens = usage.reasoning_tokens
            if telegram_file_id is not None:
                existing.telegram_file_id = telegram_file_id
            if message_id is not None:
                existing.telegram_message_id = message_id
            await s.commit()
        else:  # new
            s.add(ScreenshotImport(
                user_id=user_id, telegram_file_id=telegram_file_id,
                telegram_message_id=message_id, image_sha256=sha,
                source=extraction.source, extracted=extraction.__dict__, status="staged",
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens))
            await s.commit()

        staged = await _staged_rows(s, user_id)
        merged, unplaceable = correlate_batch([parse_extraction(r.extracted) for r in staged])
        # Preview what Save will produce (kWh + home/location-rate cost) so the
        # card shows real figures, not "£?". Best-effort — never block the card.
        _uid, car_id = ctx.resolve_target()
        projected: list[dict] = []
        for m in merged:
            try:
                cs = await preview_merged_session(s, user_id=user_id, car_id=car_id, merged=m)
                projected.append({
                    "kwh_added": cs.kwh_added,
                    "cost_pence": cs.cost_pence,
                    "cost_basis": cs.cost_basis,
                })
            except Exception:  # noqa: BLE001
                projected.append({})
    text = prefix + _summarise(merged, projected=projected)
    if unplaceable:
        text += (
            f"\n⚠️ {len(unplaceable)} reading(s) have no date — send the app "
            "screenshot (MyCupra/network) for that charge, or include a date, "
            "so I can place them."
        )
    await ctx.telegram.send_message(chat_id=chat_id, text=text, reply_markup=_kb())


async def handle_photo(
    ctx: IngestContext, *, from_id: int, chat_id: int, message_id: int, file_id: str,
    caption: Optional[str] = None,
) -> None:
    if from_id not in ctx.allowed_user_ids:
        return
    user_id, _car_id = ctx.resolve_target()
    path = await ctx.telegram.get_file_path(file_id)
    image = await ctx.telegram.download_file(path)
    sha = hashlib.sha256(image).hexdigest()

    # Dedupe is resolved in _stage_and_card (committed -> warn, staged -> re-show,
    # discarded -> re-stage, new -> insert), so it's the single source of truth.
    result = await ctx.extractor(image)
    extraction = result.extraction
    if caption and caption.strip() and not extraction.location_name:
        extraction = dataclasses.replace(extraction, location_name=caption.strip())
    await _stage_and_card(
        ctx, user_id=user_id, chat_id=chat_id, extraction=extraction,
        usage=result.usage, telegram_file_id=file_id, message_id=message_id, sha=sha,
    )


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
        exts = [parse_extraction(r.extracted) for r in staged]
        merged, unplaceable = correlate_batch(exts)
        unplaceable_ids = {id(e) for e in unplaceable}
        created: list[tuple[int, Optional[int], Optional[str]]] = []  # (id, cost_pence, cost_basis)
        for m in merged:
            cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=m)
            if cs is not None:
                created.append((cs.id, cs.cost_pence, cs.cost_basis))
        # Mark only the placeable rows committed; keep undated readings staged so
        # their app-screenshot companion can still arrive and place them.
        kept = 0
        for row, ext in zip(staged, exts):
            if id(ext) in unplaceable_ids:
                kept += 1
                continue
            row.status = "committed"
        await s.commit()

    await ctx.telegram.answer_callback(callback_id, "Saved")
    lines = [f"Saved {len(created)} session(s)."]
    base = ctx.public_base_url.rstrip("/") if ctx.public_base_url else None
    for sid, cost_pence, basis in created:
        cost = f"£{cost_pence/100:.2f} ({basis})" if cost_pence is not None else "cost n/a"
        line = f"#{sid}: {cost}"
        if base:
            line += f" — {base}/sessions/{sid}"
        lines.append(line)
    if kept:
        lines.append(
            f"⚠️ Kept {kept} undated reading(s) staged — send the app screenshot "
            "for that charge to place them."
        )
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
    # Try to parse a free-text charge note.
    if ctx.extractor_text is not None and text and text.strip():
        result = await ctx.extractor_text(text)
        e = result.extraction
        usable = e.confidence > 0 and (
            e.energy_kwh is not None or e.soc_start is not None
            or e.soc_end is not None or e.cost_total_pence is not None)
        if usable:
            import hashlib as _hashlib
            sha = _hashlib.sha256(("text:" + text.strip().lower()).encode()).hexdigest()
            user_id, _car_id = ctx.resolve_target()
            await _stage_and_card(ctx, user_id=user_id, chat_id=chat_id, extraction=e,
                                  usage=result.usage, telegram_file_id=None,
                                  message_id=None, sha=sha)
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
            caption=msg.get("caption"),
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
    from .screenshot_extraction import ExtractionResult, call_openai, extract_from_text
    from .telegram_client import TelegramClient

    telegram = TelegramClient(token=config.token)

    async def extractor(image: bytes) -> ExtractionResult:
        return await call_openai(image, api_key=config.openai_key, model=config.model)

    async def extractor_text(text: str) -> ExtractionResult:
        return await extract_from_text(text, api_key=config.openai_key, model=config.model)

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
        extractor_text=extractor_text,
    )
