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
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from ..models import ScreenshotImport
from .mileage_tracking import KM_PER_MILE, _max_odo_at_or_before
from .screenshot_commit import commit_merged_session, preview_merged_session
from .screenshot_commit import _distance_unit as _distance_unit_for
from .screenshot_correlation import MergedSession, correlate_batch
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
    usage_answerer: Optional[Callable[[str], Awaitable[Any]]] = None
    # Agentic bot fields (Task 4)
    agent_runner: Optional[Callable[..., Awaitable[Any]]] = None  # run_agent_turn-shaped
    ai_enabled: bool = False
    openai_key: Optional[str] = None
    openai_model: str = "gpt-5-mini"
    # chat_id -> message_id of the current batch's confirm card, so we EDIT it
    # in place as more screenshots merge in (instead of spamming new cards).
    # Scoped to the bot instance (reset on reconcile); cleared on Save/Discard.
    card_ids: dict[int, int] = field(default_factory=dict)
    # Per-chat rolling conversation history for the agentic loop (Task 4).
    # Keyed by chat_id; each value is a list of Responses-API input item dicts.
    # Reset on new charge Save; capped at HISTORY_TURN_CAP * 2 items.
    rolling_context: dict[int, list[dict]] = field(default_factory=dict)
    # chat_id -> pending change_token (from a propose_* result awaiting commit).
    pending_tokens: dict[int, str] = field(default_factory=dict)
    # chat_id -> (charge_id, set_at_epoch) — conversational two-step edit target.
    # Set by handle_text when user says "update session N from the next screenshot".
    # Consumed (single-use, 10-min expiry) by the next handle_photo for that chat.
    pending_edit_target: dict[int, tuple[int, float]] = field(default_factory=dict)


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
    ai_enabled: bool = False


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


# A photo caption carries the bits the screenshot can't: a mileage reading and,
# for home charges, the word "home" (MyCupra screens show neither). Parse out an
# odometer number (optionally suffixed mi/miles/km) and treat whatever's left as
# the location word. A bare number leaves the unit None so commit applies the
# distance_unit setting (default mi); "km" is the only thing that overrides that.
_CAPTION_ODO_RE = re.compile(
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>miles?|mi|kilometres?|kms?|km)?\b",
    re.IGNORECASE,
)


def _parse_caption(caption: Optional[str]) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """(location_word, odometer, odometer_unit) from a photo caption.

    Examples: "Home 11001mi" -> ("Home", 11001.0, "mi");
    "11056" -> (None, 11056.0, None); "home" -> ("home", None, None).
    """
    text = (caption or "").strip()
    if not text:
        return (None, None, None)
    odo: Optional[float] = None
    unit: Optional[str] = None
    m = _CAPTION_ODO_RE.search(text)
    if m:
        odo = float(m.group("num").replace(",", ""))
        u = (m.group("unit") or "").lower()
        if u.startswith("k"):
            unit = "km"
        elif u:
            unit = "mi"
        text = (text[: m.start()] + text[m.end():]).strip()
    return (text or None, odo, unit)


# ---------------------------------------------------------------------------
# Update-target parsers
# ---------------------------------------------------------------------------

# Verb form: "update 42", "update session 7", "edit charge 99", "update #42"
_UPDATE_VERB_RE = re.compile(
    r"(?:update|edit)\s+(?:session\s+|charge\s+)?#?(\d+)",
    re.IGNORECASE,
)
# Bare hash form: caption is EXACTLY "#42" (whole-caption match only, not substring)
_UPDATE_HASH_WHOLE_RE = re.compile(r"^#\s?(\d+)$", re.IGNORECASE)


