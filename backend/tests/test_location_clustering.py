"""Tests for location clustering + haversine helpers."""

from __future__ import annotations

import pytest
from plugtrack.models import Location, User
from plugtrack.services.location_clustering import (
    find_or_create_location,
    haversine_m,
)


def test_haversine_zero_distance_for_same_point():
    assert haversine_m(50.0, 0.0, 50.0, 0.0) == pytest.approx(0.0, abs=0.01)


def test_haversine_one_degree_latitude_is_about_111km():
    # 1 deg latitude ≈ 111.32 km at equator and stays close near the poles
    # because we go meridionally.
    distance = haversine_m(0.0, 0.0, 1.0, 0.0)
    assert distance == pytest.approx(111_195.0, rel=0.01)


def test_haversine_symmetric():
    a = haversine_m(50.85, -0.13, 51.51, -0.12)
    b = haversine_m(51.51, -0.12, 50.85, -0.13)
    assert a == pytest.approx(b, rel=1e-9)


@pytest.mark.asyncio
async def test_creates_new_location_when_no_match(test_sessionmaker):
    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        loc, created = await find_or_create_location(
            session, user.id, lat=50.85, lng=-0.13, radius_m=100
        )
        await session.commit()

    assert created is True
    assert loc.id is not None
    # Unlabelled defaults from the spec.
    assert loc.name is None
    assert loc.is_home is False
    assert loc.is_free is False
    assert loc.default_cost_per_kwh_p is None
    assert loc.address is None


@pytest.mark.asyncio
async def test_returns_existing_location_within_radius(test_sessionmaker):
    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        existing = Location(
            user_id=user.id,
            centroid_lat=50.85,
            centroid_lng=-0.13,
            radius_m=100,
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        # 50 m roughly north (1 deg lat ≈ 111 km, so 50 m ≈ 0.00045 deg)
        loc, created = await find_or_create_location(
            session, user.id, lat=50.85 + 0.00045, lng=-0.13, radius_m=100
        )

    assert created is False
    assert loc.id == existing.id


@pytest.mark.asyncio
async def test_creates_new_location_just_outside_radius(test_sessionmaker):
    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        existing = Location(
            user_id=user.id,
            centroid_lat=50.85,
            centroid_lng=0.0,
            radius_m=100,
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        # ~150 m offset (≈ 0.00135 deg latitude) — just outside radius_m=100
        loc, created = await find_or_create_location(
            session,
            user.id,
            lat=50.85 + 0.00135,
            lng=0.0,
            radius_m=100,
        )
        await session.commit()

    assert created is True
    assert loc.id != existing.id


@pytest.mark.asyncio
async def test_boundary_at_radius_matches(test_sessionmaker):
    """Point exactly at radius_m matches; just past it does not."""
    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        existing = Location(
            user_id=user.id,
            centroid_lat=50.0,
            centroid_lng=0.0,
            radius_m=100,
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)

        # Compute a target lat exactly 100 m north.
        # 1 deg lat = 111195 m → 100 m = 100/111195 deg
        target_at_radius_lat = 50.0 + 100.0 / 111_195.0
        target_outside_lat = 50.0 + 110.0 / 111_195.0

        # Exactly at the radius — `<=` matches.
        _, created_at = await find_or_create_location(
            session, user.id, lat=target_at_radius_lat, lng=0.0, radius_m=100
        )
        assert created_at is False

        # Outside — must create new.
        _, created_outside = await find_or_create_location(
            session, user.id, lat=target_outside_lat, lng=0.0, radius_m=100
        )
        assert created_outside is True


@pytest.mark.asyncio
async def test_multi_user_isolation(test_sessionmaker):
    """User A's locations are not matched for user B's queries."""
    async with test_sessionmaker() as session:
        user_a = User(username="alice", password_hash="x")
        user_b = User(username="bob", password_hash="y")
        session.add_all([user_a, user_b])
        await session.commit()
        await session.refresh(user_a)
        await session.refresh(user_b)

        # User A creates a location.
        loc_a, created_a = await find_or_create_location(
            session, user_a.id, lat=50.0, lng=0.0, radius_m=100
        )
        await session.commit()
        assert created_a is True

        # User B at the SAME coords creates a brand-new location
        # (no cross-user matching).
        loc_b, created_b = await find_or_create_location(
            session, user_b.id, lat=50.0, lng=0.0, radius_m=100
        )
        await session.commit()
        assert created_b is True
        assert loc_b.id != loc_a.id
        assert loc_b.user_id == user_b.id
