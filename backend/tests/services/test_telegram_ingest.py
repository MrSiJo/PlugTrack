# backend/tests/services/test_telegram_ingest.py
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from plugtrack.services.screenshot_extraction import (
    Extraction,
    ExtractionResult,
    Usage,
    parse_extraction,
)
from plugtrack.services.telegram_ingest import (
    IngestContext,
    MergedSession,
    _summarise,
    handle_callback,
    handle_photo,
    handle_text,
)

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
        return ExtractionResult(
            extraction=parse_extraction(json.loads((FX / name).read_text())),
            usage=Usage(None, None, None),
        )

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


def _merged():
    return MergedSession(
        start_at=dt.datetime(2026, 6, 12, 14, 25, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 12, 14, 40, tzinfo=dt.timezone.utc),
        energy_kwh=9.78, cost_total_pence=851, cost_per_kwh_pence=87.0,
        soc_start=56, soc_end=70, location_name="Land's End", location_address="TR19 7AA",
        network="Osprey", peak_kw=40.0, confidence=0.95, source_kinds=["mycupra", "osprey"])


def test_summarise_shows_all_fields():
    text = _summarise([_merged()])
    for token in ("9.78", "8.51", "56", "70", "Osprey", "Land's End", "TR19 7AA", "0.95"):
        assert token in text


class FakeTgText:
    def __init__(self): self.sent = []
    async def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_handle_text_runs_health_for_command():
    tg = FakeTgText()
    called = {}
    async def health(from_id):
        called["id"] = from_id
        from plugtrack.services.telegram_health import HealthReport, Check
        return HealthReport(checks=[Check("Telegram", True, "ok")], all_ok=True, usage_this_month=None)
    ctx = IngestContext(telegram=tg, sessionmaker=None, extractor=None,
                        resolve_target=lambda: (1, 1), allowed_user_ids={111}, health_check=health)
    await handle_text(ctx, from_id=111, chat_id=9, text="/test")
    assert called["id"] == 111 and tg.sent and "Telegram" in tg.sent[-1]


@pytest.mark.asyncio
async def test_handle_text_disallowed_ignored():
    tg = FakeTgText()
    ctx = IngestContext(telegram=tg, sessionmaker=None, extractor=None,
                        resolve_target=lambda: (1, 1), allowed_user_ids={111})
    await handle_text(ctx, from_id=999, chat_id=9, text="/test")
    assert tg.sent == []
