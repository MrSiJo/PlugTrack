# backend/tests/services/test_telegram_screenshot_edit.py
"""Tests for the update-session-from-screenshot feature.

Two triggers:
  1. Caption trigger: handle_photo with caption "update 42" / "#13" / "edit session 7"
  2. Conversational two-step: handle_text sets pending_edit_target; the NEXT
     handle_photo (no caption) consumes it and proposes the edit.
"""
import time

import pytest

from plugtrack.services.screenshot_extraction import (
    Extraction,
    ExtractionResult,
    Usage,
)
from plugtrack.services.telegram_ingest import (
    IngestContext,
    _parse_pending_screenshot_edit,
    _parse_update_target,
    handle_photo,
    handle_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extraction(**kw):
    base = dict(
        source="osprey",
        has_cost=True,
        energy_kwh=9.78,
        cost_total_pence=851,
        cost_per_kwh_pence=87.0,
        start_at="2026-06-12T14:25:00",
        end_at="2026-06-12T14:40:00",
        soc_start=56,
        soc_end=70,
        location_name="Land's End",
        location_address="TR19 7AA",
        network="Osprey",
        peak_kw=40.0,
        confidence=0.95,
    )
    base.update(kw)
    return Extraction(**base)


class FakeTg:
    def __init__(self, files: dict | None = None):
        self._files: dict[str, bytes] = files or {}
        self.sent: list[dict] = []

    async def get_file_path(self, file_id):
        return file_id

    async def download_file(self, path):
        return self._files[path]

    async def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return len(self.sent)

    async def answer_callback(self, callback_id, text=""):
        pass


def _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction):
    async def extractor(image_bytes: bytes):
        return ExtractionResult(extraction=extraction, usage=Usage(10, 10, 0))

    return IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )


async def _seed_session(test_sessionmaker, user_id, car_id):
    """Insert a real ChargingSession and return its id."""
    import datetime as dt

    from plugtrack.models import ChargingSession

    async with test_sessionmaker() as s:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            date=dt.date(2026, 6, 12),
            kwh_added=7.5,
            start_soc=40,
            end_soc=80,
            charge_network="Osprey",
            source="osprey",
        )
        s.add(cs)
        await s.commit()
        await s.refresh(cs)
        return cs.id


# ---------------------------------------------------------------------------
# 1. _parse_update_target
# ---------------------------------------------------------------------------


def test_parse_update_target_bare_update():
    assert _parse_update_target("update 42") == 42


def test_parse_update_target_update_session():
    assert _parse_update_target("update session 7") == 7


def test_parse_update_target_update_charge():
    assert _parse_update_target("update charge 99") == 99


def test_parse_update_target_edit():
    assert _parse_update_target("edit 5") == 5


def test_parse_update_target_edit_session():
    assert _parse_update_target("edit session 3") == 3


def test_parse_update_target_hash_prefix():
    assert _parse_update_target("#13") == 13


def test_parse_update_target_update_hash():
    assert _parse_update_target("update #42") == 42


def test_parse_update_target_case_insensitive():
    assert _parse_update_target("UPDATE SESSION 10") == 10


def test_parse_update_target_home_returns_none():
    assert _parse_update_target("Home") is None


def test_parse_update_target_bare_number_returns_none():
    assert _parse_update_target("11056") is None


def test_parse_update_target_plain_location_word_returns_none():
    assert _parse_update_target("Public Charger") is None


def test_parse_update_target_none_caption():
    assert _parse_update_target(None) is None


def test_parse_update_target_empty_string():
    assert _parse_update_target("") is None


# ---------------------------------------------------------------------------
# 2. _parse_pending_screenshot_edit
# ---------------------------------------------------------------------------


def test_parse_pending_screenshot_edit_standard():
    assert _parse_pending_screenshot_edit("update session 42 with the next screenshot") == 42


def test_parse_pending_screenshot_edit_photo_word():
    assert _parse_pending_screenshot_edit("update 42 with a photo") == 42


def test_parse_pending_screenshot_edit_screenshot_for_form_no_verb_returns_none():
    # "screenshot for session N" alone has no intent verb — must NOT match (fix 2).
    assert _parse_pending_screenshot_edit("screenshot for session 42") is None


def test_parse_pending_screenshot_edit_screenshot_for_with_send_verb():
    # Same "for session N" construct WITH an intent verb → matches.
    assert _parse_pending_screenshot_edit("I'll send a screenshot for session 42") == 42


