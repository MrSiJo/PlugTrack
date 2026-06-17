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
            "location_short_name": {"type": ["string", "null"]},
            "network": {"type": ["string", "null"]},
            "peak_kw": {"type": ["number", "null"]},
            "odometer": {"type": ["number", "null"]},
            "odometer_unit": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
        },
        "required": [
            "source", "has_cost", "energy_kwh", "cost_total_pence",
            "cost_per_kwh_pence", "start_at", "end_at", "soc_start", "soc_end",
            "location_name", "location_address", "location_short_name", "network",
            "peak_kw", "odometer", "odometer_unit", "confidence",
        ],
    },
}

SYSTEM_PROMPT = (
    "You are extracting a single EV charging session from a screenshot of a "
    "charging app (e.g. MyCupra, Osprey, Electroverse, Tesla) OR a portable "
    "home charger / 'granny' charger / EVSE meter display. Read every visible "
    "field. MyCupra screenshots show state-of-charge %, a power curve, and start/end "
    "times but NO cost/energy. Network apps (Osprey/Tesla/Electroverse) show energy "
    "in kWh, total cost, and location but NO state-of-charge. A granny/EVSE meter "
    "display shows delivered energy in kWh and an elapsed/charging time, but NO "
    "state-of-charge, cost, or location (set source='granny'). Set has_cost true only "
    "if a monetary total is visible. Convert all money to integer pence. Use ISO 8601 "
    "for times, inferring the date shown. Null any field not present. confidence is "
    "0..1 for your overall read. "
    "If an odometer / mileage reading is visible (e.g. a MyCupra vehicle status "
    "screen), put the number in odometer and its unit ('mi' or 'km') in odometer_unit "
    "if shown; otherwise null both. "
    "Also produce location_short_name: a concise '<Network> <Place>' label for this "
    "charge, e.g. 'Tesla Lifton', 'Osprey Land's End', 'MFG Morrisons Yeovil'. Normalise "
    "the network ('Supercharging'/'Tesla Supercharging' -> 'Tesla'), and drop site noise "
    "('Car Park', bay numbers, ', UK'). Null it if this is not a recognisable public "
    "charging site. "
)

TEXT_SYSTEM_PROMPT = (
    "You are parsing a short free-text note about a single EV charging session "
    "into the schema. The note may give delivered energy (e.g. '9.3kwh', '9.3 kWh'), "
    "a duration (e.g. '8h31m', '8hrs 31mins', '8:31'), and/or a location word such "
    "as 'home'. Put delivered energy in energy_kwh and any location word in "
    "location_name. If a clock start time is given, use it for start_at (ISO 8601); a "
    "bare duration with no clock time leaves start_at/end_at null. There is no SoC or "
    "cost in such notes unless explicitly stated. Null anything absent. If the text is "
    "NOT a charging note (e.g. a question or chit-chat), return confidence 0 with all "
    "fields null. source='text'. "
    "A number with a 'mi'/'miles'/'km' suffix or an explicit 'odo'/'mileage' word is an "
    "odometer reading: put the number in odometer and the unit in odometer_unit. Only set "
    "odometer when such a suffix or word is present, so you never mistake the energy value "
    "(e.g. the 9.3 of '9.3kwh') for mileage. If an odometer number has no unit suffix, set "
    "odometer and leave odometer_unit null. "
    "Set location_short_name null (free-text home notes have no public-site name). "
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
    odometer: Optional[float] = None
    odometer_unit: Optional[str] = None
    location_short_name: Optional[str] = None


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
        odometer=raw.get("odometer"),
        odometer_unit=raw.get("odometer_unit"),
        location_short_name=raw.get("location_short_name"),
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


def build_text_request_payload(text: str, *, model: str) -> dict[str, Any]:
    fmt = {
        "type": "json_schema",
        "name": EXTRACTION_SCHEMA["name"],
        "strict": EXTRACTION_SCHEMA["strict"],
        "schema": EXTRACTION_SCHEMA["schema"],
    }
    return {
        "model": model,
        "instructions": TEXT_SYSTEM_PROMPT,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": text}]}],
        "reasoning": {"effort": "none"},
        "text": {"format": fmt},
        "max_output_tokens": 400,
    }


async def extract_from_text(
    text: str, *, api_key: str, model: str,
    client: Optional[httpx.AsyncClient] = None,
) -> ExtractionResult:
    payload = build_text_request_payload(text, model=model)
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
        out = extract_output_text(body)
        if not out:
            raise RuntimeError("OpenAI response had no output text")
        return ExtractionResult(extraction=parse_extraction(json.loads(out)), usage=parse_usage(body))
    finally:
        if owns:
            await client.aclose()
