"""Auth routes — login (signs cookie) and logout (clears it)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...bootstrap import get_settings
from ...db import get_db
from ...services.auth_service import authenticate
from ..auth_middleware import SESSION_COOKIE_NAME, make_serializer
from ..rate_limit import limiter


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=512)


class LoginResponse(BaseModel):
    user_id: int
    username: str


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,  # noqa: ARG001 — required by slowapi
    response: Response,
    body: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> LoginResponse:
    settings = get_settings()
    user = await authenticate(session, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid credentials")

    serializer = make_serializer(settings.app_secret_key)
    token = serializer.dumps({"user_id": user.id})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_max_age_seconds,
        path="/",
    )
    return LoginResponse(user_id=user.id, username=user.username)


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"ok": True}
