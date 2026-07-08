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
    from plugtrack.db import set_sqlite_pragmas
    from plugtrack.models import Base

    db_file = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(url, future=True)
    # Same per-connection PRAGMAs production applies (PLUG-L1). Note:
    # foreign_keys enforcement is NOT among them — see the comment in
    # plugtrack/db.py:set_sqlite_pragmas for why it is held back.
    set_sqlite_pragmas(engine.sync_engine)
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
    # nosec B113 — in-process ASGI transport, no network I/O to time out.
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:  # nosec B113
        yield c


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-for-tests-only-padding-padding")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    # cookie_secure now defaults to True (secure-by-default). The test client
    # talks plain HTTP to http://testserver, where httpx won't store/send
    # Secure cookies — so the primed CSRF cookie would never come back and
    # every CSRF-protected POST would 403. Pin the localhost-dev default here.
    monkeypatch.setenv("COOKIE_SECURE", "false")
    # Settings are lru_cached; clear so the env above is honoured per test
    # regardless of import/cache order.
    from plugtrack.bootstrap import get_settings

    get_settings.cache_clear()
    yield


@pytest_asyncio.fixture
async def seeded_user_car(test_sessionmaker):
    """Insert a User + Car and return ``(user_id, car_id)``."""
    from plugtrack.models import Car, User

    async with test_sessionmaker() as s:
        user = User(username="alice", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return user.id, car.id
