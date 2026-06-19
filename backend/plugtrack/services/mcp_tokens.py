"""Per-user MCP bearer token service.

Tokens are hashed at rest using sha256(app_secret + plaintext). The plaintext
is returned once from ``mint`` and never stored. Tokens are scoped
("read" | "readwrite") and revocable by the owning user only.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..bootstrap import get_settings
from ..models.mcp_token import MCPToken


def generate_token() -> str:
    """Return a URL-safe random token (43 chars from 32 bytes)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Return sha256(app_secret + token) as a lowercase hex digest."""
    app_secret = get_settings().app_secret_key
    return hashlib.sha256((app_secret + token).encode()).hexdigest()


async def mint(
    session: AsyncSession,
    user_id: int,
    name: str,
    scope: str,
) -> tuple[MCPToken, str]:
    """Create and persist a new MCPToken row.

    Returns ``(row, plaintext_token)``.  The plaintext is the caller's one
    chance to see it; only the hash is stored.
    """
    plaintext = generate_token()
    token_hash = hash_token(plaintext)

    row = MCPToken(
        user_id=user_id,
        name=name,
        token_hash=token_hash,
        scope=scope,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row, plaintext


async def verify(session: AsyncSession, token: str) -> Optional[MCPToken]:
    """Look up a token by hash; update ``last_used_at`` on a hit.

    Returns the ``MCPToken`` row on success, or ``None`` if the token is
    unknown or has been revoked.
    """
    token_hash = hash_token(token)
    result = await session.execute(
        select(MCPToken).where(MCPToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None

    row.last_used_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return row


async def list_for_user(session: AsyncSession, user_id: int) -> list[MCPToken]:
    """Return all tokens belonging to ``user_id``, newest first."""
    result = await session.execute(
        select(MCPToken)
        .where(MCPToken.user_id == user_id)
        .order_by(MCPToken.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke(session: AsyncSession, user_id: int, token_id: int) -> bool:
    """Delete the token only if it belongs to ``user_id``.

    Returns ``True`` on success, ``False`` if the token doesn't exist or
    belongs to a different user.
    """
    result = await session.execute(
        select(MCPToken).where(
            MCPToken.id == token_id,
            MCPToken.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False

    await session.delete(row)
    await session.commit()
    return True
