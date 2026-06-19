"""MCP token management routes.

Allows authenticated users to mint, list, and revoke their own per-user
bearer tokens for the MCP HTTP server.

These routes are NORMAL auth-gated endpoints (session cookie, CSRF
required for mutating verbs) — they are NOT exempt from auth/CSRF.
They do NOT expose the token_hash or plaintext (except once at mint).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...services import mcp_tokens as token_service

router = APIRouter(prefix="/api/mcp/tokens", tags=["mcp-tokens"])

_VALID_SCOPES = frozenset({"read", "readwrite"})


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------


class TokenListItem(BaseModel):
    id: int
    name: str
    scope: str
    created_at: datetime
    last_used_at: Optional[datetime]


class TokenCreateRequest(BaseModel):
    name: str
    scope: str


class TokenCreateResponse(BaseModel):
    id: int
    name: str
    scope: str
    created_at: datetime
    token: str  # plaintext — shown ONCE; never stored


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[TokenListItem])
async def list_tokens(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[TokenListItem]:
    """List the caller's MCP tokens. Never returns the token or hash."""
    user_id = _user_id(request)
    rows = await token_service.list_for_user(session, user_id)
    return [
        TokenListItem(
            id=row.id,
            name=row.name,
            scope=row.scope,
            created_at=row.created_at,
            last_used_at=row.last_used_at,
        )
        for row in rows
    ]


@router.post("", response_model=TokenCreateResponse, status_code=201)
async def create_token(
    request: Request,
    body: TokenCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenCreateResponse:
    """Mint a new token. Returns the plaintext ONCE — store it now."""
    user_id = _user_id(request)

    if body.scope not in _VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"scope must be one of {sorted(_VALID_SCOPES)}",
        )

    row, plaintext = await token_service.mint(session, user_id, body.name, body.scope)
    return TokenCreateResponse(
        id=row.id,
        name=row.name,
        scope=row.scope,
        created_at=row.created_at,
        token=plaintext,
    )


@router.delete("/{token_id}", status_code=204)
async def revoke_token(
    token_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke a token the caller owns. 404 if not found or not owned."""
    user_id = _user_id(request)
    success = await token_service.revoke(session, user_id, token_id)
    if not success:
        raise HTTPException(status_code=404, detail="token not found")
    return Response(status_code=204)
