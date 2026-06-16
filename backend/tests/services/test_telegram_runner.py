# backend/tests/services/test_telegram_runner.py
import asyncio
import pytest

from plugtrack.services.telegram_ingest import dispatch_update


class Spy:
    def __init__(self): self.calls = []


@pytest.mark.asyncio
async def test_dispatch_routes_photo(monkeypatch):
    calls = []

    async def fake_photo(ctx, **kw):  # noqa: ANN001
        calls.append(("photo", kw))

    async def fake_cb(ctx, **kw):  # noqa: ANN001
        calls.append(("cb", kw))

    monkeypatch.setattr("plugtrack.services.telegram_ingest.handle_photo", fake_photo)
    monkeypatch.setattr("plugtrack.services.telegram_ingest.handle_callback", fake_cb)

    update = {
        "update_id": 1,
        "message": {
            "message_id": 3, "chat": {"id": 9}, "from": {"id": 111},
            "photo": [{"file_id": "small"}, {"file_id": "big"}],
        },
    }
    await dispatch_update(ctx=None, update=update)
    assert calls and calls[0][0] == "photo"
    # Largest photo (last in array) chosen.
    assert calls[0][1]["file_id"] == "big"


@pytest.mark.asyncio
async def test_dispatch_routes_callback(monkeypatch):
    calls = []
    async def fake_cb(ctx, **kw):  # noqa: ANN001
        calls.append(kw)
    monkeypatch.setattr("plugtrack.services.telegram_ingest.handle_callback", fake_cb)
    update = {
        "update_id": 2,
        "callback_query": {
            "id": "cb9", "data": "save",
            "from": {"id": 111}, "message": {"chat": {"id": 9}},
        },
    }
    await dispatch_update(ctx=None, update=update)
    assert calls and calls[0]["data"] == "save"
