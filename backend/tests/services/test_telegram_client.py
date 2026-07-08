# backend/tests/services/test_telegram_client.py
import json

import httpx
import pytest
from plugtrack.services.telegram_client import TelegramClient


def _mock(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_get_updates_passes_offset():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 5}]})

    async with _mock(handler) as http:
        tc = TelegramClient(token="T", http=http)
        updates = await tc.get_updates(offset=42, timeout=0)
    assert "/botT/getUpdates" in seen["url"]
    assert "offset=42" in seen["url"]
    assert updates[0]["update_id"] == 5


@pytest.mark.asyncio
async def test_send_message_posts_chat_and_text():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["json"] = req.read().decode()
        return httpx.Response(200, json={"ok": True, "result": {}})

    async with _mock(handler) as http:
        tc = TelegramClient(token="T", http=http)
        await tc.send_message(chat_id=7, text="hi", reply_markup={"x": 1})
    assert "/botT/sendMessage" in captured["url"]
    # Parse rather than substring-match: httpx changed its JSON separator
    # style in 0.28 (compact, no space after ':'), and the wire format is
    # not what this test is about.
    body = json.loads(captured["json"])
    assert body["chat_id"] == 7
    assert body["text"] == "hi"
    assert body["reply_markup"] == {"x": 1}
