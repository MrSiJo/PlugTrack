"""Tests for the User model."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_user_can_be_inserted(test_sessionmaker):
    from plugtrack.models import User

    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="not-a-real-hash")
        session.add(user)
        await session.commit()
        await session.refresh(user)

    assert user.id == 1
    assert user.username == "alice"
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_user_username_is_unique(test_sessionmaker):
    from plugtrack.models import User
    from sqlalchemy.exc import IntegrityError

    async with test_sessionmaker() as session:
        session.add(User(username="alice", password_hash="a"))
        session.add(User(username="alice", password_hash="b"))
        with pytest.raises(IntegrityError):
            await session.commit()
