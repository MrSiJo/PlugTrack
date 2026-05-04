"""Settings routes.

GET  /api/settings — auth required. Returns all rows from the `setting`
   table keyed by `key`. Secret values are redacted to "***" — and we
   determine "is this a secret?" by looking up the catalogue, NOT the DB
   row. This is defence-in-depth: even if a row's `is_secret` column was
   silently flipped to false, the catalogue still wins.

PUT  /api/settings — auth + CSRF. Body {key, value}. Validates the key
   exists in the catalogue (rejects unknown keys). Encrypts secret values
   via Fernet (`encrypt_secret`) before storing.

POST /api/settings/clear-pycupra-tokens — auth + CSRF. Wipes the local
   pycupra token cache directory. Used by Phase 5 but added here so all
   settings routes live together.
"""
import shutil
from pathlib import Path
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
    return {"key": row.key, "status": "updated"}


def _pycupra_dir() -> Path:
    """Resolve the pycupra token directory.

    In the deployed container the Dockerfile creates `/app/data/pycupra`.
    For dev we resolve `data/pycupra` relative to the repo root so the
    test suite can target a tmp_path-backed copy if needed.
    """
    repo_root = Path(__file__).resolve().parents[4]
    return repo_root / "data" / "pycupra"


@router.post("/clear-pycupra-tokens")
async def clear_pycupra_tokens(request: Request) -> dict[str, Any]:  # noqa: ARG001
    target = _pycupra_dir()
    if not target.exists():
        return {"cleared": False, "count": 0}

    count = 0
    for child in target.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                continue
        count += 1
    return {"cleared": count > 0, "count": count}