def test_parse_pending_screenshot_edit_i_will_send():
    assert _parse_pending_screenshot_edit("i'll send a screenshot to update session 42") == 42


def test_parse_pending_screenshot_edit_edit_verb():
    assert _parse_pending_screenshot_edit("edit session 7 from the next screenshot") == 7


def test_parse_pending_screenshot_edit_plain_question_returns_none():
    assert _parse_pending_screenshot_edit("what did I spend") is None


def test_parse_pending_screenshot_edit_no_id_returns_none():
    assert _parse_pending_screenshot_edit("send a screenshot") is None


def test_parse_pending_screenshot_edit_no_screenshot_word_returns_none():
    # Has id and update verb but no screenshot/photo word
    assert _parse_pending_screenshot_edit("update session 42") is None


# ---------------------------------------------------------------------------
# 3. handle_photo — caption "update 42" routes to propose_edit, not new session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_photo_caption_update_proposes_edit(test_sessionmaker, seeded_user_car):
    """Caption 'update <id>' triggers propose_edit_charge; a mcpcommit card is sent;
    no new ScreenshotImport row is created."""
    from sqlalchemy import select

    from plugtrack.models import ScreenshotImport

    user_id, car_id = seeded_user_car
    session_id = await _seed_session(test_sessionmaker, user_id, car_id)

    extraction = _make_extraction()
    tg = FakeTg(files={"img": b"img"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction)

    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=1,
        file_id="img",
        caption=f"update {session_id}",
    )

    # A message must have been sent with a Save/Discard (mcpcommit) keyboard
    assert tg.sent, "Expected at least one message to be sent"
    last = tg.sent[-1]
    kb = last["reply_markup"]
    assert kb is not None, "Expected inline keyboard for proposal"
    buttons_flat = [b for row in kb["inline_keyboard"] for b in row]
    callback_datas = [b["callback_data"] for b in buttons_flat]
    assert any(d.startswith("mcpcommit:") for d in callback_datas), (
        f"Expected mcpcommit button, got: {callback_datas}"
    )

    # A change_token must be stored
    assert ctx.pending_tokens.get(9) is not None, "change_token not stored in ctx.pending_tokens"

    # No ScreenshotImport row should have been created (update path bypasses staging)
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
    assert rows == [], f"Expected no ScreenshotImport rows, got: {rows}"


# ---------------------------------------------------------------------------
# 4. Two-step flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_step_sets_pending_and_photo_proposes(test_sessionmaker, seeded_user_car):
    """handle_text 'update session N from the next screenshot' → pending_edit_target set;
    subsequent handle_photo (no caption) → proposes the edit; pending_edit_target cleared."""
    from sqlalchemy import select

    from plugtrack.models import ScreenshotImport

    user_id, car_id = seeded_user_car
    session_id = await _seed_session(test_sessionmaker, user_id, car_id)

    tg = FakeTg(files={"img": b"img"})
    extraction = _make_extraction()

    async def extractor(image_bytes: bytes):
        return ExtractionResult(extraction=extraction, usage=Usage(10, 10, 0))

    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )

    # Step 1: text message sets pending target
    await handle_text(
        ctx,
        from_id=111,
        chat_id=9,
        text=f"update session {session_id} with the next screenshot",
    )
    assert 9 in ctx.pending_edit_target, "pending_edit_target not set after text trigger"
    pending_id, _ts = ctx.pending_edit_target[9]
    assert pending_id == session_id

    # The bot must have replied acknowledging the pending target
    assert tg.sent, "Expected a reply after handle_text"
    assert str(session_id) in tg.sent[-1]["text"]

    # Step 2: photo (no caption) consumes the pending target
    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=2,
        file_id="img",
        caption=None,
    )

    # Pending target must be consumed (cleared)
    assert 9 not in ctx.pending_edit_target, "pending_edit_target not cleared after photo"

    # A proposal card (mcpcommit) must have been sent
    proposal_msgs = [
        m for m in tg.sent if m.get("reply_markup") is not None
        and any(
            b["callback_data"].startswith("mcpcommit:")
            for row in m["reply_markup"]["inline_keyboard"]
            for b in row
        )
    ]
    assert proposal_msgs, "Expected a mcpcommit proposal card to be sent after photo"

    # Still no new ScreenshotImport
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
    assert rows == [], f"Expected no ScreenshotImport rows, got: {rows}"


