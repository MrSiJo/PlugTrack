# backend/plugtrack/services/bot_agent.py
"""Agentic tool-calling loop for the Telegram bot.

Calls the OpenAI Responses API (httpx, function tool-calling) and dispatches
tool calls to the MCP tool core (mcp/tools.py) in-process, user-scoped.

Key design points
-----------------
- run_agent_turn is the entry point; tool_runner is injected so the loop is
  unit-testable with a fake runner.
- propose_* tool results cause the loop to STOP and return a proposal; the
  caller (handle_text) renders Save/Discard buttons.
- commit_change is available as a tool (for completeness) but the Telegram
  wiring never auto-commits — only the explicit mcpcommit: callback does.
- The loop is capped at MAX_TOOL_ITERATIONS to prevent runaway.
- Grounding discipline: the system prompt only permits answers drawn from
  tool results (mirrors usage_chat.py discipline).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC
from typing import Any

import httpx

from .screenshot_extraction import RESPONSES_URL

logger = logging.getLogger(__name__)

# Maximum number of tool-call iterations per turn (prevents runaway).
MAX_TOOL_ITERATIONS = 6

# Tool names that, when called, signal a propose_* result: stop the loop and
# return the result as a proposal for the user to confirm.
_PROPOSE_TOOL_NAMES = frozenset(
    {
        "propose_create_location",
        "propose_set_location",
        "propose_edit_charge",
    }
)

AGENT_SYSTEM_PROMPT = (
    "You are a helpful assistant for PlugTrack, an EV charging tracker. "
    "You help the user query and manage their charging history.\n\n"
    "GROUNDING RULE — CRITICAL: Only state facts that come directly from tool results. "
    "Never invent charge records, costs, dates, locations, or statistics. "
    "If you cannot answer from tool results, say so and offer to look it up. "
    "If the user asks for a change (add location, edit a charge), use the propose_* tools "
    "to prepare the change — the user must confirm with Save before anything is written. "
    "To edit a session, call propose_edit_charge with only the fields the user named — "
    "each field (start_soc, end_soc, kwh, total_cost_p, price_p_per_kwh, network, notes, "
    "date, odometer) is independent, so 'set the ending soc to 81 on session 34' changes "
    "only end_soc and leaves the rest untouched. "
    "NEVER pass 0 or an empty string for a field the user did not mention — omit it "
    "entirely. To erase a value, use clear_fields. If a propose_* result comes back with "
    "ignored_fields, you sent padding values: tell the user plainly which fields were "
    "left unchanged rather than presenting the edit as fully applied. "
    "Be concise, friendly, and use plain text (no Markdown, no asterisks). "
    "Dates are YYYY-MM-DD.\n"
    "MONEY FORMATTING: present totals and spend amounts in POUNDS as £X.XX "
    "(e.g. £9.85) — never quote the raw pence figure for a total. Present "
    "per-kWh rates and unit prices in PENCE (e.g. 7.5p/kWh). Tool results "
    "include pre-formatted fields for this — prefer 'spend' (pounds), 'cost' "
    "(pounds), 'avg_price' and 'tariff' (pence/kWh) over the raw *_pence fields.\n"
    "If a tool returns an error, tell the user plainly and offer alternatives."
)


# ---------------------------------------------------------------------------
# Tool catalogue (function definitions for the Responses API)
# ---------------------------------------------------------------------------


def build_tool_catalogue() -> list[dict[str, Any]]:
    """Return the list of function tool definitions for the Responses API.

    IMPORTANT: the Responses API expects the FLAT function-tool shape —
    ``{"type": "function", "name": ..., "description": ..., "parameters": {...}}`` —
    NOT the Chat Completions nested ``{"type": "function", "function": {...}}``
    shape (which 400s with "Missing required parameter: 'tools[0].name'"). The
    definitions below are authored nested for readability and flattened on return.
    """
    _nested = [
        {
            "type": "function",
            "function": {
                "name": "find_charges",
                "description": (
                    "Find charging sessions for the user. Returns a list of recent charges "
                    "ordered most-recent first. Supports optional filtering by date range "
                    "and location."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Optional text search query (reserved for future use).",
                        },
                        "date_from": {
                            "type": "string",
                            "description": "Start date filter in YYYY-MM-DD format (inclusive).",
                        },
                        "date_to": {
                            "type": "string",
                            "description": "End date filter in YYYY-MM-DD format (inclusive).",
                        },
                        "location_id": {
                            "type": "integer",
                            "description": "Filter by location ID.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default 10).",
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_charge",
                "description": "Get full details of a single charging session by ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "charge_id": {
                            "type": "integer",
                            "description": "The ID of the charging session.",
                        },
                    },
                    "required": ["charge_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_insights",
                "description": (
                    "Get aggregated insights/statistics about charging history, "
                    "including totals, home/public split, network breakdown, and trends over time."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date_from": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format.",
                        },
                        "date_to": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_create_location",
                "description": (
                    "Propose creating a new charging location. Returns a summary and change_token "
                    "for the user to confirm — writes nothing until confirmed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name for the location (e.g. 'Home', 'Work').",
                        },
                        "lat": {
                            "type": "number",
                            "description": "Latitude coordinate.",
                        },
                        "lng": {
                            "type": "number",
                            "description": "Longitude coordinate.",
                        },
                        "address": {
                            "type": "string",
                            "description": (
                                "Address string (used for geocoding if lat/lng not given)."
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_set_location",
                "description": (
                    "Propose setting the location on a charging session. "
                    "Returns a summary and change_token for user confirmation — writes nothing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "charge_id": {
                            "type": "integer",
                            "description": "The charging session ID to update.",
                        },
                        "location_id": {
                            "type": "integer",
                            "description": "The location ID to assign.",
                        },
                        "location_name": {
                            "type": "string",
                            "description": "Location name to look up (alternative to location_id).",
                        },
                    },
                    "required": ["charge_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_edit_charge",
                "description": (
                    "Propose editing fields on a charging session. "
                    "Returns a summary and change_token for user confirmation — writes nothing."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "charge_id": {
                            "type": "integer",
                            "description": (
                                "The charging session ID to edit. Pass ONLY this plus the "
                                "fields being changed — omitted fields keep their current "
                                "values. Never pad the call with zeros or empty strings."
                            ),
                        },
                        "kwh": {
                            "type": "number",
                            "description": "New energy in kWh.",
                        },
                        "price_p_per_kwh": {
                            "type": "number",
                            "description": "New rate in pence per kWh.",
                        },
                        "total_cost_p": {
                            "type": "integer",
                            "description": "New total cost in pence.",
                        },
                        "start_soc": {
                            "type": "integer",
                            "description": "New start state of charge (%).",
                        },
                        "end_soc": {
                            "type": "integer",
                            "description": "New end state of charge (%).",
                        },
                        "date": {
                            "type": "string",
                            "description": "New date in YYYY-MM-DD format.",
                        },
                        "network": {
                            "type": "string",
                            "description": "Charging network name.",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Notes for this session.",
                        },
                        "odometer": {
                            "type": "number",
                            "description": (
                                "New odometer reading in the user's distance unit "
                                "(miles unless they say km)."
                            ),
                        },
                        "odometer_unit": {
                            "type": "string",
                            "description": (
                                "mi or km; defaults to the user's display unit if omitted."
                            ),
                        },
                        "clear_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Fields to explicitly blank: notes, network, odometer, "
                                "price_p_per_kwh, total_cost_p. The ONLY way to erase a value — "
                                "never pass 0 or an empty string to clear something."
                            ),
                        },
                    },
                    "required": ["charge_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "commit_change",
                "description": (
                    "Apply a previously proposed change using its change_token. "
                    "Only call this when the user has explicitly confirmed they want to save."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "change_token": {
                            "type": "string",
                            "description": "The change_token returned by a propose_* tool.",
                        },
                    },
                    "required": ["change_token"],
                    "additionalProperties": False,
                },
            },
        },
    ]
    # Flatten to the Responses API shape: {"type": "function", "name", ...}.
    return [{"type": "function", **t["function"]} for t in _nested]


# ---------------------------------------------------------------------------
# Tool runner factory
# ---------------------------------------------------------------------------


def make_tool_runner(session, user_id: int) -> Callable[[str, dict], Awaitable[Any]]:
    """Return an async callable that routes tool_name + args → the tool-core functions.

    Binds `session` and `user_id` so the loop can call it without knowing them.
    """
    import datetime as dt

    from ..mcp import tools as tc

    async def run(tool_name: str, args: dict) -> Any:
        try:
            if tool_name == "find_charges":
                date_from = None
                date_to = None
                if args.get("date_from"):
                    date_from = dt.date.fromisoformat(args["date_from"])
                if args.get("date_to"):
                    date_to = dt.date.fromisoformat(args["date_to"])
                return await tc.find_charges(
                    session,
                    user_id,
                    query=args.get("query") or None,
                    date_from=date_from,
                    date_to=date_to,
                    location_id=(args.get("location_id") or None),
                    limit=int(args.get("limit") or 10),
                )
            elif tool_name == "get_charge":
                return await tc.get_charge(session, user_id, int(args["charge_id"]))
            elif tool_name == "get_insights":
                date_from = None
                date_to = None
                if args.get("date_from"):
                    date_from = dt.date.fromisoformat(args["date_from"])
                if args.get("date_to"):
                    date_to = dt.date.fromisoformat(args["date_to"])
                return await tc.get_insights(session, user_id, date_from=date_from, date_to=date_to)
            elif tool_name == "propose_create_location":
                return await tc.propose_create_location(
                    session,
                    user_id,
                    name=args.get("name"),
                    lat=args.get("lat"),
                    lng=args.get("lng"),
                    address=args.get("address"),
                )
            elif tool_name == "propose_set_location":
                return await tc.propose_set_location(
                    session,
                    user_id,
                    charge_id=int(args["charge_id"]),
                    location_id=(args.get("location_id") or None),
                    location_name=args.get("location_name") or None,
                )
            elif tool_name == "propose_edit_charge":
                date = None
                if args.get("date"):
                    date = dt.date.fromisoformat(args["date"])
                return await tc.propose_edit_charge(
                    session,
                    user_id,
                    charge_id=int(args["charge_id"]),
                    kwh=args.get("kwh"),
                    price_p_per_kwh=args.get("price_p_per_kwh"),
                    total_cost_p=args.get("total_cost_p"),
                    start_soc=args.get("start_soc"),
                    end_soc=args.get("end_soc"),
                    date=date,
                    network=args.get("network"),
                    notes=args.get("notes"),
                    odometer=args.get("odometer"),
                    odometer_unit=args.get("odometer_unit"),
                    clear_fields=args.get("clear_fields"),
                )
            elif tool_name == "commit_change":
                return await tc.commit_change(session, user_id, str(args["change_token"]))
            else:
                return {"error": f"unknown tool: {tool_name}"}
        except Exception as exc:
            logger.exception("tool_runner error for %s", tool_name)
            return {"error": str(exc)}

    return run


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


def _extract_tool_calls(body: dict) -> list[dict]:
    """Extract tool call items from a Responses API response body."""
    calls = []
    for item in body.get("output", []):
        if item.get("type") == "function_call":
            calls.append(item)
    return calls


def _extract_text(body: dict) -> str | None:
    """Extract the final text content from a Responses API response body."""
    for item in body.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return part.get("text")
    return None


async def run_agent_turn(
    *,
    session,
    user_id: int,
    text: str,
    history: list[dict],
    api_key: str,
    model: str,
    tool_runner: Callable[[str, dict], Awaitable[Any]],
) -> dict:
    """Run one user turn through the OpenAI tool-calling loop.

    Returns an AgentResult dict:
        reply_text: str | None   — the final text reply to send to the user
        proposal: dict | None    — {summary, change_token} if a propose_* tool was called
        usage: dict              — token usage summary

    The loop:
    1. Build payload with system prompt + history + user text + tool catalogue.
    2. POST to Responses API.
    3. If the response contains tool calls:
       a. Execute each via tool_runner.
       b. If a propose_* tool returned a change_token → capture as proposal, stop.
       c. Feed tool results back as a new input item.
       d. Loop (up to MAX_TOOL_ITERATIONS total).
    4. When the model returns a final text → return it as reply_text.
    """
    from datetime import datetime

    today = datetime.now(UTC).date().isoformat()
    date_line = (
        f"Today's date is {today}. When the user gives a relative date "
        "(today, yesterday, last week, this month), resolve it to YYYY-MM-DD "
        "against today before calling tools."
    )
    instructions = AGENT_SYSTEM_PROMPT + "\n\n" + date_line

    tools = build_tool_catalogue()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Build the initial input sequence
    input_items: list[dict] = []
    for turn in history:
        input_items.append(turn)
    input_items.append({"role": "user", "content": [{"type": "input_text", "text": text}]})

    usage_agg: dict = {}
    proposal: dict | None = None
    reply_text: str | None = None

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            for iteration in range(MAX_TOOL_ITERATIONS + 1):
                payload = {
                    "model": model,
                    "instructions": instructions,
                    "input": input_items,
                    "tools": tools,
                    "max_output_tokens": 1000,
                }

                try:
                    resp = await client.post(RESPONSES_URL, json=payload, headers=headers)
                    resp.raise_for_status()
                except Exception as exc:
                    logger.error("OpenAI Responses API error: %s", exc)
                    return {
                        "reply_text": "Sorry — I couldn't reach the AI right now.",
                        "proposal": None,
                        "usage": usage_agg,
                        "error": str(exc),
                    }

                body = resp.json()

                # Accumulate usage
                raw_usage = body.get("usage") or {}
                for k, v in raw_usage.items():
                    if isinstance(v, int):
                        usage_agg[k] = usage_agg.get(k, 0) + v

                # Check for tool calls
                tool_calls = _extract_tool_calls(body)
                if tool_calls:
                    # Append the assistant's tool-call turn to input
                    input_items.extend(body.get("output", []))

                    # Execute each tool call
                    tool_results: list[dict] = []
                    for call in tool_calls:
                        call_id = call.get("call_id", "")
                        tool_name = call.get("name", "")
                        try:
                            args = json.loads(call.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            args = {}

                        result = await tool_runner(tool_name, args)

                        # If a propose_* returned a change_token → capture as proposal
                        if tool_name in _PROPOSE_TOOL_NAMES and isinstance(result, dict):
                            if "change_token" in result and "error" not in result:
                                proposal = {
                                    "summary": result.get("summary", ""),
                                    "change_token": result["change_token"],
                                }

                        tool_results.append(
                            {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": json.dumps(result, default=str),
                            }
                        )

                    # Append tool results as next input
                    input_items.extend(tool_results)

                    # If we captured a proposal, do one more loop to get the model's
                    # confirmation text, then stop.
                    if proposal is not None and iteration >= MAX_TOOL_ITERATIONS - 1:
                        # Cap reached with a proposal: return what we have
                        break
                    # Otherwise continue the loop
                    continue

                # No tool calls → model returned a final text
                reply_text = _extract_text(body)
                break

            # If we hit the cap without a final text, give a fallback
            if reply_text is None and proposal is None:
                reply_text = (
                    "I've looked up the information but couldn't produce a final reply. "
                    "Please try rephrasing your question."
                )

    except Exception as exc:
        logger.exception("run_agent_turn unexpected error")
        return {
            "reply_text": "Sorry — something went wrong processing your request.",
            "proposal": None,
            "usage": usage_agg,
            "error": str(exc),
        }

    return {
        "reply_text": reply_text,
        "proposal": proposal,
        "usage": usage_agg,
    }
