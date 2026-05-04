"""Tests for `dashboard_service.dashboard_summary`.

Covers:
- Empty state (no cars / no sessions).
- Single car with multiple sessions: panels + totals + recent list.
- Multi-car: top-locations aggregation across cars.
- Orchestrator merge: live state overrides session-derived defaults.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from plugtrack.models import Car, ChargingSession, Location, User
from plugtrack.services.dashboard_service import dashboard_summary
from plugtrack.services.sync_orchestrator import CarSyncState, SyncOrchestrator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _make_user(sessionmaker, username: str = "alice") -> User:
    async with sessionmaker() as s:
        user = User(username=username, password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _make_car(
    sessionmaker, user_id: int, *, make: str = "Cupra", model: str = "Born", active: bool = True
) -> Car:
    async with sessionmaker() as s:
        car = Car(
            user_id=user_id,
            make=make,
            model=model,
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=active,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car


async def _make_location(
    sessionmaker,
    user_id: int,
    *,
    name: str | None = None,
    lat: float = 51.5,
    lng: float = -0.1,
    visit_count: int = 0,
) -> Location:
    async with sessionmaker() as s:
        loc = Location(
            user_id=user_id,
            name=name,
            centroid_lat=lat,
            centroid_lng=lng,
            visit_count=visit_count,
        )
        s.add(loc)
        await s.commit()
        await s.refresh(loc)
        return loc


async def _make_session(
    sessionmaker,
    *,
    user_id: int,
    car_id: int,
    when: date,
    kwh: float,
    cost_pence: int | None,
    location_id: int | None = None,
    end_soc: int = 80,
    odometer_km: float | None = None,
    source: str = "manual",
) -> ChargingSession:
    async with sessionmaker() as s:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            date=when,
            start_soc=20,
            end_soc=end_soc,
            kwh_added=kwh,
            charging_type="ac",
            charging_mode="manual",
            cost_pence=cost_pence,
            cost_basis="home_rate" if cost_pence else "unknown",
            tariff_p_per_kwh=7.5 if cost_pence else None,
            location_id=location_id,
            odometer_at_session_km=odometer_km,
            source=source,
            charge_end_at=datetime.combine(when, datetime.min.time()).replace(
                tzinfo=timezone.utc
            ),
        )
        s.add(cs)
        await s.commit()
        await s.refresh(cs)
        return cs


@pytest.mark.asyncio
async def test_dashboard_summary_empty(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    async with test_sessionmaker() as session:
        summary = await dashboard_summary(session, user.id)

    assert summary.cars == []
    assert summary.recent_sessions == []
    assert summary.top_locations == []
    totals = summary.lifetime_totals
    assert totals.kwh == 0.0
    assert totals.cost_pence == 0
    assert totals.distance_km == 0
    assert totals.sessions_count == 0


@pytest.mark.asyncio
async def test_dashboard_summary_single_car_three_sessions(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)

    today = date(2026, 5, 1)
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today - timedelta(days=2),
        kwh=10.0,
        cost_pence=150,
        odometer_km=10_000,
        end_soc=70,
    )
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today - timedelta(days=1),
        kwh=12.0,
        cost_pence=180,
        odometer_km=10_200,
        end_soc=80,
    )
    latest = await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=today,
        kwh=8.0,
        cost_pence=120,
        odometer_km=10_350,
        end_soc=90,
    )

    async with test_sessionmaker() as session:
        summary = await dashboard_summary(session, user.id)

    assert len(summary.cars) == 1
    panel = summary.cars[0]
    assert panel.id == car.id
    # No orchestrator passed → battery_level falls back to latest session's end_soc.
    assert panel.battery_level == 90
    assert panel.last_state is None
    assert panel.charging_cable_connected is False
    assert panel.last_connected is not None
    # Should be the latest session's charge_end_at.
    assert panel.last_connected.date() == latest.date

    totals = summary.lifetime_totals
    assert totals.sessions_count == 3
    assert totals.kwh == pytest.approx(30.0)
    assert totals.cost_pence == 450
    # 10_350 - 10_000 = 350km
    assert totals.distance_km == 350

    assert len(summary.recent_sessions) == 3
    # Order is date desc, id desc.
    assert summary.recent_sessions[0].id == latest.id


@pytest.mark.asyncio
async def test_dashboard_summary_multi_car_top_locations(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    car_a = await _make_car(test_sessionmaker, user.id, model="Born")
    car_b = await _make_car(test_sessionmaker, user.id, model="Tavascan")

    home = await _make_location(test_sessionmaker, user.id, name="Home", visit_count=10)
    work = await _make_location(test_sessionmaker, user.id, name="Work", visit_count=4)
    rapid = await _make_location(
        test_sessionmaker, user.id, name="Gridserve", visit_count=2
    )
    await _make_location(test_sessionmaker, user.id, name="Visited Once", visit_count=1)

    today = date(2026, 5, 1)
    # Home: 2 sessions across both cars.
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car_a.id,
        when=today,
        kwh=20.0,
        cost_pence=150,
        location_id=home.id,
    )
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car_b.id,
        when=today - timedelta(days=1),
        kwh=15.0,
        cost_pence=110,
        location_id=home.id,
    )
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car_a.id,
        when=today - timedelta(days=2),
        kwh=8.0,
        cost_pence=60,
        location_id=work.id,
    )
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car_b.id,
        when=today - timedelta(days=3),
        kwh=42.0,
        cost_pence=3500,
        location_id=rapid.id,
    )

    async with test_sessionmaker() as session:
        summary = await dashboard_summary(session, user.id)

    assert len(summary.cars) == 2
    # Top locations: ordered by visit_count desc.
    assert [loc.name for loc in summary.top_locations[:3]] == ["Home", "Work", "Gridserve"]
    home_stat = summary.top_locations[0]
    assert home_stat.total_kwh == pytest.approx(35.0)
    assert home_stat.total_cost_pence == 260
    # All 4 locations in scope (limit is 5, we created 4).
    assert len(summary.top_locations) == 4


@pytest.mark.asyncio
async def test_dashboard_summary_orchestrator_overrides_battery(test_sessionmaker):
    user = await _make_user(test_sessionmaker)
    car = await _make_car(test_sessionmaker, user.id)
    await _make_session(
        test_sessionmaker,
        user_id=user.id,
        car_id=car.id,
        when=date(2026, 5, 1),
        kwh=5.0,
        cost_pence=40,
        end_soc=50,
    )

    orch = SyncOrchestrator()
    state = orch.ensure_state(car.id)
    state.last_state = "CHARGING"
    state.last_soc = 73
    state.last_car_captured_timestamp = _utcnow()
    state.next_poll_at = _utcnow() + timedelta(minutes=5)
    state.active_job_id = "job-abc"

    async with test_sessionmaker() as session:
        summary = await dashboard_summary(session, user.id, orchestrator=orch)

    panel = summary.cars[0]
    assert panel.battery_level == 73
    assert panel.last_soc == 73
    assert panel.last_state == "CHARGING"
    assert panel.charging_cable_connected is True
    assert panel.active_job_id == "job-abc"
    assert panel.next_poll_at is not None


@pytest.mark.asyncio
async def test_dashboard_summary_excludes_other_users(test_sessionmaker):
    alice = await _make_user(test_sessionmaker, username="alice")
    bob = await _make_user(test_sessionmaker, username="bob")
    alice_car = await _make_car(test_sessionmaker, alice.id)
    await _make_car(test_sessionmaker, bob.id)
    await _make_session(
        test_sessionmaker,
        user_id=alice.id,
        car_id=alice_car.id,
        when=date(2026, 5, 1),
        kwh=10.0,
        cost_pence=100,
    )

    async with test_sessionmaker() as session:
        bob_summary = await dashboard_summary(session, bob.id)

    # Bob has his own car, so panels are not empty — but Alice's car must
    # not leak in.
    assert all(panel.id != alice_car.id for panel in bob_summary.cars)
    assert bob_summary.lifetime_totals.sessions_count == 0
    assert bob_summary.recent_sessions == []
    assert bob_summary.top_locations == []
