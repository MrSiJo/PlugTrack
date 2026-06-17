# backend/tests/services/test_telegram_health.py
import datetime as dt
import pytest

from plugtrack.services.telegram_health import (
    HealthReport, UsageSummary, build_health_report, format_health_text,
)
from plugtrack.services.telegram_ingest import BotConfig, ConfigProblem


class FakeTg:
    def __init__(self, me=None, fail=False):
        self._me, self._fail = me, fail
    async def get_me(self):
        if self._fail:
            raise RuntimeError("network")
        return self._me or {"username": "plugbot"}


async def _ok_validate(key, *, client=None):
    return True, "12 models"


def _cfg(car_id, user_id):
    return BotConfig(token="t", openai_key="k", model="gpt-5-mini",
                     allowed={111}, car_id=car_id, user_id=user_id)


@pytest.mark.asyncio
async def test_all_ok_report(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        config_or_problem=_cfg(car_id, user_id), telegram=FakeTg(),
        openai_validate=_ok_validate, sessionmaker=test_sessionmaker,
        is_running=True, requesting_user_id=111, now=now)
    assert isinstance(r, HealthReport) and r.all_ok
    names = {c.name for c in r.checks}
    assert {"Telegram", "OpenAI", "Default car", "Allowlist", "Bot running"} <= names


@pytest.mark.asyncio
async def test_telegram_failure_marks_not_ok(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        config_or_problem=_cfg(car_id, user_id), telegram=FakeTg(fail=True),
        openai_validate=_ok_validate, sessionmaker=test_sessionmaker,
        is_running=True, requesting_user_id=111, now=now)
    assert not r.all_ok
    tg = next(c for c in r.checks if c.name == "Telegram")
    assert not tg.ok


@pytest.mark.asyncio
async def test_problem_config_reports_reasons(test_sessionmaker):
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        config_or_problem=ConfigProblem(reasons=["telegram_default_car_id not set"]),
        telegram=FakeTg(), openai_validate=_ok_validate,
        sessionmaker=test_sessionmaker, is_running=False, now=now)
    assert not r.all_ok
    assert any("car" in c.detail.lower() for c in r.checks)
    assert "✗" in format_health_text(r)


@pytest.mark.asyncio
async def test_usage_summary_sums_month_with_cost(test_sessionmaker, seeded_user_car):
    from plugtrack.models import ScreenshotImport
    user_id, car_id = seeded_user_car
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    async with test_sessionmaker() as s:
        s.add(ScreenshotImport(user_id=user_id, image_sha256="a", extracted={},
              status="committed", input_tokens=2000, output_tokens=500,
              reasoning_tokens=0, created_at=dt.datetime(2026, 6, 5, tzinfo=dt.timezone.utc)))
        await s.commit()
    cfg = _cfg(car_id, user_id)
    cfg.input_price_p, cfg.output_price_p = 50.0, 100.0  # pence per 1k
    r = await build_health_report(
        config_or_problem=cfg, telegram=FakeTg(), openai_validate=_ok_validate,
        sessionmaker=test_sessionmaker, is_running=True, now=now)
    assert isinstance(r.usage_this_month, UsageSummary)
    assert r.usage_this_month.input_tokens == 2000
    # 2000/1000*50 + 500/1000*100 = 100 + 50 = 150 pence
    assert r.usage_this_month.cost_pence == 150
