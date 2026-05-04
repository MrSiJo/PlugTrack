"""Shared pytest fixtures for the PlugTrack backend test suite.

Tests must NEVER touch any real database. Each test gets its own SQLite
file inside pytest's tmp_path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-tests-only-padding-padding")

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest_asyncio.fixture
async def test_engine(tmp_path):
    from plugtrack.models import Base

    db_file = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_sessionmaker(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def app(test_engine, test_sessionmaker, monkeypatch):
    from plugtrack import db as db_module
    from plugtrack.main import create_app

    monkeypatch.setattr(db_module, "engine", test_engine, raising=False)
    monkeypatch.setattr(db_module, "SessionLocal", test_sessionmaker, raising=False)

    application = create_app()

    async def _override_get_db():
        async with test_sessionmaker() as session:
            yield session

    application.dependency_overrides[db_module.get_db] = _override_get_db

    try:
        from plugtrack.api.rate_limit import limiter
        limiter.reset()
    except Exception:
        pass

    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-for-tests-only-padding-padding")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    yield