def _parse_update_target(caption: Optional[str]) -> Optional[int]:
    """Return session id if the caption expresses an update intent, else None.

    Matches: "update 42", "update session 7", "update charge 99",
    "update #42", "edit 5", "edit session 3".
    Bare #N form ONLY when it is the ENTIRE caption (strip): "#42", "  #42 ".
    Does NOT match "#N" embedded in a location name ("Osprey stall #3",
    "BP Pulse #1 Oxford"), bare numbers ("11056") or plain words ("Home").
    """
    text = (caption or "").strip()
    if not text:
        return None
    # Verb form may appear anywhere in the caption.
    m = _UPDATE_VERB_RE.search(text)
    if m:
        return int(m.group(1))
    # Bare #N form: only when the WHOLE stripped caption is "#N".
    m = _UPDATE_HASH_WHOLE_RE.match(text)
    if m:
        return int(m.group(1))
    return None


def _parse_pending_screenshot_edit(text: str) -> Optional[int]:
    """Return session id if text expresses intent to send a screenshot to update a session.

    Requires ALL of:
    - a session id
    - a screenshot/photo word
    - an explicit update/edit/send-intent verb

    The bare "screenshot for session N" form WITHOUT an intent verb is NOT
    matched (it could be a read-only question like "Can you show me a
    screenshot for session 42?").

    Examples that match:
      "update session 42 with the next screenshot" → 42
      "update 42 with a photo" → 42
      "i'll send a screenshot to update session 42" → 42
      "edit session 7 from the next screenshot" → 7

    Examples that do NOT match:
      "Can you show me a screenshot for session 42?" (no intent verb)
      "update session 42"        (no screenshot/photo word)
      "send a screenshot"        (no id)
      "what did I spend"         (no relevant tokens)
    """
    text = (text or "").strip()
    if not text:
        return None

    has_photo_word = bool(re.search(r"\b(?:screenshot|photo)\b", text, re.IGNORECASE))

    # All forms require both a photo word AND an update/edit/send verb
    if not has_photo_word:
        return None
    has_verb = bool(re.search(
        r"\b(?:update|edit|send|attach|i['']?ll\s+send|i\s+will\s+send)\b",
        text, re.IGNORECASE,
    ))
    if not has_verb:
        return None

    # Extract the session id
    for pat in (
        r"(?:update|edit)\s+(?:session\s+|charge\s+)?#?(\d+)",
        r"\b(?:session|charge)\s+#?(\d+)\b",
    ):
        m2 = re.search(pat, text, re.IGNORECASE)
        if m2:
            return int(m2.group(1))

    return None


_PENDING_EDIT_TTL = 600  # 10 minutes


def _build_proposal_message(result: dict, target: int) -> tuple[str, dict]:
    """Return (text, reply_markup) for a propose_edit_charge result."""
    summary = result.get("summary", f"Proposed update to session #{target}")
    token = result["change_token"]
    return summary, _proposal_kb(token)


def _kb() -> dict[str, Any]:
    return {
        "inline_keyboard": [[
            {"text": "✓ Save", "callback_data": "save"},
            {"text": "🗑️ Discard", "callback_data": "discard"},
        ]]
    }


# Map the raw cost_basis token to a human label for the confirm card. An
# unknown/missing basis just drops the parenthetical (we don't print the token).
_BASIS_LABELS = {
    "location_rate": "location rate",
    "home_rate": "home rate",
    "location_free": "free",
    "override_total": "manual total",
    "override_per_kwh": "manual rate",
}


def _hms(seconds: int) -> str:
    """`14280` -> `3h58m`, `1200` -> `20m`."""
    mins = seconds // 60
    h, mm = divmod(mins, 60)
    return f"{h}h{mm:02d}m" if h else f"{mm}m"


