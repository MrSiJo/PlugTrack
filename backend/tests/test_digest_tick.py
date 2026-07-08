"""Tests for run_digest_tick — send-once-per-period + downtime catch-up.

Fixed "now" choices:
- MONDAY_AFTER = 2026-06-22 09:00 Europe/London (a Monday, after default send_hour 8)
- WEDNESDAY    = 2026-06-24 09:00 Europe/London (mid-week, anchor already passed)
- MONDAY_BEFORE = 2026-06-22 07:30 Europe/London (Monday before send_hour — NOT yet due)
- FIRST_AFTER  = 2026-07-01 09:00 Europe/London (1st of month, after send_hour)
- SECOND       = 2026-07-02 09:00 Europe/London (2nd of month, anchor passed)
- FIRST_BEFORE = 2026-07-01 07:30 Europe/London (1st of month before send_hour — not yet due)

ISO week:  2026-W26  (week containing Mon 2026-06-22)
Month:     2026-07   (July 2026)
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from plugtrack.models import Setting, User
from sqlalchemy import select

LONDON = ZoneInfo("Europe/London")

# ── Fixed instants (all tz-aware, Europe/London) ────────────────────────────
MONDAY_AFTER = dt.datetime(2026, 6, 22, 9, 0, tzinfo=LONDON)  # Mon, hour>=8
MONDAY_BEFORE = dt.datetime(2026, 6, 22, 7, 30, tzinfo=LONDON)  # Mon, hour<8
WEDNESDAY = dt.datetime(2026, 6, 24, 9, 0, tzinfo=LONDON)  # Wed, anchor passed
FIRST_AFTER = dt.datetime(2026, 7, 1, 9, 0, tzinfo=LONDON)  # 1st, hour>=8
FIRST_BEFORE = dt.datetime(2026, 7, 1, 7, 30, tzinfo=LONDON)  # 1st, hour<8
SECOND = dt.datetime(2026, 7, 2, 9, 0, tzinfo=LONDON)  # 2nd, anchor passed

WEEK_MARKER = "2026-W26"
MONTH_MARKER = "2026-07"

# ISO week for SECOND (2026-07-02 is Thursday of W27)
WEEK_MARKER_W27 = "2026-W27"
# Month for SECOND
MONTH_MARKER_JUL = "2026-07"

# Bot creds
FAKE_TOKEN = "faketoken123"
FAKE_CHAT_ID = 99999


# ── Fake Telegram client ─────────────────────────────────────────────────────


class FakeTelegramClient:
    """Records calls to send_message without hitting the network."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def send_message(
        self, *, chat_id: int, text: str, reply_markup: dict | None = None
    ) -> int | None:
        self.calls.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return 1  # fake message_id

    async def aclose(self) -> None:
        self.closed = True


