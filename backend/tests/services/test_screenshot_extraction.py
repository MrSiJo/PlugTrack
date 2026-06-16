# backend/tests/services/test_screenshot_extraction.py
import pytest

from plugtrack.services.screenshot_extraction import (
    Extraction,
    build_request_payload,
    parse_extraction,
)


def test_build_request_payload_has_image_and_schema():
    payload = build_request_payload(b"\x89PNG_fake", model="gpt-5.5")
    assert payload["model"] == "gpt-5.5"
    msg = payload["messages"][0]["content"]
    kinds = {part["type"] for part in msg}
    assert "image_url" in kinds and "text" in kinds
    img = next(p for p in msg if p["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")
    assert payload["response_format"]["type"] == "json_schema"


def test_parse_extraction_maps_fields():
    raw = {
        "source": "osprey",
        "has_cost": True,
        "energy_kwh": 9.78,
        "cost_total_pence": 851,
        "cost_per_kwh_pence": 87.0,
        "start_at": "2026-06-12T14:26:00",
        "end_at": "2026-06-12T14:40:00",
        "soc_start": None,
        "soc_end": None,
        "location_name": "Land's End Car Park, Penzance",
        "location_address": "TR19 7AA",
        "network": "Osprey",
        "peak_kw": 40.0,
        "confidence": 0.95,
    }
    e = parse_extraction(raw)
    assert isinstance(e, Extraction)
    assert e.energy_kwh == 9.78
    assert e.cost_total_pence == 851
    assert e.network == "Osprey"
    assert e.soc_start is None
    assert e.has_cost is True


@pytest.mark.asyncio
async def test_call_openai_parses_mocked_response(monkeypatch):
    import httpx
    from plugtrack.services import screenshot_extraction as se

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"source":"tesla","has_cost":true,'
                     '"energy_kwh":37.9124,"cost_total_pence":1706,'
                     '"cost_per_kwh_pence":45,"start_at":"2026-06-13T08:43:00",'
                     '"end_at":null,"soc_start":null,"soc_end":null,'
                     '"location_name":"Lifton","location_address":"PL16 0AA",'
                     '"network":"Tesla Supercharger","peak_kw":null,'
                     '"confidence":0.97}'}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        e = await se.call_openai(b"img", api_key="sk-x", model="gpt-5.5", client=client)
    assert e.cost_total_pence == 1706
    assert e.network == "Tesla Supercharger"
