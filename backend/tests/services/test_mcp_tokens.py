"""Tests for the MCPToken model and mcp_tokens service.

Verifies:
  1. mint() returns a plaintext token + a row whose token_hash != plaintext.
  2. verify(plaintext) returns the row; a wrong/old token → None.
  3. scope is persisted correctly.
  4. list_for_user() is user-scoped (user B sees none of user A's tokens).
  5. revoke() only deletes the caller's own token (other user's token_id → False/no-op).
  6. verify after revoke → None.
"""

from __future__ import annotations

import pytest
from plugtrack.models import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(sm, username: str) -> int:
    async with sm() as s:
        user = User(username=username, password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user.id


# ---------------------------------------------------------------------------
# 1. mint: returns plaintext + row with hashed token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_returns_plaintext_and_row(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint

    user_id = await _make_user(test_sessionmaker, "alice")

    async with test_sessionmaker() as session:
        row, plaintext = await mint(session, user_id, name="Claude Desktop", scope="read")

    assert plaintext, "plaintext token should be non-empty"
    assert row.id is not None, "row should have a PK after commit"
    assert row.token_hash != plaintext, "stored hash must differ from plaintext"
    assert len(row.token_hash) == 64, "sha256 hex digest is 64 chars"


# ---------------------------------------------------------------------------
# 2. verify: hit on correct token; None on wrong/old token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_correct_token_returns_row(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, verify

    user_id = await _make_user(test_sessionmaker, "bob")

    async with test_sessionmaker() as session:
        row, plaintext = await mint(session, user_id, name="Desktop", scope="readwrite")

    async with test_sessionmaker() as session:
        found = await verify(session, plaintext)

    assert found is not None, "verify should return the MCPToken row"
    assert found.id == row.id


@pytest.mark.asyncio
async def test_verify_wrong_token_returns_none(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, verify

    user_id = await _make_user(test_sessionmaker, "carol")

    async with test_sessionmaker() as session:
        await mint(session, user_id, name="Desktop", scope="read")

    async with test_sessionmaker() as session:
        result = await verify(session, "completely-wrong-token")

    assert result is None


@pytest.mark.asyncio
async def test_verify_updates_last_used_at(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, verify

    user_id = await _make_user(test_sessionmaker, "dave")

    async with test_sessionmaker() as session:
        row, plaintext = await mint(session, user_id, name="Desktop", scope="read")

    assert row.last_used_at is None, "last_used_at should be None initially"

    async with test_sessionmaker() as session:
        found = await verify(session, plaintext)

    assert found is not None
    assert found.last_used_at is not None, "verify should update last_used_at"


# ---------------------------------------------------------------------------
# 3. scope is persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scope_persisted_read(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, verify

    user_id = await _make_user(test_sessionmaker, "eve_r")

    async with test_sessionmaker() as session:
        row, plaintext = await mint(session, user_id, name="ReadOnly", scope="read")

    async with test_sessionmaker() as session:
        found = await verify(session, plaintext)

    assert found is not None
    assert found.scope == "read"


@pytest.mark.asyncio
async def test_scope_persisted_readwrite(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, verify

    user_id = await _make_user(test_sessionmaker, "eve_rw")

    async with test_sessionmaker() as session:
        row, plaintext = await mint(session, user_id, name="ReadWrite", scope="readwrite")

    async with test_sessionmaker() as session:
        found = await verify(session, plaintext)

    assert found is not None
    assert found.scope == "readwrite"


# ---------------------------------------------------------------------------
# 4. list_for_user is user-scoped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_for_user_is_user_scoped(test_sessionmaker):
    from plugtrack.services.mcp_tokens import list_for_user, mint

    user_a = await _make_user(test_sessionmaker, "frank")
    user_b = await _make_user(test_sessionmaker, "grace")

    async with test_sessionmaker() as session:
        await mint(session, user_a, name="A-token-1", scope="read")
        await mint(session, user_a, name="A-token-2", scope="readwrite")
        await mint(session, user_b, name="B-token-1", scope="read")

    async with test_sessionmaker() as session:
        tokens_a = await list_for_user(session, user_a)
        tokens_b = await list_for_user(session, user_b)

    assert len(tokens_a) == 2, "user A should see their 2 tokens"
    assert len(tokens_b) == 1, "user B should see their 1 token"
    # Cross-user: none of B's IDs appear in A's list and vice versa
    ids_a = {t.id for t in tokens_a}
    ids_b = {t.id for t in tokens_b}
    assert ids_a.isdisjoint(ids_b), "no overlap between the two users' token IDs"


# ---------------------------------------------------------------------------
# 5. revoke: user-scoped; returns False for another user's token_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_own_token_returns_true(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, revoke

    user_id = await _make_user(test_sessionmaker, "heidi")

    async with test_sessionmaker() as session:
        row, _ = await mint(session, user_id, name="Desktop", scope="read")
        token_id = row.id

    async with test_sessionmaker() as session:
        result = await revoke(session, user_id, token_id)

    assert result is True


@pytest.mark.asyncio
async def test_revoke_other_users_token_returns_false(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, revoke

    user_a = await _make_user(test_sessionmaker, "ivan")
    user_b = await _make_user(test_sessionmaker, "judy")

    async with test_sessionmaker() as session:
        row, _ = await mint(session, user_a, name="A-token", scope="read")
        a_token_id = row.id

    # user_b attempts to revoke user_a's token
    async with test_sessionmaker() as session:
        result = await revoke(session, user_b, a_token_id)

    assert result is False, "user B cannot revoke user A's token"


@pytest.mark.asyncio
async def test_revoke_nonexistent_token_returns_false(test_sessionmaker):
    from plugtrack.services.mcp_tokens import revoke

    user_id = await _make_user(test_sessionmaker, "karl")

    async with test_sessionmaker() as session:
        result = await revoke(session, user_id, 999999)

    assert result is False


# ---------------------------------------------------------------------------
# 6. verify after revoke → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_after_revoke_returns_none(test_sessionmaker):
    from plugtrack.services.mcp_tokens import mint, revoke, verify

    user_id = await _make_user(test_sessionmaker, "lena")

    async with test_sessionmaker() as session:
        row, plaintext = await mint(session, user_id, name="Desktop", scope="read")
        token_id = row.id

    async with test_sessionmaker() as session:
        revoked = await revoke(session, user_id, token_id)
    assert revoked is True

    async with test_sessionmaker() as session:
        result = await verify(session, plaintext)

    assert result is None, "verify after revoke should return None"
