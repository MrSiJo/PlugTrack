# backend/plugtrack/services/screenshot_extraction.py
"""Extract a charge-session record from a screenshot via an OpenAI vision model.

The image is sent as a base64 data URI to the Responses API (`/v1/responses`)
with reasoning disabled (`reasoning:{effort:"none"}`) and the output constrained
to EXTRACTION_SCHEMA via `text.format` json_schema. Network I/O is isolated in
`call_openai` so tests can mock it; `build_request_payload`/`parse_extraction`/
`parse_usage`/`extract_output_text` are pure and unit-tested directly.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx

RESPONSES_URL = "https://api.openai.com/v1/responses"

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

SYSTEM_PROMPT = (
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


@dataclass(frozen=True)
class Usage:
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    reasoning_tokens: Optional[int]


@dataclass(frozen=True)
class ExtractionResult:
    extraction: "Extraction"
    usage: Usage


def build_request_payload(image_bytes: bytes, *, model: str) -> dict[str, Any]:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    fmt = {
        "type": "json_schema",
        "name": EXTRACTION_SCHEMA["name"],
        "strict": EXTRACTION_SCHEMA["strict"],
        "schema": EXTRACTION_SCHEMA["schema"],
    }
    return {
        "model": model,
        "instructions": SYSTEM_PROMPT,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"}
                ],
            }
        ],
        # Extraction is a direct field-read/classification task — no reasoning.
        "reasoning": {"effort": "none"},
        "text": {"format": fmt},
        "max_output_tokens": 800,
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


def extract_output_text(body: dict[str, Any]) -> str:
    # Prefer the convenience field if the API includes it.
    if isinstance(body.get("output_text"), str) and body["output_text"]:
        return body["output_text"]
    for item in body.get("output", []):
        if item.get("type") == "message":
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    return part.get("text", "")
    return ""


def parse_usage(body: dict[str, Any]) -> Usage:
    u = body.get("usage") or {}
    details = u.get("output_tokens_details") or {}
    return Usage(
        input_tokens=u.get("input_tokens"),
        output_tokens=u.get("output_tokens"),
        reasoning_tokens=details.get("reasoning_tokens"),
    )


async def call_openai(
    image_bytes: bytes, *, api_key: str, model: str,
    client: Optional[httpx.AsyncClient] = None,
) -> ExtractionResult:
    payload = build_request_payload(image_bytes, model=model)
    # Some models reject effort "none"; retry once at "minimal".
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=90)
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
        return ExtractionResult(
            extraction=parse_extraction(json.loads(text)),
            usage=parse_usage(body),
        )
    finally:
        if owns:
            await client.aclose()
