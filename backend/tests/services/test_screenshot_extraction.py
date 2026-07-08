# backend/tests/services/test_screenshot_extraction.py
import httpx
import pytest
from plugtrack.services.screenshot_extraction import (
    Extraction,
    ExtractionResult,
    Usage,
    build_request_payload,
    call_openai,
    extract_output_text,
    parse_extraction,
    parse_usage,
)


def test_payload_is_responses_shape_with_reasoning_off():
    p = build_request_payload(b"\x89PNG", model="gpt-5-mini")
    assert p["model"] == "gpt-5-mini"
    assert p["reasoning"] == {"effort": "none"}
    assert p["text"]["format"]["type"] == "json_schema"
    assert p["text"]["format"]["strict"] is True
    assert "instructions" in p and isinstance(p["instructions"], str) and p["instructions"]
    content = p["input"][0]["content"]
    img = next(c for c in content if c["type"] == "input_image")
    assert img["image_url"].startswith("data:image/png;base64,")
    assert "max_output_tokens" in p


def test_parse_extraction_maps_fields():
    e = parse_extraction(
        {
            "source": "osprey",
            "has_cost": True,
            "energy_kwh": 9.78,
            "cost_total_pence": 851,
            "cost_per_kwh_pence": 87.0,
            "start_at": "2026-06-12T14:26:00",
            "end_at": "2026-06-12T14:40:00",
            "soc_start": None,
            "soc_end": None,
            "location_name": "Land's End",
            "location_address": "TR19 7AA",
            "network": "Osprey",
            "peak_kw": 40.0,
            "confidence": 0.95,
        }
    )
    assert isinstance(e, Extraction)
    assert e.energy_kwh == 9.78 and e.network == "Osprey" and e.has_cost is True


def test_parse_usage_reads_responses_usage_object():
    body = {
        "usage": {
            "input_tokens": 2400,
            "output_tokens": 410,
            "output_tokens_details": {"reasoning_tokens": 0},
        }
    }
    u = parse_usage(body)
    assert u == Usage(input_tokens=2400, output_tokens=410, reasoning_tokens=0)


def test_extract_output_text_from_output_array():
    body = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": '{"x":1}'}]},
        ]
    }
    assert extract_output_text(body) == '{"x":1}'


