"""Settings routes.

GET  /api/settings — auth required. Returns all rows from the `setting`
   table keyed by `key`. Secret values are redacted to "***" — and we
   determine "is this a secret?" by looking up the catalogue, NOT the DB
   row. This is defence-in-depth: even if a row's `is_secret` column was
   silently flipped to false, the catalogue still wins.

PUT  /api/settings — auth + CSRF. Body {key, value}. Validates the key
   exists in the catalogue (rejects unknown keys). Encrypts secret values
   via Fernet (`encrypt_secret`) before storing.
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...bootstrap import get_settings as get_app_settings
from ...db import get_db
from ...models import Setting
from ...security.crypto import encrypt_secret
from ...settings.catalogue import CATALOGUE


router = APIRouter(prefix="/api/settings", tags=["settings"])


# Catalogue lookup keyed by `key` for O(1) access.
_CATALOGUE_BY_KEY = {entry.key: entry for entry in CATALOGUE}

# Settings whose change must reconcile the live Telegram bot manager.
_RECONCILE_KEYS = {
    "telegram_bot_enabled",
    "telegram_bot_token",
    "telegram_allowed_user_ids",
    "openai_api_key",
    "openai_model",
}


class SettingPayload(BaseModel):
    key: str
    value: Optional[Any]
    value_type: str
    group_name: str
    label: str
    description: Optional[str]
    is_secret: bool


class UpdateSettingRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: Optional[str] = None


def _is_secret_per_catalogue(key: str) -> bool:
    entry = _CATALOGUE_BY_KEY.get(key)
    return bool(entry and entry.is_secret)


@router.get("", response_model=dict[str, SettingPayload])
async def list_settings(
    session: AsyncSession = Depends(get_db),
) -> dict[str, SettingPayload]:
    result = await session.execute(select(Setting))
    rows = result.scalars().all()
    out: dict[str, SettingPayload] = {}
    for row in rows:
        # Defence-in-depth: read is_secret from the catalogue, not the row.
        secret = _is_secret_per_catalogue(row.key)
        value: Optional[Any] = "***" if (secret and row.value) else row.value
        out[row.key] = SettingPayload(
            key=row.key,
            value=value,
            value_type=row.value_type,
            group_name=row.group_name,
            label=row.label,
            description=row.description,
            is_secret=secret,
        )
    return out


@router.put("")
async def update_setting(
    body: UpdateSettingRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    entry = _CATALOGUE_BY_KEY.get(body.key)
    if entry is None:
        raise HTTPException(
            status_code=400, detail=f"unknown setting key: {body.key!r}"
        )

    result = await session.execute(select(Setting).where(Setting.key == body.key))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"setting {body.key!r} not seeded; run lifespan first",
        )

    new_value: Optional[str]
    if body.value is None or body.value == "":
        new_value = None
    elif entry.is_secret:
        app_secret = get_app_settings().app_secret_key
        new_value = encrypt_secret(body.value, app_secret)
    else:
        new_value = body.value

    row.value = new_value
    await session.commit()

    # When a Telegram/OpenAI key that affects the running bot changes,
    # reconcile the live TelegramBotManager so start/stop/restart happen
    # without a redeploy. PUT updates one key per call, so the changed-key
    # set is just {body.key}.
    if body.key in _RECONCILE_KEYS:
        mgr = getattr(request.app.state, "telegram_manager", None)
        if mgr is not None:
            await mgr.reconcile()

    return {"key": row.key, "status": "updated"}
