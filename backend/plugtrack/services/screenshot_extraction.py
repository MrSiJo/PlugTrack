# backend/plugtrack/services/screenshot_extraction.py
"""Extract a charge-session record from a screenshot via an OpenAI vision model.

The image is sent as a base64 data URI to the Chat Completions API, constrained
to EXTRACTION_SCHEMA via response_format=json_schema. Network I/O is isolated in
`call_openai` so tests can mock it; `build_request_payload`/`parse_extraction`
are pure and unit-tested directly.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

EXTRACTION_SCHEMA: dict[str, Any] = {
    "name": "charge_session_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source": {"type": "string"},
            "has_cost": {"type": "boolean"},
            "energy_kwh": {"type": ["number", "null"]},
            "cost_total_pence": {"type": ["integer", "null"]},
            "cost_per_kwh_pence": {"type": ["number", "null"]},
            "start_at": {"type": ["string", "null"]},
            "end_at": {"type": ["string", "null"]},
            "soc_start": {"type": ["integer", "null"]},
            "soc_end": {"type": ["integer", "null"]},
            "location_name": {"type": ["string", "null"]},
            "location_address": {"type": ["string", "null"]},
            "network": {"type": ["string", "null"]},
            "peak_kw": {"type": ["number", "null"]},
            "confidence": {"type": "number"},
        },
        "required": [
            "source", "has_cost", "energy_kwh", "cost_total_pence",
            "cost_per_kwh_pence", "start_at", "end_at", "soc_start", "soc_end",
            "location_name", "location_address", "network", "peak_kw", "confidence",
        ],
    },
}

PROMPT = (
    "You are extracting a single EV charging session from a screenshot of a "
    "charging app (e.g. MyCupra, Osprey, Electroverse, Tesla). Read every visible "
    "field. MyCupra screenshots show state-of-charge %, a power curve, and start/end "
    "times but NO cost/energy. Network apps (Osprey/Tesla/Electroverse) show energy "
    "in kWh, total cost, and location but NO state-of-charge. Set has_cost true only "
    "if a monetary total is visible. Convert all money to integer pence. Use ISO 8601 "
    "for times, inferring the date shown. Null any field not present. confidence is "
    "0..1 for your overall read."
)


@dataclass(frozen=True)
class Extraction:
    source: str
    has_cost: bool
    energy_kwh: Optional[float]
    cost_total_pence: Optional[int]
    cost_per_kwh_pence: Optional[float]
    start_at: Optional[str]
    end_at: Optional[str]
    soc_start: Optional[int]
    soc_end: Optional[int]
    location_name: Optional[str]
    location_address: Optional[str]
    network: Optional[str]
    peak_kw: Optional[float]
    confidence: float


def build_request_payload(image_bytes: bytes, *, model: str) -> dict[str, Any]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "response_format": {"type": "json_schema", "json_schema": EXTRACTION_SCHEMA},
        "max_completion_tokens": 600,
    }


def parse_extraction(raw: dict[str, Any]) -> Extraction:
    return Extraction(
        source=str(raw.get("source") or "other"),
        has_cost=bool(raw.get("has_cost")),
        energy_kwh=raw.get("energy_kwh"),
        cost_total_pence=raw.get("cost_total_pence"),
        cost_per_kwh_pence=raw.get("cost_per_kwh_pence"),
        start_at=raw.get("start_at"),
        end_at=raw.get("end_at"),
        soc_start=raw.get("soc_start"),
        soc_end=raw.get("soc_end"),
        location_name=raw.get("location_name"),
        location_address=raw.get("location_address"),
        network=raw.get("network"),
        peak_kw=raw.get("peak_kw"),
        confidence=float(raw.get("confidence") or 0.0),
    )


async def call_openai(
    image_bytes: bytes, *, api_key: str, model: str, client: Optional[httpx.AsyncClient] = None
) -> Extraction:
    payload = build_request_payload(image_bytes, model=model)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        resp = await client.post(OPENAI_URL, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        return parse_extraction(json.loads(content))
    finally:
        if owns:
            await client.aclose()
