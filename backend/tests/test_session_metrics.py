"""Tests for session_metrics — petrol comparison + chain handling."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from plugtrack.models import Car, ChargingSession, Setting, User
from plugtrack.services.session_metrics import (
    compute_session_metrics,
    petrol_pence_per_mile,
)


def test_petrol_pence_per_mile_uk_gallons():
    # 150p/L * 4.54609 / 50 MPG = 13.638...
    ppm = petrol_pence_per_mile(150.0, 50.0)
    assert ppm is not None
    assert round(ppm, 2) == 13.64


def test_petrol_pence_per_mile_rejects_zero():
    assert petrol_pence_per_mile(0, 50) is None
    assert petrol_pence_per_mile(150, 0) is None


@pytest.mark.asyncio
async def test_metrics_none_without_settings(test_sessionmaker):
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        s.add(
            ChargingSession(
                user_id=1, car_id=1, date=date(2026, 5, 1),
                start_soc=20, end_soc=80, kwh_added=40.0, source="manual",
                cost_basis="home_rate",
            )
        )
        await s.commit()
        cs = (await s.execute(_one(ChargingSession))).scalar_one()
        m = await compute_session_metrics(s, cs)
        # No prior odometer + no settings → all derived fields None.
        assert m.miles_since_previous is None
        assert m.cost_per_mile_p is None
        assert m.savings_vs_petrol_p is None


@pytest.mark.asyncio
async def test_anchor_session_uses_chain_total(test_sessionmaker):
    """Anchor session has miles; the two zero-mile follow-ups roll their
    cost into the anchor's saving figure.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        s.add(Setting(key="petrol_price_p_per_litre", value="150.0", value_type="float", group_name="cost", label="x", description=None, default_value="150.0"))
        s.add(Setting(key="petrol_mpg", value="50.0", value_type="float", group_name="cost", label="x", description=None, default_value="50.0"))
        # Prior session with odometer at 1000 km.
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        # Anchor — moved to 1100 km (~62 miles).
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        # Two follow-ups with same odometer (no driving).
        s.add(_session(id=3, date=date(2026, 5, 1), odo_km=1100.0, cost_pence=300))
        s.add(_session(id=4, date=date(2026, 5, 2), odo_km=1100.0, cost_pence=400))
        await s.commit()

        anchor = await s.get(ChargingSession, 2)
        m = await compute_session_metrics(s, anchor)

        miles = (1100.0 - 1000.0) / 1.609344
        assert m.miles_since_previous == float(round(miles))
        # Chain total = 500 + 300 + 400.
        assert m.chain_total_cost_pence == 1200
        assert sorted(m.chain_session_ids) == [2, 3, 4]
        # Petrol cost vs the chain total (not just the anchor).
        ppm = (150.0 * 4.54609) / 50.0
        assert m.petrol_equivalent_cost_p == round(miles * ppm)
        assert m.savings_vs_petrol_p == m.petrol_equivalent_cost_p - 1200
        assert m.chain_anchor_id is None


@pytest.mark.asyncio
async def test_zero_mile_followup_points_at_anchor(test_sessionmaker):
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        s.add(Setting(key="petrol_price_p_per_litre", value="150.0", value_type="float", group_name="cost", label="x", description=None, default_value="150.0"))
        s.add(Setting(key="petrol_mpg", value="50.0", value_type="float", group_name="cost", label="x", description=None, default_value="50.0"))
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        s.add(_session(id=3, date=date(2026, 5, 1), odo_km=1100.0, cost_pence=300))
        await s.commit()

        followup = await s.get(ChargingSession, 3)
        m = await compute_session_metrics(s, followup)

        # Zero-mile follow-ups don't get their own comparison; they
        # just point back at the anchor.
        assert m.miles_since_previous is None
        assert m.savings_vs_petrol_p is None
        assert m.chain_anchor_id == 2


def _session(*, id, date, odo_km, cost_pence):
    return ChargingSession(
        id=id,
        user_id=1,
        car_id=1,
        date=date,
        start_soc=40,
        end_soc=80,
        kwh_added=10.0,
        odometer_at_session_km=odo_km,
        cost_pence=cost_pence,
        cost_basis="home_rate",
        source="manual",
    )


def _one(model):
    from sqlalchemy import select
    return select(model)


# ---------------------------------------------------------------------------
# Charge-mechanics metrics: range added, duration, avg/peak power, efficiency.
# ---------------------------------------------------------------------------


def _seed_car(s, *, battery_kwh: float = 59.0, mi_per_kwh: float = 3.6) -> Car:
    car = Car(
        user_id=1,
        make="Cupra",
        model="Born",
        battery_kwh=battery_kwh,
        nominal_efficiency_mi_per_kwh=mi_per_kwh,
        provider="cupra_connect",
        provider_vehicle_id="VIN-T",
    )
    s.add(car)
    return car


@pytest.mark.asyncio
async def test_range_added_from_soc_delta(test_sessionmaker):
    """Range added = (Δsoc/100) × battery_kwh × nominal_mi_per_kwh."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.6)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=86, kwh_added=18.0,
            cost_basis="override_total", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        # 26 pp -> 15.34 kWh -> 55.224 mi -> rounds to 55.
        assert m.range_added_miles == pytest.approx(55.22, abs=0.1)


@pytest.mark.asyncio
async def test_duration_and_average_power(test_sessionmaker):
    """charge_end_at - charge_start_at + kwh_added → minutes, avg kW."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            charge_start_at=datetime(2026, 5, 14, 11, 18, tzinfo=timezone.utc),
            charge_end_at=datetime(2026, 5, 14, 11, 43, tzinfo=timezone.utc),
            start_soc=60, end_soc=86, kwh_added=18.0,
            cost_basis="override_total", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        assert m.duration_minutes == 25
        # 18 kWh in 25 min = 43.2 kW avg.
        assert m.average_power_kw == pytest.approx(43.2, abs=0.1)


@pytest.mark.asyncio
async def test_duration_none_when_timestamps_missing(test_sessionmaker):
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=86, kwh_added=18.0,
            cost_basis="override_total", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        assert m.duration_minutes is None
        assert m.average_power_kw is None


@pytest.mark.asyncio
async def test_peak_power_from_curve(test_sessionmaker):
    """power_curve is [[delta_s, soc, kW], ...]; peak = max kW."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=86, kwh_added=18.0,
            cost_basis="override_total", source="synthesis",
            power_curve=[
                [0.0, 60.0, 30.0],
                [60.0, 65.0, 90.0],
                [120.0, 75.0, 47.2],
                [180.0, 86.0, 15.0],
            ],
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        assert m.peak_power_kw == pytest.approx(90.0, abs=0.01)


@pytest.mark.asyncio
async def test_peak_power_none_for_manual_sessions(test_sessionmaker):
    """Manual sessions have no power_curve; peak is None."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=86, kwh_added=18.0,
            cost_basis="override_total", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        assert m.peak_power_kw is None


@pytest.mark.asyncio
async def test_efficiency_percent(test_sessionmaker):
    """kwh_calculated / kwh_added * 100 → energy efficiency %."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=86, kwh_added=18.0,
            kwh_calculated=15.34,
            cost_basis="override_total", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        # 15.34 / 18.0 = 85.22%
        assert m.efficiency_percent == pytest.approx(85.2, abs=0.1)


@pytest.mark.asyncio
async def test_efficiency_none_when_kwh_calculated_missing(test_sessionmaker):
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=86, kwh_added=18.0,
            cost_basis="override_total", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        assert m.efficiency_percent is None
