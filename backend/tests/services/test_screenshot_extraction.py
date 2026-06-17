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
    e = parse_extraction({
        "source": "osprey", "has_cost": True, "energy_kwh": 9.78,
        "cost_total_pence": 851, "cost_per_kwh_pence": 87.0,
        "start_at": "2026-06-12T14:26:00", "end_at": "2026-06-12T14:40:00",
        "soc_start": None, "soc_end": None, "location_name": "Land's End",
        "location_address": "TR19 7AA", "network": "Osprey", "peak_kw": 40.0,
        "confidence": 0.95,
    })
    assert isinstance(e, Extraction)
    assert e.energy_kwh == 9.78 and e.network == "Osprey" and e.has_cost is True


def test_parse_usage_reads_responses_usage_object():
    body = {"usage": {"input_tokens": 2400, "output_tokens": 410,
                      "output_tokens_details": {"reasoning_tokens": 0}}}
    u = parse_usage(body)
    assert u == Usage(input_tokens=2400, output_tokens=410, reasoning_tokens=0)


def test_extract_output_text_from_output_array():
    body = {"output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": "{\"x\":1}"}]},
    ]}
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
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": payload}]}],
            "usage": {"input_tokens": 2500, "output_tokens": 420,
                      "output_tokens_details": {"reasoning_tokens": 0}},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        result = await call_openai(b"img", api_key="sk-x", model="gpt-5-mini", client=c)
    assert isinstance(result, ExtractionResult)
    assert result.extraction.cost_total_pence == 1706
    assert result.usage.input_tokens == 2500


@pytest.mark.asyncio
async def test_call_openai_raises_on_incomplete():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [], "usage": {"input_tokens": 10, "output_tokens": 800},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(RuntimeError, match="incomplete"):
            await call_openai(b"img", api_key="sk-x", model="gpt-5-mini", client=c)
