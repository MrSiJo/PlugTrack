"""Application configuration via pydantic-settings.

Reads environment variables (and `.env` if present) into a typed Settings
object. APP_SECRET_KEY is validated to be present, sufficiently long, and
not a placeholder — startup fails loudly if any of those checks fail.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_REPO_ROOT = Path(__file__).resolve().parents[2]
# In the dev tree this points at <repo>/data; in the container the
# Dockerfile creates /app/data and we override DATA_DIR=/app/data via env.
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_DEFAULT_DB_PATH = _DEFAULT_DATA_DIR / "plugtrack.db"
_DEFAULT_DB_URL = f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH.as_posix()}"

_PLACEHOLDER_FRAGMENTS = (
    "replace-with",
    "change-me",
    "your-secret",
    "placeholder",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_secret_key: str = Field(..., alias="APP_SECRET_KEY")
    database_url: str = Field(default=_DEFAULT_DB_URL, alias="DATABASE_URL")
    data_dir: str = Field(default=str(_DEFAULT_DATA_DIR), alias="DATA_DIR")

    session_cookie_name: str = Field(default="plugtrack_session")
    csrf_cookie_name: str = Field(default="plugtrack_csrf")
    # Secure-by-default: the Set-Cookie Secure flag is on unless explicitly
    # disabled via COOKIE_SECURE=false for plain-HTTP localhost dev.
    cookie_secure: bool = Field(default=True, alias="COOKIE_SECURE")
    session_max_age_seconds: int = Field(default=86400 * 7)

    @field_validator("app_secret_key")
    @classmethod
    def _validate_secret_key(cls, v: str) -> str:
        if not v or len(v) < 32:
            raise ValueError("APP_SECRET_KEY must be at least 32 characters")
        lowered = v.lower()
        for fragment in _PLACEHOLDER_FRAGMENTS:
            if fragment in lowered:
                raise ValueError(
                    f"APP_SECRET_KEY appears to be a placeholder ('{fragment}'); "
                    "generate a real value, e.g. "
                    "python -c \"import secrets; print(secrets.token_urlsafe(48))\" "
                    "(see the compose.yaml header)"
                )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