# ---------------------------------------------------------------------------
# 5. Caption target for a session NOT owned → "not found" reply, no proposal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_photo_caption_update_unknown_session(test_sessionmaker, seeded_user_car):
    """Caption 'update 99999' for a non-existent session → 'not found' reply, no staging."""
    from sqlalchemy import select

    from plugtrack.models import ScreenshotImport

    user_id, car_id = seeded_user_car
    extraction = _make_extraction()
    tg = FakeTg(files={"img": b"img"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction)

    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=1,
        file_id="img",
        caption="update 99999",
    )

    assert tg.sent, "Expected an error reply"
    assert "99999" in tg.sent[-1]["text"] or "not found" in tg.sent[-1]["text"].lower()
    # No mcpcommit keyboard
    assert tg.sent[-1]["reply_markup"] is None or not any(
        b["callback_data"].startswith("mcpcommit:")
        for row in (tg.sent[-1]["reply_markup"] or {}).get("inline_keyboard", [])
        for b in row
    )
    # No ScreenshotImport staged
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# 6. Regression: plain photo with no / non-update caption → existing new-session flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_photo_no_caption_stages_new_session(test_sessionmaker, seeded_user_car):
    """A plain photo with no caption still stages a NEW session (regression guard)."""
    from sqlalchemy import select

    from plugtrack.models import ScreenshotImport

    user_id, car_id = seeded_user_car
    extraction = _make_extraction()
    tg = FakeTg(files={"img": b"img"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction)

    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=1,
        file_id="img",
        caption=None,
    )

    # A message must have been sent (the staging card)
    assert tg.sent

    # A ScreenshotImport row must have been created
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
    assert len(rows) == 1, f"Expected 1 ScreenshotImport row, got {len(rows)}"
    assert rows[0].status == "staged"


@pytest.mark.asyncio
async def test_handle_photo_location_caption_stages_new_session(test_sessionmaker, seeded_user_car):
    """Caption 'Home' (no update verb, no #) still stages a new session.
    When the extraction has no location, the caption word fills it in.
    """
    from sqlalchemy import select

    from plugtrack.models import ScreenshotImport

    user_id, car_id = seeded_user_car
    # Extraction with NO location_name so the caption "Home" can fill it
    extraction = _make_extraction(location_name=None, location_address=None)
    tg = FakeTg(files={"img": b"img"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction)

    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=1,
        file_id="img",
        caption="Home",
    )

    # Session must have been staged (new-session flow)
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "staged"
    # location_name should have been filled from caption (only when extraction lacks one)
    assert rows[0].extracted.get("location_name") == "Home"


# ---------------------------------------------------------------------------
# 7. handle_text pending-edit-target: unknown session → "not found" reply, no pending set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_step_unknown_session_not_stored(test_sessionmaker, seeded_user_car):
    """handle_text with update-screenshot intent for a non-existent session id → reply
    that session not found; pending_edit_target NOT set."""
    user_id, car_id = seeded_user_car
    tg = FakeTg()

    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )

    await handle_text(
        ctx,
        from_id=111,
        chat_id=9,
        text="update session 99999 with the next screenshot",
    )

    assert 9 not in ctx.pending_edit_target, "Should not set pending for unknown session"
    assert tg.sent, "Expected a 'not found' reply"
    text = tg.sent[-1]["text"].lower()
    assert "not found" in text or "99999" in text


# ---------------------------------------------------------------------------
# 8. Expiry: pending_edit_target that is older than 10min is ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_step_expired_pending_ignored(test_sessionmaker, seeded_user_car):
    """An expired pending_edit_target (>10min) is popped and the new-session flow runs."""
    from sqlalchemy import select

    from plugtrack.models import ScreenshotImport

    user_id, car_id = seeded_user_car
    session_id = await _seed_session(test_sessionmaker, user_id, car_id)

    extraction = _make_extraction()
    tg = FakeTg(files={"img": b"img"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction)

    # Inject an expired pending target (set 11 minutes ago)
    ctx.pending_edit_target[9] = (session_id, time.time() - 660)

    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=1,
        file_id="img",
        caption=None,
    )

    # Expired entry must be cleared
    assert 9 not in ctx.pending_edit_target

    # Should fall through to new-session staging
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "staged"


# ---------------------------------------------------------------------------
# FIX 1 — _parse_update_target: bare #N in a location name must NOT match
# ---------------------------------------------------------------------------


