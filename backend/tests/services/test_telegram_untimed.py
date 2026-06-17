"""Ingest behaviour for untimed readings under the one-charge-per-Save model."""
import datetime as dt

import pytest
from sqlalchemy import select

from plugtrack.models import ScreenshotImport
from plugtrack.services.screenshot_extraction import Extraction
from plugtrack.services.telegram_ingest import IngestContext, handle_callback


def _ex(**kw):
    base = dict(
        source="x", has_cost=False, energy_kwh=None, cost_total_pence=None,
        cost_per_kwh_pence=None, start_at=None, end_at=None, soc_start=None,
        soc_end=None, location_name=None, location_address=None, network=None,
        peak_kw=None, confidence=0.95,
    )
    base.update(kw)
    return Extraction(**base)


class FakeTg:
    def __init__(self):
        self.sent = []
        self.answered = []

    async def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append(text)

    async def answer_callback(self, callback_id, text=""):
        self.answered.append(text)


def _ctx(tg, sm, user_id, car_id):
    return IngestContext(
        telegram=tg, sessionmaker=sm, extractor=None,
        resolve_target=lambda: (user_id, car_id), allowed_user_ids={111},
        public_base_url="http://host:9279",
    )


async def _seed_home_rate(sm):
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults
    async with sm() as s:
        await seed_defaults(s)
        row = (await s.execute(select(Setting).where(
            Setting.key == "default_home_rate_p_per_kwh"))).scalar_one()
        row.value = "19.26"
        await s.commit()


async def _stage_row(sm, user_id, sha, ex):
    async with sm() as s:
        s.add(ScreenshotImport(user_id=user_id, image_sha256=sha, source=ex.source,
                               extracted=ex.__dict__, status="staged"))
        await s.commit()


@pytest.mark.asyncio
async def test_save_merges_mycupra_and_untimed_granny(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    await _stage_row(test_sessionmaker, user_id, "a", _ex(
        source="mycupra", soc_start=67, soc_end=80,
        start_at="2026-06-15T19:27:00", end_at="2026-06-16T06:59:00"))
    await _stage_row(test_sessionmaker, user_id, "b", _ex(source="granny", energy_kwh=9.3))
    tg = FakeTg()
    await handle_callback(_ctx(tg, test_sessionmaker, user_id, car_id),
                          from_id=111, callback_id="cb", data="save", chat_id=9)
    reply = tg.sent[-1]
    assert "Saved 1 session" in reply and "£" in reply
    assert "undated" not in reply.lower()
    async with test_sessionmaker() as s:
        rows = (await s.execute(select(ScreenshotImport))).scalars().all()
        assert all(r.status == "committed" for r in rows)


@pytest.mark.asyncio
async def test_save_keeps_undated_granny_only_staged(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    await _stage_row(test_sessionmaker, user_id, "g", _ex(source="granny", energy_kwh=9.3))
    tg = FakeTg()
    await handle_callback(_ctx(tg, test_sessionmaker, user_id, car_id),
                          from_id=111, callback_id="cb", data="save", chat_id=9)
    reply = tg.sent[-1]
    assert "Saved 0 session" in reply
    assert "undated" in reply.lower()
    async with test_sessionmaker() as s:
        row = (await s.execute(select(ScreenshotImport))).scalar_one()
        assert row.status == "staged"  # kept for its app-screenshot companion