@pytest.mark.asyncio
async def test_call_openai_parses_response_and_usage():
    payload = (
        '{"source":"tesla","has_cost":true,"energy_kwh":37.9124,'
        '"cost_total_pence":1706,"cost_per_kwh_pence":45,'
        '"start_at":"2026-06-13T08:43:00","end_at":null,"soc_start":null,'
        '"soc_end":null,"location_name":"Lifton","location_address":"PL16 0AA",'
        '"network":"Tesla Supercharger","peak_kw":null,"confidence":0.97}'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/responses"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": payload}]}
                ],
                "usage": {
                    "input_tokens": 2500,
                    "output_tokens": 420,
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        result = await call_openai(b"img", api_key="sk-x", model="gpt-5-mini", client=c)
    assert isinstance(result, ExtractionResult)
    assert result.extraction.cost_total_pence == 1706
    assert result.usage.input_tokens == 2500


@pytest.mark.asyncio
async def test_call_openai_raises_on_incomplete():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [],
                "usage": {"input_tokens": 10, "output_tokens": 800},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(RuntimeError, match="incomplete"):
            await call_openai(b"img", api_key="sk-x", model="gpt-5-mini", client=c)


@pytest.mark.asyncio
async def test_call_openai_retries_once_on_429(monkeypatch):
    """PLUG-H1: a transient 429/5xx gets one retry with backoff."""
    import plugtrack.services.screenshot_extraction as mod

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", no_sleep)

    calls = {"n": 0}
    payload = (
        '{"source":"osprey","has_cost":true,"energy_kwh":9.78,'
        '"cost_total_pence":851,"cost_per_kwh_pence":87,'
        '"start_at":null,"end_at":null,"soc_start":null,"soc_end":null,'
        '"location_name":null,"location_address":null,"network":null,'
        '"peak_kw":null,"confidence":0.9}'
    )

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": payload}]}
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        result = await call_openai(b"img", api_key="sk-x", model="gpt-5-mini", client=c)
    assert calls["n"] == 2
    assert result.extraction.cost_total_pence == 851


def test_schema_required_covers_all_properties():
    """Strict json_schema demands every property also appear in `required`;
    OpenAI 400s otherwise. Tests mock the API, so this guards the invariant
    that mocking can't (regression: 'peak_kw' was dropped from required)."""
    from plugtrack.services.screenshot_extraction import EXTRACTION_SCHEMA

    schema = EXTRACTION_SCHEMA["schema"]
    assert EXTRACTION_SCHEMA["strict"] is True
    assert set(schema["required"]) == set(schema["properties"])


def test_schema_has_odometer_fields():
    from plugtrack.services.screenshot_extraction import EXTRACTION_SCHEMA

    props = EXTRACTION_SCHEMA["schema"]["properties"]
    assert props["odometer"] == {"type": ["number", "null"]}
    assert props["odometer_unit"] == {"type": ["string", "null"]}
    req = EXTRACTION_SCHEMA["schema"]["required"]
    assert "odometer" in req and "odometer_unit" in req


def test_parse_extraction_reads_odometer():
    from plugtrack.services.screenshot_extraction import parse_extraction

    e = parse_extraction({"source": "text", "odometer": 12345, "odometer_unit": "mi"})
    assert e.odometer == 12345
    assert e.odometer_unit == "mi"


def test_parse_extraction_odometer_defaults_none():
    from plugtrack.services.screenshot_extraction import parse_extraction

    e = parse_extraction({"source": "text"})
    assert e.odometer is None and e.odometer_unit is None


def test_schema_has_location_short_name():
    from plugtrack.services.screenshot_extraction import EXTRACTION_SCHEMA

    props = EXTRACTION_SCHEMA["schema"]["properties"]
    assert props["location_short_name"] == {"type": ["string", "null"]}
    assert "location_short_name" in EXTRACTION_SCHEMA["schema"]["required"]


def test_parse_extraction_reads_location_short_name():
    from plugtrack.services.screenshot_extraction import parse_extraction

    e = parse_extraction({"source": "osprey", "location_short_name": "Osprey Land's End"})
    assert e.location_short_name == "Osprey Land's End"


def test_parse_extraction_short_name_defaults_none():
    from plugtrack.services.screenshot_extraction import parse_extraction

    assert parse_extraction({"source": "text"}).location_short_name is None


def test_schema_has_actual_charge_seconds():
    from plugtrack.services.screenshot_extraction import EXTRACTION_SCHEMA

    props = EXTRACTION_SCHEMA["schema"]["properties"]
    assert props["actual_charge_seconds"] == {"type": ["integer", "null"]}
    assert "actual_charge_seconds" in EXTRACTION_SCHEMA["schema"]["required"]


def test_parse_extraction_reads_actual_charge_seconds():
    from plugtrack.services.screenshot_extraction import parse_extraction

    e = parse_extraction({"source": "mycupra", "actual_charge_seconds": 32940})
    assert e.actual_charge_seconds == 32940


def test_parse_extraction_actual_charge_seconds_defaults_none():
    from plugtrack.services.screenshot_extraction import parse_extraction

    assert parse_extraction({"source": "text"}).actual_charge_seconds is None


def test_parse_extraction_reads_power_curve():
    raw = {
        "source": "mycupra",
        "has_cost": False,
        "energy_kwh": None,
        "cost_total_pence": None,
        "cost_per_kwh_pence": None,
        "start_at": "2026-06-18T11:26:00",
        "end_at": "2026-06-18T11:50:00",
        "soc_start": 55,
        "soc_end": 90,
        "location_name": None,
        "location_address": None,
        "location_short_name": None,
        "network": None,
        "peak_kw": 62,
        "odometer": None,
        "odometer_unit": None,
        "actual_charge_seconds": 1320,
        "confidence": 0.9,
        "power_curve": [[0.0, 0], [0.2, 62], [1.0, 48]],
    }
    e = parse_extraction(raw)
    assert e.power_curve == [[0.0, 0], [0.2, 62], [1.0, 48]]


def test_parse_extraction_power_curve_defaults_none():
    raw = {  # minimal AC-style payload, no power_curve key
        "source": "granny",
        "has_cost": False,
        "energy_kwh": 9.2,
        "cost_total_pence": None,
        "cost_per_kwh_pence": None,
        "start_at": None,
        "end_at": None,
        "soc_start": None,
        "soc_end": None,
        "location_name": None,
        "location_address": None,
        "location_short_name": None,
        "network": None,
        "peak_kw": None,
        "odometer": None,
        "odometer_unit": None,
        "actual_charge_seconds": 1200,
        "confidence": 0.8,
    }
    assert parse_extraction(raw).power_curve is None


# ---------------------------------------------------------------------------
# FIX 8 — cost_total_pence is coerced to int
# ---------------------------------------------------------------------------


def test_parse_extraction_cost_total_pence_float_coerced_to_int():
    """A model returning 851.0 (float) must be coerced to int 851 so it
    doesn't leak a float into an Integer database column (fix 8)."""
    e = parse_extraction({"source": "osprey", "cost_total_pence": 851.0})
    assert isinstance(e.cost_total_pence, int), f"Expected int, got {type(e.cost_total_pence)}"
    assert e.cost_total_pence == 851


def test_parse_extraction_cost_total_pence_none_stays_none():
    e = parse_extraction({"source": "mycupra", "cost_total_pence": None})
    assert e.cost_total_pence is None


def test_parse_extraction_cost_total_pence_int_unchanged():
    e = parse_extraction({"source": "osprey", "cost_total_pence": 1234})
    assert e.cost_total_pence == 1234
    assert isinstance(e.cost_total_pence, int)