def _summarise(merged: list[MergedSession], projected: Optional[list[dict]] = None, *, unit: str = "mi") -> str:
    """Render the confirm card as an itemised, human-readable block per charge.

    When `projected` is supplied (per-session dicts with kwh_added/cost_pence/
    cost_basis from a commit preview), show the kWh and £ the Save will actually
    produce — including the home/location rate — instead of the raw extracted
    values (which carry no cost for home charges). Each line is omitted entirely
    when its datum is missing (never a `?` placeholder)."""
    def _odo(km: float) -> str:
        return f"{km / KM_PER_MILE:,.0f} mi" if unit == "mi" else f"{km:,.0f} km"

    n = len(merged)
    blocks = [f"Staged {n} {'charge' if n == 1 else 'charges'}:"]
    for i, m in enumerate(merged):
        proj = projected[i] if (projected and i < len(projected)) else None
        kwh = (proj.get("kwh_added") if proj else None) or m.energy_kwh
        cost_pence = (proj.get("cost_pence") if proj else None)
        if cost_pence is None:
            cost_pence = m.cost_total_pence
        basis = proj.get("cost_basis") if proj else None

        is_dc = bool(m.network) or m.cost_total_pence is not None
        emoji = "🔌" if is_dc else "🏠"

        lines: list[str] = []

        # Location line: emoji + the best label we have + the start time.
        # Compose '<Network> <Name> (<Address>)' from whatever's present,
        # skipping a network already echoed in the name.
        name = m.location_name
        if m.network and not (name and m.network.lower() in name.lower()):
            name = f"{m.network} {name}" if name else m.network
        place = name
        if m.location_address:
            place = f"{place} ({m.location_address})" if place else m.location_address
        loc = f"{emoji} {place}" if place else emoji
        loc += f" — {m.start_at:%d %b %H:%M}"
        lines.append(loc)

        if m.soc_start is not None and m.soc_end is not None:
            lines.append(f"🔋 {m.soc_start} → {m.soc_end}%")

        energy = f"⚡ {kwh:.2f} kWh" if kwh else "⚡ energy set on save"
        if m.actual_charge_seconds:
            energy += f" in {_hms(m.actual_charge_seconds)}"
        lines.append(energy)

        if cost_pence is not None:
            cost = f"💷 £{cost_pence / 100:.2f}"
            bits: list[str] = []
            if kwh:
                bits.append(f"~{cost_pence / kwh:.0f}p/kWh")
            label = _BASIS_LABELS.get(basis or "")
            if label:
                bits.append(label)
            if bits:
                cost += f" ({', '.join(bits)})"
            lines.append(cost)

        odo_km = proj.get("odometer_km") if proj else None
        if odo_km is not None:
            odo_line = f"🛞 {_odo(odo_km)}"
            if proj.get("odometer_regressed"):
                em = proj.get("existing_max_km")
                if em is not None:
                    odo_line += f"  ⚠ below last reading ({_odo(em)})"
            lines.append(odo_line)

        if m.confidence < 0.6:
            lines.append("⚠ low confidence")

        blocks.append("\n".join(lines))
    # Blank line between the header/sessions for readability.
    return "\n\n".join(blocks)


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


async def _send_or_edit_card(ctx: IngestContext, *, chat_id: int, text: str) -> None:
    """Show the batch's confirm card. If one is already showing for this chat,
    EDIT it in place (so it updates 7.67->10.74 as screenshots merge) instead
    of sending a new one. Falls back to a fresh card if the edit fails."""
    mid = ctx.card_ids.get(chat_id)
    edit = getattr(ctx.telegram, "edit_message_text", None)
    if mid is not None and edit is not None:
        try:
            await edit(chat_id=chat_id, message_id=mid, text=text, reply_markup=_kb())
            return
        except Exception:  # noqa: BLE001 — message too old / not modified / deleted
            pass
    new_mid = await ctx.telegram.send_message(chat_id=chat_id, text=text, reply_markup=_kb())
    if new_mid is not None:
        ctx.card_ids[chat_id] = new_mid


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
    unit = "mi"
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
        unit = await _distance_unit_for(s)
        from datetime import date as _date
        projected: list[dict] = []
        for m in merged:
            try:
                cs = await preview_merged_session(s, user_id=user_id, car_id=car_id, merged=m)
                entry = {
                    "kwh_added": cs.kwh_added,
                    "cost_pence": cs.cost_pence,
                    "cost_basis": cs.cost_basis,
                }
                if cs.odometer_at_session_km is not None:
                    existing_max = await _max_odo_at_or_before(
                        s, user_id=user_id, car_id=car_id, on_or_before=_date.today())
                    entry["odometer_km"] = cs.odometer_at_session_km
                    if existing_max is not None and cs.odometer_at_session_km < existing_max:
                        entry["odometer_regressed"] = True
                        entry["existing_max_km"] = existing_max
                projected.append(entry)
            except Exception:  # noqa: BLE001
                projected.append({})
    text = prefix + _summarise(merged, projected=projected, unit=unit)
    if unplaceable:
        text += (
            f"\n⚠️ {len(unplaceable)} reading(s) have no date — send the app "
            "screenshot (MyCupra/network) for that charge, or include a date, "
            "so I can place them."
        )
    await _send_or_edit_card(ctx, chat_id=chat_id, text=text)


