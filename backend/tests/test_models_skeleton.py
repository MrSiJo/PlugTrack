"""Smoke tests proving the skeleton tables exist and FKs hold."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_car_belongs_to_user(test_sessionmaker):
    from plugtrack.models import Car, User

    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)

        assert car.id == 1
        assert car.user_id == user.id


@pytest.mark.asyncio
async def test_charging_session_belongs_to_car(test_sessionmaker):
    from plugtrack.models import Car, ChargingSession, User
    from datetime import date

    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)

        cs = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=date.today(),
            source="manual",
            start_soc=20,
            end_soc=80,
            kwh_added=46.2,
        )
        session.add(cs)
        await session.commit()
        await session.refresh(cs)

        assert cs.id == 1


@pytest.mark.asyncio
async def test_sync_run_skeleton(test_sessionmaker):
    from plugtrack.models import Car, SyncRun, User
    from datetime import datetime, timezone

    async with test_sessionmaker() as session:
        user = User(username="alice", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)

        run = SyncRun(
            car_id=car.id, started_at=datetime.now(timezone.utc), status="running"
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        assert run.id == 1
        assert run.status == "running"
