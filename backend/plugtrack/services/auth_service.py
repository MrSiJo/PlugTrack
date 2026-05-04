"""Auth service — single-user bootstrap and credential verification.

`bootstrap_user` is one-shot: it refuses if any `user` row already
exists, and uses an INSERT inside a single transaction so two concurrent
calls cannot both succeed (the second hits the unique constraint or
sees the row created by the first).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from ..security.crypto import hash_password, verify_password


MIN_PASSWORD_LENGTH = 12


class SetupAlreadyComplete(RuntimeError):
    """Raised by bootstrap_user when a user already exists."""


class WeakPasswordError(ValueError):
    """Raised when the supplied password is too short."""


async def _user_exists(session: AsyncSession) -> bool:
    result = await session.execute(select(func.count()).select_from(User))
    return (result.scalar_one() or 0) > 0


async def bootstrap_user(
    session: AsyncSession, username: str, password: str
) -> User:
    """Create the single application user. Race-safe.

    Raises SetupAlreadyComplete if any user already exists. Raises
    WeakPasswordError if the password is shorter than MIN_PASSWORD_LENGTH.
    """
    if not username or not username.strip():
        raise ValueError("username is required")
    if password is None or len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )

    if await _user_exists(session):
        raise SetupAlreadyComplete("a user already exists")

    user = User(
        username=username.strip(),
        password_hash=hash_password(password),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Lost the race with a concurrent bootstrap_user call.
        await session.rollback()
        raise SetupAlreadyComplete("a user already exists") from exc
    await session.commit()
    return user


async def find_user_by_username(
    session: AsyncSession, username: str
) -> Optional[User]:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def authenticate(
    session: AsyncSession, username: str, password: str
) -> Optional[User]:
    """Return the user if username+password match, else None."""
    if not username or not password:
        return None
    user = await find_user_by_username(session, username)
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