def _extraction_to_edit_kwargs(extraction: "Extraction") -> dict[str, Any]:
    """Map Extraction fields → propose_edit_charge keyword arguments.

    Only includes fields that are not None. Date and notes are never set from
    a screenshot (updating an existing session shouldn't move its date).
    Cost: prefer total_cost_p when has_cost+cost_total_pence; else per-kwh rate.
    """
    kwargs: dict[str, Any] = {}
    if extraction.energy_kwh is not None:
        kwargs["kwh"] = extraction.energy_kwh
    if extraction.has_cost and extraction.cost_total_pence is not None:
        kwargs["total_cost_p"] = extraction.cost_total_pence
    elif extraction.cost_per_kwh_pence is not None:
        kwargs["price_p_per_kwh"] = extraction.cost_per_kwh_pence
    if extraction.soc_start is not None:
        kwargs["start_soc"] = extraction.soc_start
    if extraction.soc_end is not None:
        kwargs["end_soc"] = extraction.soc_end
    if extraction.network is not None:
        kwargs["network"] = extraction.network
    if extraction.odometer is not None:
        kwargs["odometer"] = extraction.odometer
        if extraction.odometer_unit is not None:
            kwargs["odometer_unit"] = extraction.odometer_unit
    return kwargs


async def _handle_photo_update_target(
    ctx: IngestContext, *, target: int, user_id: int, chat_id: int, image: bytes,
    consumed_pending: bool = False,
) -> None:
    """Execute the update-from-screenshot path for a resolved target session id.

    Downloads+extracts the image, validates ownership, calls propose_edit_charge,
    stores the change_token, sends the proposal card. Sends an error message on
    any failure (not found, no usable fields, propose error).

    `consumed_pending` signals that the caller has already pulled this call's
    target from pending_edit_target; on failure we put it back so the user can
    resend (fix 5).
    """
    from ..mcp.tools import get_charge, propose_edit_charge

    async with ctx.sessionmaker() as s:
        owned = await get_charge(s, user_id, target)
        if owned is None or (isinstance(owned, dict) and owned.get("error")):  # fix 7
            await ctx.telegram.send_message(
                chat_id=chat_id,
                text=f"Session {target} not found.",
            )
            # Ownership failure — restore pending so the user can correct and resend.
            if consumed_pending:
                ctx.pending_edit_target[chat_id] = (target, time.time())
            return

    result_obj = await ctx.extractor(image)
    extraction = result_obj.extraction
    kwargs = _extraction_to_edit_kwargs(extraction)

    if not kwargs:
        await ctx.telegram.send_message(
            chat_id=chat_id,
            text=f"Couldn't read any charge data from that screenshot to update session {target}.",
        )
        # Extraction failure — restore pending so the user can resend a clearer photo.
        if consumed_pending:
            ctx.pending_edit_target[chat_id] = (target, time.time())
        return

    async with ctx.sessionmaker() as s:
        result = await propose_edit_charge(s, user_id, charge_id=target, **kwargs)

    if result.get("error"):
        await ctx.telegram.send_message(chat_id=chat_id, text=result["error"])
        # propose error — restore pending so the user can retry.
        if consumed_pending:
            ctx.pending_edit_target[chat_id] = (target, time.time())
        return

    # Success: clear the staging card so the next new-session photo starts fresh (fix 3).
    ctx.card_ids.pop(chat_id, None)

    change_token = result["change_token"]
    ctx.pending_tokens[chat_id] = change_token
    # Use _build_proposal_message as the single source of truth for card text (fix 6).
    summary, kb = _build_proposal_message(result, target)
    await ctx.telegram.send_message(
        chat_id=chat_id,
        text=summary,
        reply_markup=kb,
    )


