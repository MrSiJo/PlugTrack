# backend/plugtrack/services/usage_chat.py
"""Answer a free-text usage question grounded in a usage-stats snapshot.

The model may only restate numbers present in the snapshot JSON; the system
prompt forbids invented figures and mandates a refuse-with-capability-hint
fallback. Output is free text (no json_schema). Network I/O mirrors
`screenshot_extraction.call_openai` (same retry-on-effort + incomplete check).
"""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from .screenshot_extraction import (
    RESPONSES_URL, Usage, extract_output_text, parse_usage,
)

USAGE_SYSTEM_PROMPT = (
    "You answer the user's questions about their EV charging history. You may use "
    "ONLY the numbers in the JSON snapshot below — never compute new figures, never "
    "invent values, and never estimate beyond what is given. If the question cannot be "
    "answered from the snapshot, say you can't answer that and list what you CAN answer: "
    "spend, energy (kWh), average p/kWh, home vs public split, spend by network, and "
    "mileage / annual pace — over this month, last month, last 30 days, year to date, or "
    "lifetime. Be concise and friendly. Money is in £; distances are already in the "
    "user's units. Today is {today}.\n\nSNAPSHOT:\n{snapshot}"
)


def build_usage_payload(question: str, snapshot: dict, *, model: str, today: str) -> dict[str, Any]:
    instructions = USAGE_SYSTEM_PROMPT.format(
        today=today, snapshot=json.dumps(snapshot, ensure_ascii=False)
    )
    return {
        "model": model,
        "instructions": instructions,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": question}]}],
        "reasoning": {"effort": "none"},
        "max_output_tokens": 400,
    }


async def answer_usage_question(
    question: str, snapshot: dict, *, api_key: str, model: str,
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[str, Usage]:
    today = str(snapshot.get("today", ""))
    payload = build_usage_payload(question, snapshot, model=model, today=today)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        resp = await client.post(RESPONSES_URL, json=payload, headers=headers)
        if resp.status_code == 400 and "effort" in resp.text.lower():
            payload["reasoning"]["effort"] = "minimal"
            resp = await client.post(RESPONSES_URL, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") == "incomplete":
            reason = (body.get("incomplete_details") or {}).get("reason", "unknown")
            raise RuntimeError(f"OpenAI response incomplete: {reason}")
        text = extract_output_text(body)
        if not text:
            raise RuntimeError("OpenAI response had no output text")
        return text, parse_usage(body)
    finally:
        if owns:
            await client.aclose()