class FailingTelegramClient:
    """Always raises on send_message — simulates a Telegram network error."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_message(
        self, *, chat_id: int, text: str, reply_markup: dict | None = None
    ) -> int | None:
        self.calls.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        raise RuntimeError("Telegram network error (simulated)")


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _seed_user(sm) -> int:
    async with sm() as s:
        user = User(username="alice", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user.id


async def _upsert_setting(sm, key: str, value: str | None) -> None:
    async with sm() as s:
        row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        if row is None:
            s.add(
                Setting(
                    key=key,
                    value=value,
                    value_type="string",
                    group_name="telegram",
                    label=key,
                    description="",
                    default_value=None,
                )
            )
        else:
            row.value = value
        await s.commit()


async def _get_marker(sm, key: str) -> str | None:
    async with sm() as s:
        row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        return row.value if row else None


async def _seed_bot_settings(sm, *, weekly=True, monthly=True, send_hour=8):
    """Seed just enough settings for the bot channel to be deemed available."""
    settings = {
        "telegram_bot_enabled": "true",
        "telegram_bot_token": FAKE_TOKEN,  # plain text — no encryption in tests
        "telegram_allowed_user_ids": str(FAKE_CHAT_ID),
        "digest_weekly_enabled": "true" if weekly else "false",
        "digest_monthly_enabled": "true" if monthly else "false",
        "digest_send_hour": str(send_hour),
    }
    for k, v in settings.items():
        await _upsert_setting(sm, k, v)


# ── Import the function under test ───────────────────────────────────────────

from plugtrack.main import run_digest_tick  # noqa: E402 (module imported after helpers)

# ─────────────────────────────────────────────────────────────────────────────
# Weekly tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_sends_on_monday_at_send_hour(test_sessionmaker):
    """Monday at/after send_hour, enabled, no marker → sends; marker set to ISO week."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False)

    fake = FakeTelegramClient()
    digest_text = "Weekly recap"

    async def _fake_weekly(session, *, user_id, now):
        return digest_text

    async def _fake_monthly(session, *, user_id, now):
        return None

    await run_digest_tick(
        now=MONDAY_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    # One send, correct chat_id + text, NO reply_markup
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["chat_id"] == FAKE_CHAT_ID
    assert call["text"] == digest_text
    assert call["reply_markup"] is None

    # Marker must be updated to the current ISO week
    marker = await _get_marker(test_sessionmaker, "digest_last_weekly_sent")
    assert marker == WEEK_MARKER


@pytest.mark.asyncio
async def test_weekly_dedupe_same_week(test_sessionmaker):
    """Second tick in same ISO week → no resend."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False)
    await _upsert_setting(test_sessionmaker, "digest_last_weekly_sent", WEEK_MARKER)

    fake = FakeTelegramClient()

    await run_digest_tick(
        now=MONDAY_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
    )

    assert len(fake.calls) == 0


@pytest.mark.asyncio
async def test_weekly_catchup_on_wednesday(test_sessionmaker):
    """Server was down until Wednesday — anchor passed, marker not set → sends."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False)

    fake = FakeTelegramClient()
    digest_text = "Wednesday catch-up"

    async def _fake_weekly(session, *, user_id, now):
        return digest_text

    async def _fake_monthly(session, *, user_id, now):
        return None

    await run_digest_tick(
        now=WEDNESDAY,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 1
    assert fake.calls[0]["text"] == digest_text
    marker = await _get_marker(test_sessionmaker, "digest_last_weekly_sent")
    assert marker == WEEK_MARKER


@pytest.mark.asyncio
async def test_weekly_empty_period_no_send_but_marker_advances(test_sessionmaker):
    """Empty week (builder returns None) → no send BUT marker still advances."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False)

    fake = FakeTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return None  # empty period

    async def _fake_monthly(session, *, user_id, now):
        return None

    await run_digest_tick(
        now=MONDAY_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    # No message sent
    assert len(fake.calls) == 0

    # But marker advanced so it won't retry next hour
    marker = await _get_marker(test_sessionmaker, "digest_last_weekly_sent")
    assert marker == WEEK_MARKER


@pytest.mark.asyncio
async def test_weekly_not_sent_before_send_hour(test_sessionmaker):
    """Monday but before send_hour → no send."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False, send_hour=8)

    fake = FakeTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return "should not be called"

    async def _fake_monthly(session, *, user_id, now):
        return None

    await run_digest_tick(
        now=MONDAY_BEFORE,  # 07:30, before send_hour 8
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 0
    marker = await _get_marker(test_sessionmaker, "digest_last_weekly_sent")
    assert marker is None


@pytest.mark.asyncio
async def test_bot_disabled_no_send(test_sessionmaker):
    """telegram_bot_enabled=false → no send."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=True)
    await _upsert_setting(test_sessionmaker, "telegram_bot_enabled", "false")

    fake = FakeTelegramClient()

    await run_digest_tick(
        now=MONDAY_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
    )

    assert len(fake.calls) == 0


@pytest.mark.asyncio
async def test_both_toggles_off_no_send(test_sessionmaker):
    """Both weekly and monthly disabled → no send."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=False, monthly=False)

    fake = FakeTelegramClient()

    await run_digest_tick(
        now=WEDNESDAY,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
    )

    assert len(fake.calls) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Monthly tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_sends_on_first_at_send_hour(test_sessionmaker):
    """1st of month at/after send_hour, enabled, no marker → sends; marker set."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=False, monthly=True)

    fake = FakeTelegramClient()
    digest_text = "Monthly recap"

    async def _fake_weekly(session, *, user_id, now):
        return None

    async def _fake_monthly(session, *, user_id, now):
        return digest_text

    await run_digest_tick(
        now=FIRST_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["chat_id"] == FAKE_CHAT_ID
    assert call["text"] == digest_text
    assert call["reply_markup"] is None

    marker = await _get_marker(test_sessionmaker, "digest_last_monthly_sent")
    assert marker == MONTH_MARKER


@pytest.mark.asyncio
async def test_monthly_dedupe_same_month(test_sessionmaker):
    """Second tick same calendar month → no resend."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=False, monthly=True)
    await _upsert_setting(test_sessionmaker, "digest_last_monthly_sent", MONTH_MARKER)

    fake = FakeTelegramClient()

    await run_digest_tick(
        now=SECOND,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
    )

    assert len(fake.calls) == 0


@pytest.mark.asyncio
async def test_monthly_catchup_on_second(test_sessionmaker):
    """Server down until the 2nd — catch-up still sends."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=False, monthly=True)

    fake = FakeTelegramClient()
    digest_text = "July recap (late)"

    async def _fake_weekly(session, *, user_id, now):
        return None

    async def _fake_monthly(session, *, user_id, now):
        return digest_text

    await run_digest_tick(
        now=SECOND,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 1
    assert fake.calls[0]["text"] == digest_text
    marker = await _get_marker(test_sessionmaker, "digest_last_monthly_sent")
    assert marker == MONTH_MARKER


@pytest.mark.asyncio
async def test_monthly_empty_period_no_send_but_marker_advances(test_sessionmaker):
    """Empty month → no send BUT marker still advances."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=False, monthly=True)

    fake = FakeTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return None

    async def _fake_monthly(session, *, user_id, now):
        return None  # empty month

    await run_digest_tick(
        now=FIRST_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 0
    marker = await _get_marker(test_sessionmaker, "digest_last_monthly_sent")
    assert marker == MONTH_MARKER


@pytest.mark.asyncio
async def test_monthly_not_sent_before_send_hour(test_sessionmaker):
    """1st of month but before send_hour → not yet due."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=False, monthly=True, send_hour=8)

    fake = FakeTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return None

    async def _fake_monthly(session, *, user_id, now):
        return "should not be called"

    await run_digest_tick(
        now=FIRST_BEFORE,  # 07:30, before send_hour 8
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 0
    marker = await _get_marker(test_sessionmaker, "digest_last_monthly_sent")
    assert marker is None


@pytest.mark.asyncio
async def test_both_weekly_and_monthly_fire_together(test_sessionmaker):
    """When both are due at the same tick, both send."""
    await _seed_user(test_sessionmaker)
    # WEDNESDAY is in W26 and it's past the 1st of July (SECOND is July 2nd)
    # Use SECOND (2026-07-02) which is both past Monday of W27 and past 1st of July
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=True)

    fake = FakeTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return "weekly text"

    async def _fake_monthly(session, *, user_id, now):
        return "monthly text"

    # 2026-07-02 is Wednesday of W27; also past 1st of July
    await run_digest_tick(
        now=SECOND,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    texts = [c["text"] for c in fake.calls]
    assert "weekly text" in texts
    assert "monthly text" in texts
    assert len(fake.calls) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Hardening tests (Tests 3–5): send-failure retry + period independence
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_failure_no_marker_written(test_sessionmaker):
    """Test 3: send_message raises → marker NOT written → will retry next tick.

    Delivery semantics: send failure → marker NOT advanced → at-least-once
    retry. A duplicate is possible if Telegram errors then recovers, but that
    is acceptable for a low-frequency digest.
    """
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False)

    failing = FailingTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return "weekly content"  # non-empty → send will be attempted

    async def _fake_monthly(session, *, user_id, now):
        return None

    # Must NOT raise (exception swallowed by per-period try/except)
    await run_digest_tick(
        now=MONDAY_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: failing,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    # Send was attempted
    assert len(failing.calls) == 1

    # But marker must NOT have been committed → retry on next tick
    marker = await _get_marker(test_sessionmaker, "digest_last_weekly_sent")
    assert marker is None


@pytest.mark.asyncio
async def test_monthly_failure_does_not_prevent_weekly_marker(test_sessionmaker):
    """Test 4: weekly succeeds + monthly fails → weekly marker IS written, monthly is NOT.

    Independence test: the two periods must not contaminate each other.
    A monthly send failure must not roll back or skip the already-committed
    weekly marker.
    """
    await _seed_user(test_sessionmaker)
    # Both periods enabled; SECOND (2026-07-02) has both anchors passed.
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=True)

    class _MixedClient:
        """Succeeds on first call (weekly), raises on second (monthly)."""

        def __init__(self):
            self.calls: list[dict[str, Any]] = []

        async def send_message(self, *, chat_id: int, text: str, reply_markup: dict | None = None):
            self.calls.append({"chat_id": chat_id, "text": text})
            if len(self.calls) == 1:
                return 1  # weekly succeeds
            raise RuntimeError("Monthly Telegram send failed (simulated)")

    mixed = _MixedClient()

    async def _fake_weekly(session, *, user_id, now):
        return "weekly text"

    async def _fake_monthly(session, *, user_id, now):
        return "monthly text"

    # Must NOT raise (both exceptions swallowed)
    await run_digest_tick(
        now=SECOND,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: mixed,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    # Weekly message was sent
    assert any(c["text"] == "weekly text" for c in mixed.calls)

    # Weekly marker IS committed (weekly succeeded before monthly even ran)
    weekly_marker = await _get_marker(test_sessionmaker, "digest_last_weekly_sent")
    assert weekly_marker == WEEK_MARKER_W27

    # Monthly marker is NOT committed (send failed)
    monthly_marker = await _get_marker(test_sessionmaker, "digest_last_monthly_sent")
    assert monthly_marker is None


@pytest.mark.asyncio
async def test_both_succeed_markers_set_to_correct_values(test_sessionmaker):
    """Test 5: both weekly+monthly fire and succeed → BOTH markers set to correct period values.

    Verifies the exact ISO-week and YYYY-MM strings, not just that 2 sends happened.
    SECOND = 2026-07-02 (Thursday of W27, month=2026-07).
    """
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=True)

    fake = FakeTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return "weekly text"

    async def _fake_monthly(session, *, user_id, now):
        return "monthly text"

    await run_digest_tick(
        now=SECOND,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 2

    # SECOND is 2026-07-02 → ISO week W27, month 2026-07
    weekly_marker = await _get_marker(test_sessionmaker, "digest_last_weekly_sent")
    assert weekly_marker == WEEK_MARKER_W27  # "2026-W27"

    monthly_marker = await _get_marker(test_sessionmaker, "digest_last_monthly_sent")
    assert monthly_marker == MONTH_MARKER_JUL  # "2026-07"


# ─────────────────────────────────────────────────────────────────────────────
# PLUG-M4 — client lifecycle: lazy construction + aclose after every tick
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_is_closed_after_a_send(test_sessionmaker):
    """The Telegram client's aclose() runs after a tick that sent a digest."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False)

    fake = FakeTelegramClient()

    async def _fake_weekly(session, *, user_id, now):
        return "weekly text"

    async def _fake_monthly(session, *, user_id, now):
        return None

    await run_digest_tick(
        now=MONDAY_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=lambda token: fake,
        _weekly_builder=_fake_weekly,
        _monthly_builder=_fake_monthly,
    )

    assert len(fake.calls) == 1
    assert fake.closed is True


@pytest.mark.asyncio
async def test_client_not_constructed_when_nothing_due(test_sessionmaker):
    """A tick with no digest due must not construct (or leak) a client."""
    await _seed_user(test_sessionmaker)
    await _seed_bot_settings(test_sessionmaker, weekly=True, monthly=False)
    # Weekly already sent for this ISO week → nothing due.
    await _upsert_setting(test_sessionmaker, "digest_last_weekly_sent", WEEK_MARKER)

    constructed = []

    def factory(token):
        constructed.append(token)
        return FakeTelegramClient()

    await run_digest_tick(
        now=MONDAY_AFTER,
        sessionmaker=test_sessionmaker,
        client_factory=factory,
    )

    assert constructed == []