async def handle_photo(
    ctx: IngestContext, *, from_id: int, chat_id: int, message_id: int, file_id: str,
    caption: Optional[str] = None,
) -> None:
    if from_id not in ctx.allowed_user_ids:
        return
    user_id, _car_id = ctx.resolve_target()
    path = await ctx.telegram.get_file_path(file_id)
    image = await ctx.telegram.download_file(path)

    # -------------------------------------------------------------------
    # Update-from-screenshot routing: resolve a target session id, if any.
    #   Priority 1: caption trigger ("update 42", "#13", "edit session 7").
    #   Priority 2: conversational pending_edit_target (10-min expiry, single-use).
    # When a target is found, delegate to the update path and RETURN — the
    # new-session staging flow below is never reached.
    # -------------------------------------------------------------------
    target: Optional[int] = _parse_update_target(caption)
    consumed_pending = False
    if target is None:
        pending = ctx.pending_edit_target.get(chat_id)
        if pending is not None:
            pending_id, set_at = pending
            if time.time() - set_at <= _PENDING_EDIT_TTL:
                target = pending_id
                # Pop now (single-use, valid). On failure _handle_photo_update_target
                # will restore it so the user can resend (fix 5).
                ctx.pending_edit_target.pop(chat_id, None)
                consumed_pending = True
            else:
                # Expired entry — clear it.
                ctx.pending_edit_target.pop(chat_id, None)

    if target is not None:
        await _handle_photo_update_target(
            ctx, target=target, user_id=user_id, chat_id=chat_id, image=image,
            consumed_pending=consumed_pending)
        return

    # -------------------------------------------------------------------
    # Existing new-session staging flow — unchanged.
    # -------------------------------------------------------------------
    sha = hashlib.sha256(image).hexdigest()

    # Dedupe is resolved in _stage_and_card (committed -> warn, staged -> re-show,
    # discarded -> re-stage, new -> insert), so it's the single source of truth.
    result = await ctx.extractor(image)
    extraction = result.extraction
    # Fold the caption into the extraction, filling only what the image lacks:
    # the location word (so a found public location isn't clobbered) and the
    # odometer (screenshots in this flow never carry a caption mileage).
    loc_word, odo, odo_unit = _parse_caption(caption)
    repl: dict[str, Any] = {}
    if loc_word and not extraction.location_name:
        repl["location_name"] = loc_word
    if odo is not None and extraction.odometer is None:
        repl["odometer"] = odo
        if odo_unit is not None:
            repl["odometer_unit"] = odo_unit
    if repl:
        extraction = dataclasses.replace(extraction, **repl)
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

    # -----------------------------------------------------------------------
    # MCP propose/commit callbacks (Task 4)
    # -----------------------------------------------------------------------
    if data.startswith("mcpcommit:"):
        token = data[len("mcpcommit:"):]
        await ctx.telegram.answer_callback(callback_id, "Applying…")
        try:
            async with ctx.sessionmaker() as s:
                from ..mcp.tools import commit_change
                result = await commit_change(s, user_id, token)
            # Only pop the stored token if it matches the one being committed (fix 4).
            if ctx.pending_tokens.get(chat_id) == token:
                ctx.pending_tokens.pop(chat_id, None)
            if result.get("ok"):
                await ctx.telegram.send_message(chat_id=chat_id, text="Done — change saved.")
            else:
                err = result.get("error", "unknown error")
                await ctx.telegram.send_message(
                    chat_id=chat_id, text=f"Could not apply: {err}"
                )
        except Exception:
            logger.exception("mcpcommit failed")
            await ctx.telegram.send_message(
                chat_id=chat_id, text="Sorry — the change could not be applied."
            )
        return

    if data.startswith("mcpdiscard:"):
        token = data[len("mcpdiscard:"):]
        # Only pop the stored token if it matches the one being discarded (fix 4).
        if ctx.pending_tokens.get(chat_id) == token:
            ctx.pending_tokens.pop(chat_id, None)
        await ctx.telegram.answer_callback(callback_id, "Discarded")
        await ctx.telegram.send_message(chat_id=chat_id, text="Change discarded.")
        return

    # -----------------------------------------------------------------------
    # Existing Save / Discard (screenshot batch) paths — UNCHANGED
    # -----------------------------------------------------------------------
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
            ctx.card_ids.pop(chat_id, None)  # batch closed -> next charge gets a fresh card
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
        ctx.card_ids.pop(chat_id, None)  # batch saved -> next charge gets a fresh card
        # Reset rolling history on a new charge save (fresh conversation context)
        ctx.rolling_context.pop(chat_id, None)

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


