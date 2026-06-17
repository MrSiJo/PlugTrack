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


def test_summarise_uses_projected_cost():
    from plugtrack.services.screenshot_correlation import MergedSession
    from plugtrack.services.telegram_ingest import _summarise
    m = MergedSession(
        start_at=dt.datetime(2026, 6, 15, 19, 27, tzinfo=dt.timezone.utc), end_at=None,
        energy_kwh=10.74, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name="Home", location_address=None,
        network=None, peak_kw=2.0, confidence=0.91, source_kinds=["mycupra", "granny"])
    text = _summarise([m], projected=[
        {"kwh_added": 10.74, "cost_pence": 207, "cost_basis": "home_rate"}])
    assert "£2.07" in text and "home_rate" in text and "10.74" in text


@pytest.mark.asyncio
async def test_card_shows_projected_home_cost(test_sessionmaker, seeded_user_car):
    from plugtrack.services.screenshot_extraction import Usage
    from plugtrack.services.telegram_ingest import _stage_and_card
    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker)
    # granny (untimed) already staged; the MyCupra (timed) shot now arrives
    await _stage_row(test_sessionmaker, user_id, "g", _ex(source="granny", energy_kwh=10.74))
    tg = FakeTg()
    ctx = _ctx(tg, test_sessionmaker, user_id, car_id)
    mycupra = _ex(source="mycupra", soc_start=67, soc_end=80,
                  start_at="2026-06-15T19:27:00", end_at="2026-06-16T06:59:00",
                  location_name="Home")
    await _stage_and_card(ctx, user_id=user_id, chat_id=9, extraction=mycupra,
                          usage=Usage(1, 1, 0), telegram_file_id="m", message_id=1, sha="m")
    card = tg.sent[-1]
    assert "10.74 kWh" in card
    assert "£2.07" in card and "home_rate" in card


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
