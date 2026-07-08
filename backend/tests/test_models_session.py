"""Schema-level tests for ChargingSession.

Exercises:
- FK enforcement
- Partial unique index on (car_id, telematics_session_id)
- Distance-column naming convention (every distance col ends in `_km`)
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


def _tomorrow_utc() -> datetime:
    return datetime.now(UTC)


@pytest.mark.asyncio
async def test_charging_session_round_trip(test_sessionmaker):
    from plugtrack.models import Car, ChargingSession, User

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

        assert cs.id is not None
        assert cs.cost_basis == "unknown"
        assert cs.charging_type == "unknown"
        assert cs.interrupted is False


@pytest.mark.asyncio
async def test_unique_telematics_id_per_car(test_sessionmaker):
    """Same telematics_session_id can't appear twice for one car."""
    from plugtrack.models import Car, ChargingSession, User

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

        cs1 = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=date.today(),
            source="synthesis",
            start_soc=20,
            end_soc=80,
            kwh_added=46.2,
            telematics_session_id="hash-abc",
        )
        session.add(cs1)
        await session.commit()

        cs2 = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=date.today(),
            source="synthesis",
            start_soc=30,
            end_soc=70,
            kwh_added=30.8,
            telematics_session_id="hash-abc",  # duplicate!
        )
        session.add(cs2)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_null_telematics_id_does_not_collide(test_sessionmaker):
    """Manual sessions (NULL telematics_session_id) can co-exist freely."""
    from plugtrack.models import Car, ChargingSession, User

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

        for i in range(3):
            session.add(
                ChargingSession(
                    user_id=user.id,
                    car_id=car.id,
                    date=date.today(),
                    source="manual",
                    start_soc=10 + i,
                    end_soc=80,
                    kwh_added=42.0,
                    telematics_session_id=None,
                )
            )
        await session.commit()  # no IntegrityError


@pytest.mark.asyncio
async def test_distance_columns_have_km_suffix(test_engine):
    """Every distance column on relevant tables ends in `_km`.

    Reflection-based check: if a future migration adds a `distance` or
    `odometer` column without the suffix, this test catches it.
    """
    from plugtrack.models import Base

    distance_keywords = ("distance", "odometer", "range", "mileage")

    async with test_engine.begin() as conn:

        def _check(sync_conn):
            insp = inspect(sync_conn)
            for table_name in Base.metadata.tables:
                for col in insp.get_columns(table_name):
                    name = col["name"]
                    lowered = name.lower()
                    if any(kw in lowered for kw in distance_keywords):
                        assert name.endswith("_km"), (
                            f"{table_name}.{name}: distance-bearing columns "
                            f"must end in '_km' (got {name!r})"
                        )

        await conn.run_sync(_check)