def test_parse_update_target_location_with_hash_not_matched():
    # "Osprey stall #3" — hash in a location name, NOT the whole caption.
    assert _parse_update_target("Osprey stall #3") is None


def test_parse_update_target_bp_pulse_hash_not_matched():
    assert _parse_update_target("BP Pulse #1 Oxford") is None


def test_parse_update_target_bare_hash_whole_caption():
    assert _parse_update_target("#42") == 42


def test_parse_update_target_bare_hash_with_whitespace():
    assert _parse_update_target("  #42 ") == 42


def test_parse_update_target_update_hash_anywhere():
    # Verb form may appear anywhere.
    assert _parse_update_target("update #42") == 42


def test_parse_update_target_update_session_anywhere():
    assert _parse_update_target("update session 7") == 7


# ---------------------------------------------------------------------------
# FIX 2 — _parse_pending_screenshot_edit: read-only questions must NOT match
# ---------------------------------------------------------------------------


def test_parse_pending_screenshot_edit_read_only_question_returns_none():
    assert _parse_pending_screenshot_edit("Can you show me a screenshot for session 42?") is None


def test_parse_pending_screenshot_edit_plain_question_still_none():
    assert _parse_pending_screenshot_edit("what did I spend") is None


def test_parse_pending_screenshot_edit_update_next_screenshot():
    assert _parse_pending_screenshot_edit("update session 42 with the next screenshot") == 42


def test_parse_pending_screenshot_edit_ill_send():
    assert _parse_pending_screenshot_edit("I'll send a screenshot to update session 42") == 42


def test_parse_pending_screenshot_edit_edit_verb():
    assert _parse_pending_screenshot_edit("edit 7 with this photo") == 7


# ---------------------------------------------------------------------------
# FIX 3 — card_ids is cleared after update proposal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_proposal_clears_card_ids(test_sessionmaker, seeded_user_car):
    """After an update proposal the staging card_ids entry is cleared so the
    next new-session photo starts a fresh card (not an edit of the old one)."""
    user_id, car_id = seeded_user_car
    session_id = await _seed_session(test_sessionmaker, user_id, car_id)

    extraction = _make_extraction()
    tg = FakeTg(files={"img": b"img"})
    ctx = _stub_ctx(tg, test_sessionmaker, car_id, user_id, extraction)

    # Pre-seed a stale card id for this chat.
    ctx.card_ids[9] = 99

    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=1,
        file_id="img",
        caption=f"update {session_id}",
    )

    # card_ids must be cleared for this chat after the update proposal.
    assert 9 not in ctx.card_ids, "card_ids should be cleared after update proposal"


# ---------------------------------------------------------------------------
# FIX 4 — handle_callback: token mismatch leaves newer pending_token intact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_discard_old_token_does_not_pop_newer_token(
    test_sessionmaker, seeded_user_car
):
    """Discarding an old mcpdiscard card must NOT pop a *different* (newer)
    pending_token stored for the same chat."""
    from plugtrack.services.telegram_ingest import handle_callback

    user_id, car_id = seeded_user_car
    tg = FakeTg()
    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )

    newer_token = "newer-token-xyz"
    ctx.pending_tokens[9] = newer_token

    # Simulate the user clicking Discard on an old card with a stale token.
    await handle_callback(
        ctx,
        from_id=111,
        callback_id="cb1",
        data="mcpdiscard:stale-old-token",
        chat_id=9,
    )

    # The newer pending_token must survive.
    assert ctx.pending_tokens.get(9) == newer_token, (
        "Newer pending_token was incorrectly popped by an old mcpdiscard"
    )


@pytest.mark.asyncio
async def test_callback_commit_old_token_does_not_pop_newer_token(
    test_sessionmaker, seeded_user_car
):
    """Committing a stale mcpcommit token must NOT pop a *different* (newer)
    pending_token stored for the same chat (commit_change will fail gracefully)."""
    from unittest.mock import AsyncMock, patch

    from plugtrack.services.telegram_ingest import handle_callback

    user_id, car_id = seeded_user_car
    tg = FakeTg()
    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )

    newer_token = "newer-token-abc"
    ctx.pending_tokens[9] = newer_token

    # Patch commit_change to return an error (stale token scenario).
    with patch(
        "plugtrack.mcp.tools.commit_change",
        new=AsyncMock(return_value={"error": "token not found"}),
    ):
        await handle_callback(
            ctx,
            from_id=111,
            callback_id="cb2",
            data="mcpcommit:stale-old-token",
            chat_id=9,
        )

    # The newer pending_token must survive.
    assert ctx.pending_tokens.get(9) == newer_token, (
        "Newer pending_token was incorrectly popped by an old mcpcommit"
    )


