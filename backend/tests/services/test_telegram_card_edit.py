"""The confirm card is edited in place as more screenshots merge into a charge."""

import pytest
from plugtrack.models import Setting
from plugtrack.services.screenshot_extraction import Extraction, Usage
from plugtrack.services.telegram_ingest import IngestContext, _stage_and_card, handle_callback
from plugtrack.settings.seeds import seed_defaults
from sqlalchemy import select


def _ex(**kw):
    base = dict(
        source="x",
        has_cost=False,
        energy_kwh=None,
        cost_total_pence=None,
        cost_per_kwh_pence=None,
        start_at=None,
        end_at=None,
        soc_start=None,
        soc_end=None,
        location_name=None,
        location_address=None,
        network=None,
        peak_kw=None,
        confidence=0.95,
    )
    base.update(kw)
    return Extraction(**base)


_MYCUPRA = dict(
    source="mycupra",
    soc_start=67,
    soc_end=80,
    start_at="2026-06-15T19:27:00",
    end_at="2026-06-16T06:59:00",
    location_name="Home",
)
_GRANNY = dict(source="granny", energy_kwh=10.74)


class FakeTg:
    def __init__(self, edit_fails=False):
        self.sent, self.edits, self._n, self.edit_fails = [], [], 100, edit_fails

    async def send_message(self, *, chat_id, text, reply_markup=None):
        self.sent.append(text)
        self._n += 1
        return self._n

    async def edit_message_text(self, *, chat_id, message_id, text, reply_markup=None):
        if self.edit_fails:
            raise RuntimeError("too old")
        self.edits.append({"message_id": message_id, "text": text})

    async def answer_callback(self, callback_id, text=""):
        pass


def _ctx(tg, sm, user_id, car_id):
    return IngestContext(
        telegram=tg,
        sessionmaker=sm,
        extractor=None,
        resolve_target=lambda: (user_id, car_id),
        allowed_user_ids={111},
        public_base_url="http://host:9279",
    )


async def _home_rate(sm):
    async with sm() as s:
        await seed_defaults(s)
        row = (
            await s.execute(select(Setting).where(Setting.key == "default_home_rate_p_per_kwh"))
        ).scalar_one()
        row.value = "19.26"
        await s.commit()


async def _stage(ctx, ex, sha, user_id):
    await _stage_and_card(
        ctx,
        user_id=user_id,
        chat_id=9,
        extraction=ex,
        usage=Usage(1, 1, 0),
        telegram_file_id=sha,
        message_id=1,
        sha=sha,
    )


@pytest.mark.asyncio
async def test_second_screenshot_edits_card_in_place(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _home_rate(test_sessionmaker)
    tg = FakeTg()
    ctx = _ctx(tg, test_sessionmaker, user_id, car_id)
    await _stage(ctx, _ex(**_MYCUPRA), "m", user_id)
    assert len(tg.sent) == 1 and tg.edits == []
    await _stage(ctx, _ex(**_GRANNY), "g", user_id)
    assert len(tg.sent) == 1  # no second card sent
    assert len(tg.edits) == 1  # the card was edited instead
    assert "10.74" in tg.edits[-1]["text"]  # updated to the merged delivered energy


@pytest.mark.asyncio
async def test_save_clears_card_so_next_charge_is_fresh(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _home_rate(test_sessionmaker)
    tg = FakeTg()
    ctx = _ctx(tg, test_sessionmaker, user_id, car_id)
    await _stage(ctx, _ex(**_MYCUPRA), "m", user_id)
    assert 9 in ctx.card_ids
    await handle_callback(ctx, from_id=111, callback_id="cb", data="save", chat_id=9)
    assert 9 not in ctx.card_ids  # batch closed
    await _stage(
        ctx,
        _ex(
            **_MYCUPRA,
        ),
        "m2",
        user_id,
    )
    assert tg.edits == []  # didn't edit the saved card; sent a new one


@pytest.mark.asyncio
async def test_edit_failure_falls_back_to_new_card(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _home_rate(test_sessionmaker)
    tg = FakeTg(edit_fails=True)
    ctx = _ctx(tg, test_sessionmaker, user_id, car_id)
    await _stage(ctx, _ex(**_MYCUPRA), "m", user_id)
    await _stage(ctx, _ex(**_GRANNY), "g", user_id)
    assert len(tg.sent) == 2  # edit raised -> fell back to a fresh send
