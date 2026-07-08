"""Setup route — one-shot single-user creation.

Refuses if any user already exists. Argon2id-hashes the password (via
auth_service.bootstrap_user). Rate-limited to 5/minute per remote IP
to slow brute-force scanning of an unset instance.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth_service import (
    SetupAlreadyComplete,
    WeakPasswordError,
    bootstrap_user,
)
from ..rate_limit import limiter

router = APIRouter(prefix="/api", tags=["setup"])


class SetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class SetupResponse(BaseModel):
    user_id: int
    username: str


class SetupStatusResponse(BaseModel):
    setup_needed: bool


@router.get("/setup", response_model=SetupStatusResponse)
async def setup_status(
    session: AsyncSession = Depends(get_db),
) -> SetupStatusResponse:
    """Return whether first-run setup is still required.

    Unauthenticated. Used by the SPA to decide between routing the user
    to /setup vs /login on first paint. Returns true iff the `user`
    table is empty.
    """
    result = await session.execute(select(func.count()).select_from(User))
    user_count = result.scalar_one() or 0
    return SetupStatusResponse(setup_needed=user_count == 0)


@router.post("/setup", response_model=SetupResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def setup(
    request: Request,  # noqa: ARG001 — required by slowapi
    response: Response,  # noqa: ARG001 — required by slowapi for header injection
    body: SetupRequest,
    session: AsyncSession = Depends(get_db),
) -> SetupResponse:
    try:
        user = await bootstrap_user(session, body.username, body.password)
    except SetupAlreadyComplete as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WeakPasswordError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SetupResponse(user_id=user.id, username=user.username)
