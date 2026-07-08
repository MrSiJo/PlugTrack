"""Tests for the pydantic-settings env loader."""
from __future__ import annotations

import pytest


def test_settings_requires_app_secret_key(monkeypatch):
    """Settings must refuse to instantiate without APP_SECRET_KEY.

    `_env_file=None` disables the `.env` loader so the test passes even on a
    checkout with a populated root `.env` (PLUG-H2 — the suite must not be
    environment-dependent).
    """
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    from plugtrack.bootstrap import Settings

    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_settings_rejects_short_app_secret_key(monkeypatch):
    """APP_SECRET_KEY must be at least 32 characters."""
    monkeypatch.setenv("APP_SECRET_KEY", "too-short")
    from plugtrack.bootstrap import Settings

    with pytest.raises(ValueError, match="APP_SECRET_KEY"):
        Settings(_env_file=None)


def test_settings_rejects_placeholder_app_secret_key(monkeypatch):
    """APP_SECRET_KEY values that look like placeholders are rejected."""
    monkeypatch.setenv("APP_SECRET_KEY", "replace-with-output-of-bootstrap-script")
    from plugtrack.bootstrap import Settings

    with pytest.raises(ValueError, match="placeholder"):
        Settings(_env_file=None)


def test_settings_accepts_real_app_secret_key(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    from plugtrack.bootstrap import Settings

    settings = Settings(_env_file=None)
    assert settings.app_secret_key == "x" * 48
    assert settings.database_url.startswith("sqlite+aiosqlite:")
    assert settings.session_cookie_name == "plugtrack_session"
    assert settings.csrf_cookie_name == "plugtrack_csrf"
