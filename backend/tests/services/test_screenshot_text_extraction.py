# backend/tests/services/test_screenshot_text_extraction.py
import httpx
import pytest

from plugtrack.services.screenshot_extraction import (
    ExtractionResult, build_text_request_payload, extract_from_text,
)


def test_text_payload_uses_input_text_and_schema():
    p = build_text_request_payload("home 9.3kwh 8h31m", model="gpt-5-mini")
    assert p["model"] == "gpt-5-mini"
    assert p["reasoning"] == {"effort": "none"}
    assert p["text"]["format"]["type"] == "json_schema"
    parts = p["input"][0]["content"]
    kinds = {c["type"] for c in parts}
    assert "input_text" in kinds and "input_image" not in kinds
    assert any("9.3kwh" in c.get("text", "") for c in parts)


def _resp(content):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/responses"
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message",
                        "content": [{"type": "output_text", "text": content}]}],
            "usage": {"input_tokens": 40, "output_tokens": 30,
                      "output_tokens_details": {"reasoning_tokens": 0}},
        })
    return handler


@pytest.mark.asyncio
async def test_extract_from_text_parses_home_note():
    content = (
        '{"source":"text","has_cost":false,"energy_kwh":9.3,"cost_total_pence":null,'
        '"cost_per_kwh_pence":null,"start_at":null,"end_at":null,"soc_start":null,'
        '"soc_end":null,"location_name":"home","location_address":null,'
        '"network":null,"peak_kw":null,"confidence":0.9}'
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_resp(content))) as c:
        res = await extract_from_text("home 9.3kwh 8h31m", api_key="sk", model="gpt-5-mini", client=c)
    assert isinstance(res, ExtractionResult)
    assert res.extraction.energy_kwh == 9.3
    assert res.extraction.location_name == "home"
    assert res.extraction.soc_start is None


@pytest.mark.asyncio
async def test_extract_from_text_non_charge_returns_zero_confidence():
    content = (
        '{"source":"text","has_cost":false,"energy_kwh":null,"cost_total_pence":null,'
        '"cost_per_kwh_pence":null,"start_at":null,"end_at":null,"soc_start":null,'
        '"soc_end":null,"location_name":null,"location_address":null,'
        '"network":null,"peak_kw":null,"confidence":0.0}'
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_resp(content))) as c:
        res = await extract_from_text("how much did I spend?", api_key="sk", model="gpt-5-mini", client=c)
    assert res.extraction.confidence == 0.0
    assert res.extraction.energy_kwh is None


@pytest.mark.asyncio
async def test_extract_from_text_parses_odometer():
    content = (
        '{"source":"text","has_cost":false,"energy_kwh":9.3,"cost_total_pence":null,'
        '"cost_per_kwh_pence":null,"start_at":null,"end_at":null,"soc_start":null,'
        '"soc_end":null,"location_name":"home","location_address":null,'
        '"network":null,"peak_kw":null,"confidence":0.9,'
        '"odometer":12345,"odometer_unit":"mi"}'
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(_resp(content))) as c:
        res = await extract_from_text("home 12345mi 9.3kwh 8h31m", api_key="sk", model="gpt-5-mini", client=c)
    assert res.extraction.odometer == 12345
    assert res.extraction.odometer_unit == "mi"
    assert res.extraction.energy_kwh == 9.3
