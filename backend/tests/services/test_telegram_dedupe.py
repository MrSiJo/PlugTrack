import hashlib

import pytest
from sqlalchemy import select

from plugtrack.models import ScreenshotImport
from plugtrack.services.screenshot_extraction import Extraction, Usage
from plugtrack.services.telegram_ingest import IngestContext, _stage_and_card


def _ex(**kw):
    base = dict(
        source="mycupra", has_cost=False, energy_kwh=None, cost_total_pence=None,
        cost_per_kwh_pence=None, start_at="2026-06-15T19:27:00", end_at=None,
        soc_start=67, soc_end=80, location_name=None, location_address=None,
        network=None, peak_kw=2.0, confidence=0.95,
    )
    base.update(kw)
    return Extraction(**base)


class FakeTg:
    def __init__(self):
        self.sent = []

    async def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append({"text": text, "kb": reply_markup})


def _ctx(tg, sm, user_id, car_id):
    return IngestContext(
        telegram=tg, sessionmaker=sm, extractor=None,
        resolve_target=lambda: (user_id, car_id), allowed_user_ids={111},
        public_base_url="http://host:9279",
    )


async def _stage(ctx, sha, user_id):
    await _stage_and_card(
        ctx, user_id=user_id, chat_id=9, extraction=_ex(), usage=Usage(1, 1, 0),
        telegram_file_id="f", message_id=1, sha=sha,
    )


@pytest.mark.asyncio
async def test_discarded_is_restaged_reusing_row(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    tg = FakeTg()
    ctx = _ctx(tg, test_sessionmaker, user_id, car_id)
    sha = hashlib.sha256(b"img1").hexdigest()
    await _stage(ctx, sha, user_id)
    async with test_sessionmaker() as s:
        row = (await s.execute(select(ScreenshotImport))).scalar_one()
        row.status = "discarded"
        await s.commit()
    tg.sent.clear()
    await _stage(ctx, sha, user_id)  # re-send the discarded one
    assert tg.sent[-1]["kb"] is not None  # confirm card with Save/Discard
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
        assert len(rows) == 1 and rows[0].status == "staged"  # reused, not duplicated


@pytest.mark.asyncio
async def test_committed_warns_and_does_not_restage(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    tg = FakeTg()
    ctx = _ctx(tg, test_sessionmaker, user_id, car_id)
    sha = hashlib.sha256(b"img2").hexdigest()
    await _stage(ctx, sha, user_id)
    async with test_sessionmaker() as s:
        row = (await s.execute(select(ScreenshotImport))).scalar_one()
        row.status = "committed"
        row.created_session_id = 42
        await s.commit()
    tg.sent.clear()
    await _stage(ctx, sha, user_id)
    msg = tg.sent[-1]
    assert msg["kb"] is None  # warning, no Save/Discard buttons
    assert "saved" in msg["text"].lower() and "42" in msg["text"]
    async with test_sessionmaker() as s:
        row = (await s.execute(select(ScreenshotImport))).scalar_one()
        assert row.status == "committed"  # untouched


@pytest.mark.asyncio
async def test_staged_reshows_card_without_duplicate(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    tg = FakeTg()
    ctx = _ctx(tg, test_sessionmaker, user_id, car_id)
    sha = hashlib.sha256(b"img3").hexdigest()
    await _stage(ctx, sha, user_id)
    tg.sent.clear()
    await _stage(ctx, sha, user_id)  # same image, still staged
    assert tg.sent[-1]["kb"] is not None  # card re-shown
    assert "already staged" in tg.sent[-1]["text"].lower()
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
        assert len(rows) == 1  # no duplicate row
