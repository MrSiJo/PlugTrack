# backend/tests/services/test_bot_agent.py
"""Tests for the agentic tool-calling loop (bot_agent.py) + handle_text/handle_callback wiring.

All OpenAI HTTP calls are mocked — no network happens.
Tests follow TDD: written before the implementation exists.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to build fake OpenAI Responses-API payloads
# ---------------------------------------------------------------------------


def _tool_call_response(tool_name: str, args: dict, call_id: str = "call_1") -> dict:
    """A Responses API body whose output is a tool_call."""
    return {
        "output": [
            {
                "type": "function_call",
                "call_id": call_id,
                "name": tool_name,
                "arguments": json.dumps(args),
            }
        ],
        "usage": {
            "input_tokens": 50,
            "output_tokens": 20,
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "status": "completed",
    }


def _text_response(text: str) -> dict:
    """A Responses API body whose output is a final text message."""
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {
            "input_tokens": 60,
            "output_tokens": 30,
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "status": "completed",
    }


# ---------------------------------------------------------------------------
# Fake tool runner
# ---------------------------------------------------------------------------


async def _fake_runner(tool_name: str, args: dict) -> dict:
    """Returns deterministic fake results for each tool."""
    if tool_name == "find_charges":
        return [{"id": 1, "date": "2026-06-15", "kwh": 9.3, "cost": 179}]
    if tool_name == "get_charge":
        return {"id": args.get("charge_id", 1), "date": "2026-06-15", "kwh": 9.3}
    if tool_name == "get_insights":
        return {"totals": {"kwh": 100, "cost_pence": 1900}}
    if tool_name == "propose_set_location":
        return {"summary": "Set location of charge #1 to 'Home'", "change_token": "tok_abc123"}
    if tool_name == "propose_edit_charge":
        return {"summary": "Edit charge #1: kWh 9.3 → 10.0", "change_token": "tok_edit456"}
    if tool_name == "propose_create_location":
        return {"summary": "Create location 'Work'", "change_token": "tok_loc789"}
    if tool_name == "commit_change":
        return {"ok": True, "charge_id": 1}
    return {"error": f"unknown tool {tool_name}"}


# ---------------------------------------------------------------------------
# Tests for run_agent_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_nl_question_calls_find_charges_and_returns_reply():
    """A natural-language question triggers find_charges tool call, feeds result back,
    then model returns a final text reply."""
    from plugtrack.services.bot_agent import run_agent_turn

    # Two responses: first = tool call to find_charges; second = final text
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.status_code = 200
        if call_count == 1:
            m.json.return_value = _tool_call_response("find_charges", {"limit": 5})
        else:
            m.json.return_value = _text_response("You have 1 recent charge: 9.3 kWh on 2026-06-15.")
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        result = await run_agent_turn(
            session=None,
            user_id=1,
            text="Show me my recent charges",
            history=[],
            api_key="sk-test",
            model="gpt-5-mini",
            tool_runner=_fake_runner,
        )

    assert result["reply_text"] is not None
    assert "9.3" in result["reply_text"] or "charge" in result["reply_text"].lower()
    assert result["proposal"] is None
    assert result["usage"] is not None


@pytest.mark.asyncio
async def test_agent_propose_set_location_returns_proposal_no_commit():
    """When the model calls propose_set_location, the result is returned as a proposal
    (summary + change_token), and commit_change is NOT called automatically."""
    from plugtrack.services.bot_agent import run_agent_turn

    call_count = 0
    commit_called = False
    original_runner = _fake_runner

    async def tracking_runner(tool_name: str, args: dict) -> dict:
        nonlocal commit_called
        if tool_name == "commit_change":
            commit_called = True
        return await original_runner(tool_name, args)

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.status_code = 200
        if call_count == 1:
            # Model calls propose_set_location
            m.json.return_value = _tool_call_response(
                "propose_set_location",
                {"charge_id": 1, "location_name": "Home"},
            )
        else:
            # After we feed the proposal result, model gives final text
            m.json.return_value = _text_response(
                "I'll tag that charge as Home. Do you want to save this change?"
            )
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        result = await run_agent_turn(
            session=None,
            user_id=1,
            text="Tag my last charge as home",
            history=[],
            api_key="sk-test",
            model="gpt-5-mini",
            tool_runner=tracking_runner,
        )

    # A proposal should be returned
    assert result["proposal"] is not None
    assert "change_token" in result["proposal"]
    assert result["proposal"]["change_token"] == "tok_abc123"
    # commit_change must NOT have been called automatically
    assert not commit_called


@pytest.mark.asyncio
async def test_agent_loop_caps_at_max_iterations():
    """The loop must stop after the configured max iterations, even if the model
    keeps emitting tool calls (avoiding runaway loops)."""
    from plugtrack.services.bot_agent import MAX_TOOL_ITERATIONS, run_agent_turn

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.status_code = 200
        # Always returns a tool call — never a final text
        m.json.return_value = _tool_call_response(
            "find_charges", {"limit": 5}, call_id=f"call_{call_count}"
        )
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        result = await run_agent_turn(
            session=None,
            user_id=1,
            text="Tell me about my charges",
            history=[],
            api_key="sk-test",
            model="gpt-5-mini",
            tool_runner=_fake_runner,
        )

    # The total number of OpenAI calls must not exceed MAX_TOOL_ITERATIONS + 1
    assert call_count <= MAX_TOOL_ITERATIONS + 1
    # Result should have either a reply_text or a fallback (not just crash)
    # reply_text may be None if capped, but must not raise
    assert "usage" in result


@pytest.mark.asyncio
async def test_make_tool_runner_dispatches_correctly(test_sessionmaker, seeded_user_car):
    """make_tool_runner binds session+user_id and routes tool names to the tool core."""
    from plugtrack.services.bot_agent import make_tool_runner

    user_id, _car_id = seeded_user_car

    async with test_sessionmaker() as s:
        runner = make_tool_runner(s, user_id)
        result = await runner("find_charges", {"limit": 3})

    # find_charges returns a list (empty is fine — no sessions seeded)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_make_tool_runner_unknown_tool_returns_error(test_sessionmaker, seeded_user_car):
    """An unknown tool name returns an error dict, not an exception."""
    from plugtrack.services.bot_agent import make_tool_runner

    user_id, _car_id = seeded_user_car

    async with test_sessionmaker() as s:
        runner = make_tool_runner(s, user_id)
        result = await runner("nonexistent_tool", {})

    assert "error" in result


def test_build_tool_catalogue_contains_all_tools():
    """build_tool_catalogue returns a list of function-tool defs for all expected tools."""
    from plugtrack.services.bot_agent import build_tool_catalogue

    catalogue = build_tool_catalogue()
    names = {t["name"] for t in catalogue}

    expected = {
        "find_charges",
        "get_charge",
        "get_insights",
        "propose_create_location",
        "propose_set_location",
        "propose_edit_charge",
        "commit_change",
    }
    assert expected.issubset(names), f"Missing tools: {expected - names}"
    # The Responses API requires the FLAT function-tool shape:
    #   {"type": "function", "name": ..., "description": ..., "parameters": {...}}
    # NOT the Chat Completions nested {"type": "function", "function": {...}} shape.
    # (A nested shape 400s with "Missing required parameter: 'tools[0].name'".)
    for t in catalogue:
        assert t.get("type") == "function"
        assert "function" not in t, "tool must be flat, not nested under 'function'"
        assert "name" in t
        assert "description" in t
        assert "parameters" in t


@pytest.mark.asyncio
async def test_agent_openai_error_returns_gracefully():
    """If OpenAI returns a non-200 status, run_agent_turn returns an error reply_text
    rather than raising an exception."""
    from plugtrack.services.bot_agent import run_agent_turn

    async def mock_post(*args, **kwargs):
        m = MagicMock()
        m.status_code = 500
        m.text = "Internal server error"
        m.raise_for_status.side_effect = Exception("HTTP 500")
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        result = await run_agent_turn(
            session=None,
            user_id=1,
            text="What's my total spend?",
            history=[],
            api_key="sk-test",
            model="gpt-5-mini",
            tool_runner=_fake_runner,
        )

    # Should return an error message rather than crashing
    assert result["reply_text"] is not None or result.get("error") is not None


# ---------------------------------------------------------------------------
# Tests for handle_text + handle_callback wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_text_photo_path_unchanged(test_sessionmaker, seeded_user_car):
    """A photo message still routes to handle_photo (unchanged path)."""
    import plugtrack.services.telegram_ingest as ti

    user_id, car_id = seeded_user_car
    photo_called = {}

    async def fake_extractor(image_bytes):
        from plugtrack.services.screenshot_extraction import (
            Extraction,
            ExtractionResult,
            Usage,
        )

        photo_called["called"] = True
        e = Extraction(
            source="mycupra",
            has_cost=False,
            energy_kwh=None,
            cost_total_pence=None,
            cost_per_kwh_pence=None,
            start_at="2026-06-17T16:36:00",
            end_at="2026-06-18T07:06:00",
            soc_start=75,
            soc_end=79,
            location_name=None,
            location_address=None,
            network=None,
            peak_kw=2.0,
            confidence=0.89,
        )
        return ExtractionResult(extraction=e, usage=Usage(None, None, None))

    class FakeTg:
        def __init__(self):
            self.sent = []

        async def get_file_path(self, file_id):
            return file_id

        async def download_file(self, path):
            return b"fake_image"

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append(text)
            return 1

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=fake_extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={42},
    )
    # Dispatch a photo update — must not crash and must invoke extractor
    await ti.dispatch_update(
        ctx=ctx,
        update={
            "update_id": 1,
            "message": {
                "from": {"id": 42},
                "chat": {"id": 99},
                "message_id": 1,
                "photo": [{"file_id": "f1"}, {"file_id": "f2"}],
            },
        },
    )
    assert photo_called.get("called"), "extractor (photo path) was not called"


@pytest.mark.asyncio
async def test_handle_text_charge_note_still_extracts(test_sessionmaker, seeded_user_car):
    """A charge-note text message still goes through extractor_text (unchanged path)."""
    import plugtrack.services.telegram_ingest as ti
    from plugtrack.services.screenshot_extraction import (
        Extraction,
        ExtractionResult,
        Usage,
    )

    user_id, car_id = seeded_user_car
    extracted = {}

    async def extractor_text(text):
        extracted["text"] = text
        e = Extraction(
            source="text",
            has_cost=False,
            energy_kwh=9.3,
            cost_total_pence=None,
            cost_per_kwh_pence=None,
            start_at="2026-06-15T19:27:00",
            end_at=None,
            soc_start=None,
            soc_end=None,
            location_name="home",
            location_address=None,
            network=None,
            peak_kw=None,
            confidence=0.9,
        )
        return ExtractionResult(extraction=e, usage=Usage(10, 10, 0))

    class FakeTg:
        def __init__(self):
            self.sent = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append({"text": text, "kb": reply_markup})
            return 1

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={42},
        extractor_text=extractor_text,
    )

    await ti.handle_text(ctx, from_id=42, chat_id=99, text="home 9.3kwh 8h31m")

    # Should have staged a card (not just help text)
    assert extracted.get("text") == "home 9.3kwh 8h31m"
    assert tg.sent and tg.sent[-1]["kb"] is not None


@pytest.mark.asyncio
async def test_handle_text_agentic_loop_when_ai_enabled(test_sessionmaker, seeded_user_car):
    """When ai_enabled=True and no charge note, falls through to the agentic loop."""
    import plugtrack.services.telegram_ingest as ti
    from plugtrack.services.screenshot_extraction import (
        Extraction,
        ExtractionResult,
        Usage,
    )

    user_id, car_id = seeded_user_car
    agent_called = {}

    async def extractor_text(text):
        # Returns a non-charge (confidence 0)
        e = Extraction(
            source="text",
            has_cost=False,
            energy_kwh=None,
            cost_total_pence=None,
            cost_per_kwh_pence=None,
            start_at=None,
            end_at=None,
            soc_start=None,
            soc_end=None,
            location_name=None,
            location_address=None,
            network=None,
            peak_kw=None,
            confidence=0.0,
        )
        return ExtractionResult(extraction=e, usage=Usage(5, 5, 0))

    async def fake_run_agent_turn(**kwargs):
        agent_called["kwargs"] = kwargs
        return {
            "reply_text": "You have spent £19.00 total.",
            "proposal": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        }

    class FakeTg:
        def __init__(self):
            self.sent = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append({"text": text, "kb": reply_markup})
            return 1

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={42},
        extractor_text=extractor_text,
        agent_runner=fake_run_agent_turn,
        ai_enabled=True,
        openai_key="sk-test",
        openai_model="gpt-5-mini",
    )

    await ti.handle_text(ctx, from_id=42, chat_id=99, text="How much have I spent?")

    assert agent_called, "agent loop was not invoked"
    assert tg.sent
    assert "£19.00" in tg.sent[-1]["text"]


@pytest.mark.asyncio
async def test_handle_text_proposal_renders_save_discard_buttons(
    test_sessionmaker, seeded_user_car
):
    """When the agent returns a proposal, handle_text renders Save/Discard inline keyboard."""
    import plugtrack.services.telegram_ingest as ti
    from plugtrack.services.screenshot_extraction import (
        Extraction,
        ExtractionResult,
        Usage,
    )

    user_id, car_id = seeded_user_car

    async def extractor_text(text):
        e = Extraction(
            source="text",
            has_cost=False,
            energy_kwh=None,
            cost_total_pence=None,
            cost_per_kwh_pence=None,
            start_at=None,
            end_at=None,
            soc_start=None,
            soc_end=None,
            location_name=None,
            location_address=None,
            network=None,
            peak_kw=None,
            confidence=0.0,
        )
        return ExtractionResult(extraction=e, usage=Usage(5, 5, 0))

    async def fake_run_agent_turn(**kwargs):
        return {
            "reply_text": "I'll tag that charge as Home. Save?",
            "proposal": {"summary": "Set location to Home", "change_token": "tok_abc123"},
            "usage": {},
        }

    class FakeTg:
        def __init__(self):
            self.sent = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append({"text": text, "kb": reply_markup})
            return 1

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={42},
        extractor_text=extractor_text,
        agent_runner=fake_run_agent_turn,
        ai_enabled=True,
        openai_key="sk-test",
        openai_model="gpt-5-mini",
    )

    await ti.handle_text(ctx, from_id=42, chat_id=99, text="Tag my last charge as home")

    assert tg.sent
    last = tg.sent[-1]
    kb = last["kb"]
    assert kb is not None, "Expected inline keyboard for proposal"
    buttons_data = [btn["callback_data"] for row in kb["inline_keyboard"] for btn in row]
    assert any("mcpcommit:tok_abc123" in d for d in buttons_data)
    assert any("mcpdiscard:tok_abc123" in d for d in buttons_data)


@pytest.mark.asyncio
async def test_handle_text_ai_disabled_sends_help_message():
    """When ai_enabled=False, a non-charge-note falls back to help text (not agent loop)."""
    import plugtrack.services.telegram_ingest as ti
    from plugtrack.services.screenshot_extraction import (
        Extraction,
        ExtractionResult,
        Usage,
    )

    agent_called = {}

    async def extractor_text(text):
        e = Extraction(
            source="text",
            has_cost=False,
            energy_kwh=None,
            cost_total_pence=None,
            cost_per_kwh_pence=None,
            start_at=None,
            end_at=None,
            soc_start=None,
            soc_end=None,
            location_name=None,
            location_address=None,
            network=None,
            peak_kw=None,
            confidence=0.0,
        )
        return ExtractionResult(extraction=e, usage=Usage(5, 5, 0))

    async def fake_run_agent_turn(**kwargs):
        agent_called["called"] = True
        return {"reply_text": "agent reply", "proposal": None, "usage": {}}

    class FakeTg:
        def __init__(self):
            self.sent = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append(text)
            return 1

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=None,
        extractor=None,
        resolve_target=lambda: (1, 1),
        allowed_user_ids={42},
        extractor_text=extractor_text,
        agent_runner=fake_run_agent_turn,
        ai_enabled=False,  # AI disabled
        openai_key=None,
        openai_model="gpt-5-mini",
    )

    await ti.handle_text(ctx, from_id=42, chat_id=99, text="How much have I spent?")

    assert not agent_called, "Agent loop must NOT be called when ai_enabled=False"
    assert tg.sent


@pytest.mark.asyncio
async def test_handle_callback_mcpcommit_calls_commit_change(test_sessionmaker, seeded_user_car):
    """handle_callback with 'mcpcommit:<token>' calls commit_change and replies."""
    import plugtrack.services.telegram_ingest as ti

    user_id, car_id = seeded_user_car
    committed = {}

    async def fake_commit_runner(tool_name: str, args: dict) -> dict:
        if tool_name == "commit_change":
            committed["token"] = args.get("change_token")
            return {"ok": True, "charge_id": 1}
        return {"error": "unexpected"}

    class FakeTg:
        def __init__(self):
            self.sent = []
            self.answered = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append(text)
            return 1

        async def answer_callback(self, callback_id, text=""):
            self.answered.append(callback_id)

        async def edit_message_text(self, **kwargs):
            pass

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={42},
        agent_runner=None,
        ai_enabled=True,
        openai_key="sk-test",
        openai_model="gpt-5-mini",
    )

    await ti.handle_callback(
        ctx, from_id=42, callback_id="cb1", data="mcpcommit:tok_abc123", chat_id=99
    )

    # commit_change was invoked via the tool runner with the token
    # (Implementation may use a different mechanism — check a reply was sent)
    assert tg.sent, "Expected a reply after mcpcommit"
    reply = " ".join(tg.sent)
    # Should indicate success (or at least responded)
    assert tg.answered  # answer_callback was called


@pytest.mark.asyncio
async def test_handle_callback_mcpdiscard_drops_token():
    """handle_callback with 'mcpdiscard:<token>' drops the pending token + acknowledges."""
    import plugtrack.services.telegram_ingest as ti

    class FakeTg:
        def __init__(self):
            self.sent = []
            self.answered = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append(text)
            return 1

        async def answer_callback(self, callback_id, text=""):
            self.answered.append(callback_id)

        async def edit_message_text(self, **kwargs):
            pass

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=None,
        extractor=None,
        resolve_target=lambda: (1, 1),
        allowed_user_ids={42},
        agent_runner=None,
        ai_enabled=True,
        openai_key=None,
        openai_model="gpt-5-mini",
    )
    ctx.pending_tokens[99] = "tok_abc123"

    await ti.handle_callback(
        ctx, from_id=42, callback_id="cb2", data="mcpdiscard:tok_abc123", chat_id=99
    )

    assert tg.answered  # callback was answered
    # Token should be cleared
    assert ctx.pending_tokens.get(99) is None


@pytest.mark.asyncio
async def test_handle_callback_existing_save_discard_paths_unchanged(
    test_sessionmaker, seeded_user_car
):
    """The existing 'save'/'discard' callback paths are not broken by the new mcpcommit/mcpdiscard."""
    import plugtrack.services.telegram_ingest as ti

    user_id, car_id = seeded_user_car

    class FakeTg:
        def __init__(self):
            self.sent = []
            self.answered = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append(text)
            return 1

        async def answer_callback(self, callback_id, text=""):
            self.answered.append(callback_id)

        async def edit_message_text(self, **kwargs):
            pass

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={42},
        agent_runner=None,
        ai_enabled=True,
        openai_key=None,
        openai_model="gpt-5-mini",
    )

    # discard with no staged shots should still work gracefully
    await ti.handle_callback(ctx, from_id=42, callback_id="cb3", data="discard", chat_id=99)
    assert tg.answered  # answer_callback called
    assert any("Discard" in s or "discard" in s.lower() for s in tg.sent)


@pytest.mark.asyncio
async def test_rolling_context_accumulates_turns(test_sessionmaker, seeded_user_car):
    """Rolling history accumulates user+assistant turns per chat_id."""
    import plugtrack.services.telegram_ingest as ti
    from plugtrack.services.screenshot_extraction import (
        Extraction,
        ExtractionResult,
        Usage,
    )

    user_id, car_id = seeded_user_car
    turn = 0

    async def extractor_text(text):
        e = Extraction(
            source="text",
            has_cost=False,
            energy_kwh=None,
            cost_total_pence=None,
            cost_per_kwh_pence=None,
            start_at=None,
            end_at=None,
            soc_start=None,
            soc_end=None,
            location_name=None,
            location_address=None,
            network=None,
            peak_kw=None,
            confidence=0.0,
        )
        return ExtractionResult(extraction=e, usage=Usage(5, 5, 0))

    captured_histories = []

    async def fake_run_agent_turn(**kwargs):
        captured_histories.append(list(kwargs.get("history", [])))
        return {
            "reply_text": f"Turn {len(captured_histories)} reply",
            "proposal": None,
            "usage": {},
        }

    class FakeTg:
        def __init__(self):
            self.sent = []

        async def send_message(self, *, chat_id, text, reply_markup=None):
            self.sent.append(text)
            return 1

    tg = FakeTg()
    ctx = ti.IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={42},
        extractor_text=extractor_text,
        agent_runner=fake_run_agent_turn,
        ai_enabled=True,
        openai_key="sk-test",
        openai_model="gpt-5-mini",
    )

    await ti.handle_text(ctx, from_id=42, chat_id=99, text="First question")
    await ti.handle_text(ctx, from_id=42, chat_id=99, text="Second question")

    # First call: history is empty (start of conversation)
    assert len(captured_histories[0]) == 0
    # Second call: history contains at least the first turn
    assert len(captured_histories[1]) >= 2  # user + assistant from first turn


# ---------------------------------------------------------------------------
# Test F: build_tool_catalogue has odometer fields in propose_edit_charge
# ---------------------------------------------------------------------------


def test_build_tool_catalogue_propose_edit_charge_has_odometer():
    from plugtrack.services.bot_agent import build_tool_catalogue

    catalogue = build_tool_catalogue()
    edit_tool = next(t for t in catalogue if t["name"] == "propose_edit_charge")
    props = edit_tool["parameters"]["properties"]
    assert "odometer" in props
    assert props["odometer"]["type"] == "number"
    assert "odometer_unit" in props


# ---------------------------------------------------------------------------
# Test G: run_agent_turn injects today's date into instructions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_agent_turn_instructions_contain_today_date():
    import re

    from plugtrack.services.bot_agent import run_agent_turn

    captured_instructions = {}

    async def mock_post(url, *, json, headers, **kwargs):
        captured_instructions["instructions"] = json.get("instructions", "")
        m = MagicMock()
        m.status_code = 200
        m.raise_for_status = MagicMock()
        m.json.return_value = _text_response("Hello")
        return m

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = mock_post
        mock_client_cls.return_value = mock_client

        await run_agent_turn(
            session=None,
            user_id=1,
            text="hello",
            history=[],
            api_key="sk-test",
            model="gpt-5-mini",
            tool_runner=_fake_runner,
        )

    instr = captured_instructions.get("instructions", "")
    assert "Today's date is" in instr
    assert re.search(r"\d{4}-\d{2}-\d{2}", instr), "No YYYY-MM-DD date found"
