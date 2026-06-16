# backend/tests/services/test_telegram_ingest.py
import hashlib
import json
from pathlib import Path

import pytest

from plugtrack.services.screenshot_extraction import parse_extraction
from plugtrack.services.telegram_ingest import IngestContext, handle_photo, handle_callback

FX = Path(__file__).parent.parent / "fixtures" / "screenshots"


class FakeTelegram:
    def __init__(self, files: dict[str, bytes]):
        self._files = files
        self.sent: list[dict] = []
        self.answered: list[str] = []

    async def get_file_path(self, file_id):  # noqa: ANN001
        return file_id

    async def download_file(self, file_path):  # noqa: ANN001
        return self._files[file_path]

    async def send_message(self, *, chat_id, text, reply_markup=None):  # noqa: ANN001
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    async def answer_callback(self, callback_id, text=""):  # noqa: ANN001
        self.answered.append(callback_id)


def _ctx(tg, test_sessionmaker, car_id, user_id):
    async def extractor(image_bytes: bytes):
        # Map fake file bytes -> the matching fixture by content tag.
        name = image_bytes.decode()
        return parse_extraction(json.loads((FX / name).read_text()))

    return IngestContext(
        telegram=tg,
        sessionmaker=test_sessionmaker,
        extractor=extractor,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
    )


@pytest.mark.asyncio
async def test_two_photos_one_session_staged_and_committed(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    files = {"osprey.json": b"osprey.json", "mycupra_1240.json": b"mycupra_1240.json"}
    tg = FakeTelegram(files)
    ctx = _ctx(tg, test_sessionmaker, car_id, user_id)

    await handle_photo(ctx, from_id=111, chat_id=9, message_id=1, file_id="osprey.json")
    await handle_photo(ctx, from_id=111, chat_id=9, message_id=2, file_id="mycupra_1240.json")

    # The last reply should summarise ONE merged session and offer Save.
    last = tg.sent[-1]
    assert "9.78" in last["text"] or "Osprey" in last["text"]
    assert last["reply_markup"] is not None

    # Simulate the Save button callback.
    await handle_callback(ctx, from_id=111, callback_id="cb1", data="save", chat_id=9)

    from sqlalchemy import select
    from plugtrack.models import ChargingSession
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ChargingSession))).scalars().all()
    assert len(rows) == 1
    assert rows[0].total_cost_pence_override == 851
    assert rows[0].start_soc == 56


@pytest.mark.asyncio
async def test_disallowed_user_ignored(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    tg = FakeTelegram({"osprey.json": b"osprey.json"})
    ctx = _ctx(tg, test_sessionmaker, car_id, user_id)
    await handle_photo(ctx, from_id=999, chat_id=9, message_id=1, file_id="osprey.json")
    assert tg.sent == []  # silently ignored
