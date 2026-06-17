import httpx
import pytest

from plugtrack.services.usage_chat import (
    USAGE_SYSTEM_PROMPT, build_usage_payload, answer_usage_question,
)


def test_payload_grounds_on_snapshot_and_question():
    snap = {"today": "2026-06-17", "windows": [{"label": "this month", "spend": "£42.18"}]}
    p = build_usage_payload("spend this month?", snap, model="gpt-5-mini", today="2026-06-17")
    assert p["model"] == "gpt-5-mini"
    assert p["reasoning"] == {"effort": "none"}
    assert "text" not in p                                   # free-text output, not structured
    assert "£42.18" in p["instructions"]                    # snapshot embedded
    assert "only" in p["instructions"].lower()              # grounding instruction present
    assert "need not add up" in p["instructions"]           # home/public split caveat present
    parts = p["input"][0]["content"]
    assert any("spend this month?" in c.get("text", "") for c in parts)


def _resp(text):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/responses"
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 50, "output_tokens": 20,
                      "output_tokens_details": {"reasoning_tokens": 0}},
        })
    return handler


@pytest.mark.asyncio
async def test_answer_returns_model_text():
    snap = {"today": "2026-06-17", "windows": [{"label": "this month", "spend": "£42.18"}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(_resp("You spent £42.18 this month."))) as c:
        text, usage = await answer_usage_question("spend this month?", snap,
                                                  api_key="sk", model="gpt-5-mini", client=c)
    assert text == "You spent £42.18 this month."
    assert usage.input_tokens == 50