# ---------------------------------------------------------------------------
# FIX 5 — pending_edit_target survives extraction failure and is consumed by
#           a subsequent good photo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_edit_target_survives_extraction_failure(
    test_sessionmaker, seeded_user_car
):
    """When the photo extraction yields no usable fields (bad/blurry photo),
    the pending_edit_target must NOT be permanently consumed so the user can
    resend a clearer screenshot."""
    user_id, car_id = seeded_user_car
    session_id = await _seed_session(test_sessionmaker, user_id, car_id)

    # First extractor: returns empty extraction (no usable fields).
    empty_extraction = _make_extraction(
        energy_kwh=None,
        cost_total_pence=None,
        cost_per_kwh_pence=None,
        soc_start=None,
        soc_end=None,
        network=None,
        has_cost=False,
    )
    tg = FakeTg(files={"img": b"img", "img2": b"img2"})

    extractors = [
        ExtractionResult(extraction=empty_extraction, usage=Usage(10, 10, 0)),
        ExtractionResult(extraction=_make_extraction(), usage=Usage(10, 10, 0)),
    ]
    call_count = 0

    async def extractor(image_bytes: bytes):
        nonlocal call_count
        r = extractors[min(call_count, len(extractors) - 1)]
        call_count += 1
        return r

    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )

    # Arm the pending target.
    ctx.pending_edit_target[9] = (session_id, time.time())

    # First photo: extraction failure → pending should survive.
    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=1,
        file_id="img",
        caption=None,
    )

    assert 9 in ctx.pending_edit_target, (
        "pending_edit_target must survive an extraction-failure photo"
    )
    # An error message should have been sent.
    assert tg.sent, "Expected an error reply for empty extraction"
    assert any("couldn't read" in m["text"].lower() for m in tg.sent)

    # Second photo: good extraction → pending is consumed and proposal sent.
    await handle_photo(
        ctx,
        from_id=111,
        chat_id=9,
        message_id=2,
        file_id="img2",
        caption=None,
    )

    assert 9 not in ctx.pending_edit_target, (
        "pending_edit_target should be consumed by the second (good) photo"
    )
    proposal_msgs = [
        m for m in tg.sent if m.get("reply_markup") is not None
        and any(
            b["callback_data"].startswith("mcpcommit:")
            for row in m["reply_markup"]["inline_keyboard"]
            for b in row
        )
    ]
    assert proposal_msgs, "Expected a proposal card after good extraction"


# ---------------------------------------------------------------------------
# FIX — an inline "update session N, <soc>" edit command must route to the
# agentic loop (which can propose the edit), NOT the charge-note extractor
# (which would mis-read the embedded SoC as a brand-new undated reading).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inline_update_command_routes_to_agent_not_extractor(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    session_id = await _seed_session(test_sessionmaker, user_id, car_id)
    tg = FakeTg()

    calls: list[str] = []

    async def extractor_text(text: str):
        # Would greedily parse "74% to 81%" as a new reading — must NOT be called.
        calls.append("extractor_text")
        return ExtractionResult(
            extraction=_make_extraction(
                soc_start=74, soc_end=81, energy_kwh=None,
                cost_total_pence=None, cost_per_kwh_pence=None,
                start_at=None, end_at=None, location_name=None,
                location_address=None, network=None,
            ),
            usage=Usage(10, 10, 0),
        )

    async def agent_runner(*, session, user_id, text, history, api_key, model, **_kw):
        calls.append(f"agent:{text}")
        return {"reply_text": "Proposed edit", "proposal": {"change_token": "tok", "summary": "end SoC → 81%"}}

    ctx = IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=lambda b: None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
        extractor_text=extractor_text,
        agent_runner=agent_runner,
        ai_enabled=True,
        openai_key="sk-test",
    )

    await handle_text(ctx, from_id=111, chat_id=9, text=f"update session {session_id}, 74% to 81%")

    assert "extractor_text" not in calls, "edit command was mis-routed to the charge-note extractor"
    assert any(c.startswith("agent:") for c in calls), "edit command did not reach the agentic loop"
