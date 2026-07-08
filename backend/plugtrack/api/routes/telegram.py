"""Telegram/OpenAI admin endpoints: health test + model listing.

Auth + CSRF protected (NOT added to EXEMPT_PATHS).
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...bootstrap import get_settings
from ...db import get_db
from ...models import Setting
from ...security.crypto import decrypt_secret
from ...services.openai_admin import OpenAIAuthError, list_vision_models

router = APIRouter(prefix="/api", tags=["telegram"])


def _user_id(request: Request) -> int:
    uid = getattr(request.state, "user_id", None)
    if uid is None:
        raise HTTPException(status_code=401, detail="auth required")
    return uid


@router.post("/telegram/test")
async def telegram_test(request: Request) -> dict:
    _user_id(request)
    mgr = getattr(request.app.state, "telegram_manager", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="bot manager not available")
    # A web caller has no Telegram identity — its PlugTrack user id is NOT a
    # Telegram user id, so we don't run an allowlist *membership* check here
    # (that would be a guaranteed false negative). The in-chat /test command
    # passes the real Telegram from_id for a true membership check.
    report = await mgr.health(requesting_user_id=None)
    return {
        "all_ok": report.all_ok,
        "checks": [asdict(c) for c in report.checks],
        "usage_this_month": asdict(report.usage_this_month) if report.usage_this_month else None,
    }


@router.get("/openai/models")
async def openai_models(request: Request, session: AsyncSession = Depends(get_db)) -> dict:
    _user_id(request)
    rows = {r.key: r.value for r in (await session.execute(select(Setting))).scalars().all()}
    enc = rows.get("openai_api_key")
    if not enc:
        raise HTTPException(status_code=400, detail="OpenAI API key not set")
    key = decrypt_secret(enc, get_settings().app_secret_key)
    try:
        models = await list_vision_models(key)
    except OpenAIAuthError:
        raise HTTPException(status_code=400, detail="OpenAI key invalid")
    return {
        "models": [{"id": m.id, "recommended": m.recommended} for m in models],
        "current": rows.get("openai_model"),
    }
