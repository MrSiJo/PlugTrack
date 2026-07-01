"""Unit tests for the per-username login throttle."""
from __future__ import annotations

from plugtrack.api.login_throttle import LoginThrottle


class _Clock:
    """Manually-advanced monotonic clock for deterministic tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _throttle(clock: _Clock, **kw) -> LoginThrottle:
    kw.setdefault("max_failures", 3)
    kw.setdefault("lockout_seconds", 60)
    kw.setdefault("window_seconds", 60)
    return LoginThrottle(time_func=clock, **kw)


def test_not_locked_before_threshold():
    clock = _Clock()
    t = _throttle(clock)
    t.record_failure("admin")
    t.record_failure("admin")
    assert t.seconds_until_unlocked("admin") == 0


def test_locks_at_threshold_and_reports_remaining():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        t.record_failure("admin")
    assert t.seconds_until_unlocked("admin") == 60


def test_lock_expires_after_cooldown():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        t.record_failure("admin")
    clock.advance(61)
    assert t.seconds_until_unlocked("admin") == 0
    # And a fresh failure starts a new count rather than re-locking instantly.
    t.record_failure("admin")
    assert t.seconds_until_unlocked("admin") == 0


def test_successful_login_resets_counter():
    clock = _Clock()
    t = _throttle(clock)
    t.record_failure("admin")
    t.record_failure("admin")
    t.reset("admin")
    t.record_failure("admin")
    assert t.seconds_until_unlocked("admin") == 0


def test_old_failures_fall_out_of_window():
    clock = _Clock()
    t = _throttle(clock)
    t.record_failure("admin")
    t.record_failure("admin")
    clock.advance(61)  # both earlier failures now older than the 60s window
    t.record_failure("admin")
    assert t.seconds_until_unlocked("admin") == 0


def test_key_is_case_insensitive_and_trimmed():
    clock = _Clock()
    t = _throttle(clock)
    t.record_failure(" Admin ")
    t.record_failure("admin")
    t.record_failure("ADMIN")
    assert t.seconds_until_unlocked("admin") == 60


def test_lock_does_not_extend_on_further_attempts():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        t.record_failure("admin")
    assert t.seconds_until_unlocked("admin") == 60
    clock.advance(30)
    t.record_failure("admin")  # attempt while already locked
    assert t.seconds_until_unlocked("admin") == 30  # unchanged expiry, not reset


def test_usernames_are_tracked_independently():
    clock = _Clock()
    t = _throttle(clock)
    for _ in range(3):
        t.record_failure("admin")
    t.record_failure("someone-else")
    assert t.seconds_until_unlocked("admin") == 60
    assert t.seconds_until_unlocked("someone-else") == 0
