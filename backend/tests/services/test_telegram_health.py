import datetime as dt

import pytest

from plugtrack.services.telegram_health import (
    Check,
    HealthReport,
    UsageSummary,
    build_health_report,
    format_health_text,
)
from plugtrack.services.telegram_ingest import BotConfig, ConfigProblem


class FakeTg:
    def __init__(self, me=None, fail=False):
        self._me, self._fail = me, fail
        self.closed = False

    async def get_me(self):
        if self._fail:
            raise RuntimeError("network")
        return self._me or {"username": "plugbot"}

    async def aclose(self):
        self.closed = True


def _factory(tg):
    return lambda token: tg


async def _ok_validate(key, *, client=None):
    return True, "12 models"


def _cfg(user_id, **kw):
    return BotConfig(
        token="t", openai_key="k", model="gpt-5-mini",
        allowed={111}, user_id=user_id, **kw,
    )


@pytest.mark.asyncio
async def test_all_ok_report(test_sessionmaker, seeded_user_car):
    user_id, _car_id = seeded_user_car
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        token="t", openai_key="k", model="gpt-5-mini",
        make_telegram_client=_factory(FakeTg()),
        openai_validate=_ok_validate, config_or_problem=_cfg(user_id),
        sessionmaker=test_sessionmaker, is_running=True,
        requesting_user_id=111, now=now,
    )
    assert isinstance(r, HealthReport) and r.all_ok
    names = {c.name for c in r.checks}
    assert {"Telegram", "OpenAI", "Allowlist", "Bot running"} <= names
    assert "Default car" not in names


@pytest.mark.asyncio
async def test_telegram_failure_marks_not_ok(test_sessionmaker, seeded_user_car):
    user_id, _car_id = seeded_user_car
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        token="t", openai_key="k", model="gpt-5-mini",
        make_telegram_client=_factory(FakeTg(fail=True)),
        openai_validate=_ok_validate, config_or_problem=_cfg(user_id),
        sessionmaker=test_sessionmaker, is_running=True,
        requesting_user_id=111, now=now,
    )
    assert not r.all_ok
    tg = next(c for c in r.checks if c.name == "Telegram")
    assert not tg.ok


@pytest.mark.asyncio
async def test_token_and_key_validated_when_config_incomplete(test_sessionmaker):
    """Regression: a missing allowlist must NOT hide a valid token/key.

    Before the fix the report said 'OpenAI key not configured' / 'bot not
    running' whenever the full config didn't assemble — useless during setup.
    """
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        token="t", openai_key="k", model="gpt-5-mini",
        make_telegram_client=_factory(FakeTg(me={"username": "plugbot"})),
        openai_validate=_ok_validate,
        config_or_problem=ConfigProblem(reasons=["no allowed Telegram user IDs"]),
        sessionmaker=test_sessionmaker, is_running=False, now=now,
    )
    tg = next(c for c in r.checks if c.name == "Telegram")
    oai = next(c for c in r.checks if c.name == "OpenAI")
    assert tg.ok and oai.ok  # validated independently of config completeness
    assert any(c.name == "Config" and "allowed" in c.detail for c in r.checks)
    assert any(c.name == "Bot running" and not c.ok for c in r.checks)


@pytest.mark.asyncio
async def test_missing_token_and_key_reported_without_duplicate_config(test_sessionmaker):
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        token=None, openai_key=None, model=None,
        make_telegram_client=_factory(FakeTg()),
        openai_validate=_ok_validate,
        config_or_problem=ConfigProblem(
            reasons=["telegram_bot_token not set", "openai_api_key not set",
                     "no allowed Telegram user IDs"]),
        sessionmaker=test_sessionmaker, is_running=False, now=now,
    )
    tg = next(c for c in r.checks if c.name == "Telegram")
    oai = next(c for c in r.checks if c.name == "OpenAI")
    assert not tg.ok and "not set" in tg.detail
    assert not oai.ok and "not set" in oai.detail
    # token/openai reasons are covered by their own checks, not duplicated:
    config_details = [c.detail for c in r.checks if c.name == "Config"]
    assert not any("token" in d or "openai_api_key" in d for d in config_details)
    assert any("allowed" in d for d in config_details)


@pytest.mark.asyncio
async def test_allowlist_configured_when_no_requesting_user(test_sessionmaker, seeded_user_car):
    """UI button passes requesting_user_id=None (a web login has no Telegram
    id) -> 'configured', not a bogus membership test against the app user id.
    """
    user_id, _car_id = seeded_user_car
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    r = await build_health_report(
        token="t", openai_key="k", model="m",
        make_telegram_client=_factory(FakeTg()),
        openai_validate=_ok_validate, config_or_problem=_cfg(user_id),
        sessionmaker=test_sessionmaker, is_running=True,
        requesting_user_id=None, now=now,
    )
    allow = next(c for c in r.checks if c.name == "Allowlist")
    assert allow.ok and "configured" in allow.detail


@pytest.mark.asyncio
async def test_usage_summary_sums_month_with_cost(test_sessionmaker, seeded_user_car):
    from plugtrack.models import ScreenshotImport
    user_id, _car_id = seeded_user_car
    now = dt.datetime(2026, 6, 17, tzinfo=dt.timezone.utc)
    async with test_sessionmaker() as s:
        s.add(ScreenshotImport(
            user_id=user_id, image_sha256="a", extracted={}, status="committed",
            input_tokens=2000, output_tokens=500, reasoning_tokens=0,
            created_at=dt.datetime(2026, 6, 5, tzinfo=dt.timezone.utc)))
        await s.commit()
    cfg = _cfg(user_id, input_price_p=50.0, output_price_p=100.0)
    r = await build_health_report(
        token="t", openai_key="k", model="m",
        make_telegram_client=_factory(FakeTg()),
        openai_validate=_ok_validate, config_or_problem=cfg,
        sessionmaker=test_sessionmaker, is_running=True, now=now,
    )
    assert isinstance(r.usage_this_month, UsageSummary)
    assert r.usage_this_month.input_tokens == 2000
    # 2000/1000*50 + 500/1000*100 = 150 pence
    assert r.usage_this_month.cost_pence == 150


def test_format_health_text_marks():
    r = HealthReport(
        checks=[Check("Telegram", False, "x")], all_ok=False, usage_this_month=None)
    assert "✗" in format_health_text(r)