# Rolling history cap: keep the last N user+assistant turn pairs (2 items each).
_HISTORY_TURN_CAP = 10  # keeps last 10 pairs = 20 items


def _append_history(ctx: "IngestContext", chat_id: int, user_text: str, reply_text: str) -> None:
    """Append a user+assistant pair to rolling_context[chat_id], then cap."""
    history = ctx.rolling_context.setdefault(chat_id, [])
    history.append({"role": "user", "content": [{"type": "input_text", "text": user_text}]})
    history.append({"role": "assistant", "content": [{"type": "output_text", "text": reply_text}]})
    # Cap: keep only the last _HISTORY_TURN_CAP * 2 items
    if len(history) > _HISTORY_TURN_CAP * 2:
        ctx.rolling_context[chat_id] = history[-(  _HISTORY_TURN_CAP * 2):]


def _proposal_kb(change_token: str) -> dict[str, Any]:
    """Build an inline keyboard for a pending proposal (Save = commit, Discard = drop)."""
    return {
        "inline_keyboard": [[
            {"text": "✓ Save", "callback_data": f"mcpcommit:{change_token}"},
            {"text": "🗑️ Discard", "callback_data": f"mcpdiscard:{change_token}"},
        ]]
    }


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
    # -----------------------------------------------------------------------
    # Conversational two-step: "update session N from the next screenshot"
    # Checked early (before charge-note extractor) so it isn't swallowed by it.
    # -----------------------------------------------------------------------
    target_id = _parse_pending_screenshot_edit(text)
    if target_id is not None:
        from ..mcp.tools import get_charge
        user_id_for_check, _ = ctx.resolve_target()
        async with ctx.sessionmaker() as s:
            owned = await get_charge(s, user_id_for_check, target_id)
        if owned is None or (isinstance(owned, dict) and owned.get("error")):
            await ctx.telegram.send_message(
                chat_id=chat_id,
                text=f"Session {target_id} not found.",
            )
        else:
            ctx.pending_edit_target[chat_id] = (target_id, time.time())
            await ctx.telegram.send_message(
                chat_id=chat_id,
                text=f"OK — send the screenshot to update session {target_id}.",
            )
        return
    # Try to parse a free-text charge note. A failure here (e.g. an OpenAI
    # error) must NOT black-hole the message — log and fall through to the
    # usage Q&A / help line so the user always gets a reply.
    if ctx.extractor_text is not None and text and text.strip():
        try:
            result = await ctx.extractor_text(text)
        except Exception:  # noqa: BLE001
            logger.exception("charge-note extraction failed; falling through")
            result = None
        e = result.extraction if result is not None else None
        usable = e is not None and e.confidence > 0 and (
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
    # -----------------------------------------------------------------------
    # Agentic loop (Task 4) — replaces usage_answerer for non-charge messages.
    # Falls back to usage_answerer if agent_runner is not set (backward compat).
    # -----------------------------------------------------------------------
    if ctx.agent_runner is not None and ctx.ai_enabled and ctx.openai_key and text and text.strip():
        history = list(ctx.rolling_context.get(chat_id, []))
        try:
            result = await ctx.agent_runner(
                session=None,  # runner uses the sessionmaker itself or is already bound
                user_id=ctx.resolve_target()[0],
                text=text,
                history=history,
                api_key=ctx.openai_key,
                model=ctx.openai_model,
                # tool_runner is not passed here — the injected agent_runner
                # is a pre-wired closure (or make_tool_runner is called inside).
            )
        except Exception:  # noqa: BLE001
            logger.exception("agent_runner failed; sending error reply")
            await ctx.telegram.send_message(
                chat_id=chat_id, text="Sorry — I couldn't answer that right now.")
            return

        reply_text = result.get("reply_text") or ""
        proposal = result.get("proposal")

        if proposal:
            change_token = proposal["change_token"]
            ctx.pending_tokens[chat_id] = change_token
            kb = _proposal_kb(change_token)
            summary = proposal.get("summary", "")
            msg = reply_text or f"Proposed change: {summary}"
            await ctx.telegram.send_message(chat_id=chat_id, text=msg, reply_markup=kb)
        else:
            await ctx.telegram.send_message(chat_id=chat_id, text=reply_text or "No reply.")

        # Update rolling history
        _append_history(ctx, chat_id, text, reply_text or "")
        return

    # Backward-compat: usage_answerer (usage_chat.py path, being retired)
    if ctx.usage_answerer is not None and text and text.strip():
        try:
            answer, _usage = await ctx.usage_answerer(text)
        except Exception:  # noqa: BLE001 — never crash the long-poll loop
            await ctx.telegram.send_message(
                chat_id=chat_id, text="Sorry — I couldn't answer that right now.")
            return
        await ctx.telegram.send_message(chat_id=chat_id, text=answer)
        return

    # AI features off (but the bot IS configured for agentic use): inform the user.
    # Only show this when agent_runner is present but ai_enabled is False, so that
    # legacy IngestContext setups (no agent_runner at all) still show the plain help.
    if ctx.agent_runner is not None and not ctx.ai_enabled and text and text.strip():
        await ctx.telegram.send_message(
            chat_id=chat_id,
            text="AI features are off — enable AI in Admin to ask questions.")
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
        ai_enabled=_truthy(rows.get("ai_enabled")),
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


def build_ingest_context(
    config: BotConfig,
    *,
    sessionmaker,
    health_check=None,
    ai_enabled: bool = False,
) -> "IngestContext":
    from .screenshot_extraction import ExtractionResult, call_openai, extract_from_text
    from .telegram_client import TelegramClient

    telegram = TelegramClient(token=config.token)

    async def extractor(image: bytes) -> ExtractionResult:
        return await call_openai(image, api_key=config.openai_key, model=config.model)

    async def extractor_text(text: str) -> ExtractionResult:
        return await extract_from_text(text, api_key=config.openai_key, model=config.model)

    # usage_answerer is kept for backward compatibility (still wired, but the
    # agentic loop takes priority when ai_enabled and agent_runner are set).
    async def usage_answerer(question: str):
        from datetime import date
        from .usage_stats import build_usage_snapshot
        from .usage_chat import answer_usage_question
        async with sessionmaker() as s:
            unit = await _distance_unit_for(s)
            snap = await build_usage_snapshot(
                s, user_id=config.user_id, today=date.today(), distance_unit=unit)
        return await answer_usage_question(
            question, snap.to_prompt_dict(), api_key=config.openai_key, model=config.model)

    # Build the agentic runner: a sessionmaker-aware wrapper around run_agent_turn
    # that opens a session per call and passes the bound tool_runner.
    from .bot_agent import make_tool_runner, run_agent_turn as _run_agent_turn

    async def agent_runner(
        *,
        session,  # unused here — we open our own from sessionmaker
        user_id: int,
        text: str,
        history: list,
        api_key: str,
        model: str,
        **_kwargs,  # absorb any extra kwargs the caller might pass
    ):
        async with sessionmaker() as s:
            tool_runner = make_tool_runner(s, user_id)
            return await _run_agent_turn(
                session=s,
                user_id=user_id,
                text=text,
                history=history,
                api_key=api_key,
                model=model,
                tool_runner=tool_runner,
            )

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
        usage_answerer=usage_answerer,
        agent_runner=agent_runner,
        ai_enabled=ai_enabled,
        openai_key=config.openai_key,
        openai_model=config.model,
    )
