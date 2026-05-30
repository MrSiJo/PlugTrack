"""Tests for session_metrics — petrol comparison + chain handling."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from plugtrack.models import Car, ChargingSession, Setting, User
from plugtrack.services.session_metrics import (
    _observed_mi_per_kwh,
    compute_savings_for_sessions,
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


# ---------------------------------------------------------------------------
# Energy-based petrol-comparison fallback (comparison_basis = "estimated").
# ---------------------------------------------------------------------------

_KM_PER_MILE = 1.609344


def _add_petrol_settings(s, *, p_per_litre: float = 151.9, mpg: float = 54.1):
    s.add(Setting(key="petrol_price_p_per_litre", value=str(p_per_litre), value_type="float", group_name="cost", label="x", description=None, default_value=str(p_per_litre)))
    s.add(Setting(key="petrol_mpg", value=str(mpg), value_type="float", group_name="cost", label="x", description=None, default_value=str(mpg)))


@pytest.mark.asyncio
async def test_estimate_no_odometer_uses_kwh_calculated(test_sessionmaker):
    """No odometer + energy + petrol settings → basis='estimated', with
    miles / petrol-equivalent / savings derived from kwh_calculated × nominal.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.5)
        _add_petrol_settings(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=17.7,
            cost_pence=368, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)

        est_miles = 17.7 * 3.5  # 61.95 mi
        ppm = (151.9 * 4.54609) / 54.1
        assert m.comparison_basis == "estimated"
        assert m.miles_since_previous == float(round(est_miles))
        assert m.petrol_equivalent_cost_p == round(est_miles * ppm)
        assert m.savings_vs_petrol_p == m.petrol_equivalent_cost_p - 368
        assert m.cost_per_mile_p == round(368 / est_miles, 2)


@pytest.mark.asyncio
async def test_estimate_falls_back_to_kwh_added(test_sessionmaker):
    """kwh_calculated NULL → estimate uses kwh_added instead."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.5)
        _add_petrol_settings(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=None,
            cost_pence=400, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)

        est_miles = 18.0 * 3.5  # 63.0 mi (from kwh_added)
        assert m.comparison_basis == "estimated"
        assert m.miles_since_previous == float(round(est_miles))


@pytest.mark.asyncio
async def test_measured_span_no_regression(test_sessionmaker):
    """Odometer span present → basis='measured' (existing chain path)."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        await s.commit()

        cs = await s.get(ChargingSession, 2)
        m = await compute_session_metrics(s, cs)

        assert m.comparison_basis == "measured"
        miles = (1100.0 - 1000.0) / _KM_PER_MILE
        assert m.miles_since_previous == float(round(miles))


@pytest.mark.asyncio
async def test_zero_mile_followup_basis_none(test_sessionmaker):
    """Zero-mile chain follow-up stays anchored; basis stays None — the
    estimate must not hijack the chain follow-up path.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        s.add(_session(id=3, date=date(2026, 5, 1), odo_km=1100.0, cost_pence=300))
        await s.commit()

        followup = await s.get(ChargingSession, 3)
        m = await compute_session_metrics(s, followup)

        assert m.comparison_basis is None
        assert m.miles_since_previous is None
        assert m.chain_anchor_id == 2


@pytest.mark.asyncio
async def test_zero_energy_session_no_estimate(test_sessionmaker):
    """start_soc == end_soc → kwh_calculated is 0/None, no estimate, basis None."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        _add_petrol_settings(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=80, end_soc=80, kwh_added=0.0, kwh_calculated=0.0,
            cost_pence=100, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)

        assert m.comparison_basis is None
        assert m.miles_since_previous is None
        assert m.savings_vs_petrol_p is None


@pytest.mark.asyncio
async def test_estimate_without_petrol_settings(test_sessionmaker):
    """Estimate present but petrol settings missing → basis='estimated',
    petrol_equivalent_cost_p is None (cost still renders as the EV side).
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.5)
        # No petrol settings seeded.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=17.7,
            cost_pence=368, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)

        assert m.comparison_basis == "estimated"
        assert m.petrol_equivalent_cost_p is None
        assert m.savings_vs_petrol_p is None
        # The EV cost/mile is still derivable from the session's own cost.
        assert m.miles_since_previous == float(round(17.7 * 3.5))


@pytest.mark.asyncio
async def test_estimate_uses_observed_efficiency(test_sessionmaker):
    """When the car has clean measured legs, the estimate must use the
    *observed* mi/kWh (from odometer history) — not the nominal.

    Two advancing odometer legs imply a known observed efficiency that
    differs from the configured nominal; the estimated session (no
    odometer) must use the observed figure.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # Nominal (5.0) is deliberately far from the observed (3.0) so the
        # two produce clearly different rounded miles.
        _seed_car(s, battery_kwh=50.0, mi_per_kwh=5.0)
        _add_petrol_settings(s)

        # Two measured legs that consume a known amount of SoC over a known
        # distance, implying observed = 3.0 mi/kWh.
        #
        # Each leg advances 120.7008 km = exactly 75 mi. Consumed between
        # consecutive charges = end_soc(prev) 80 - start_soc(next) 30 = 50 pp
        # = 25 kWh (on a 50 kWh pack). 75 mi / 25 kWh = 3.0 mi/kWh.
        # Aggregate = 150 mi / 50 kWh = 3.0 mi/kWh.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 1),
            start_soc=30, end_soc=80, kwh_added=25.0,
            odometer_at_session_km=1000.0,
            cost_basis="home_rate", source="manual",
        ))
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 5),
            start_soc=30, end_soc=80, kwh_added=25.0,
            odometer_at_session_km=1000.0 + 120.7008,
            cost_basis="home_rate", source="manual",
        ))
        s.add(ChargingSession(
            id=3, user_id=1, car_id=1, date=date(2026, 5, 9),
            start_soc=30, end_soc=80, kwh_added=25.0,
            odometer_at_session_km=1000.0 + 2 * 120.7008,
            cost_basis="home_rate", source="manual",
        ))
        # The estimated session — no odometer.
        s.add(ChargingSession(
            id=4, user_id=1, car_id=1, date=date(2026, 5, 12),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=15.0,
            cost_pence=300, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        observed = await _observed_mi_per_kwh(
            s, car_id=1, user_id=1, battery_kwh=50.0
        )
        assert observed == pytest.approx(3.0, abs=1e-4)

        cs = await s.get(ChargingSession, 4)
        m = await compute_session_metrics(s, cs)

        assert m.comparison_basis == "estimated"
        # Must use observed (3.0 → 45 mi), NOT nominal (5.0 → 75 mi).
        assert m.miles_since_previous == float(round(15.0 * 3.0))
        assert m.miles_since_previous != float(round(15.0 * 5.0))


@pytest.mark.asyncio
async def test_estimate_falls_back_to_nominal_efficiency(test_sessionmaker):
    """With <1 clean measured leg (only one odometer reading), observed
    efficiency is None and the estimate uses the nominal.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.5)
        _add_petrol_settings(s)
        # Single odometer reading — no pair to form a leg.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 1),
            start_soc=30, end_soc=80, kwh_added=25.0,
            odometer_at_session_km=1000.0,
            cost_basis="home_rate", source="manual",
        ))
        # Estimated session — no odometer.
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 5),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=15.0,
            cost_pence=300, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        observed = await _observed_mi_per_kwh(
            s, car_id=1, user_id=1, battery_kwh=59.0
        )
        assert observed is None

        cs = await s.get(ChargingSession, 2)
        m = await compute_session_metrics(s, cs)
        assert m.comparison_basis == "estimated"
        # Uses nominal 3.5.
        assert m.miles_since_previous == float(round(15.0 * 3.5))


# ---------------------------------------------------------------------------
# _observed_mi_per_kwh — unit-level cases.
# ---------------------------------------------------------------------------


def _odo_session(*, id, date, odo_km, start_soc, end_soc):
    return ChargingSession(
        id=id, user_id=1, car_id=1, date=date,
        start_soc=start_soc, end_soc=end_soc, kwh_added=10.0,
        odometer_at_session_km=odo_km,
        cost_basis="home_rate", source="manual",
    )


@pytest.mark.asyncio
async def test_observed_two_clean_legs_aggregate(test_sessionmaker):
    """Two advancing legs with clean SoC drops → correct aggregate mi/kWh."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # battery 50 kWh.
        # A→B: 80 km = 49.7097 mi; consumed = 80-30 = 50pp = 25 kWh.
        # B→C: 80 km = 49.7097 mi; consumed = 80-30 = 50pp = 25 kWh.
        s.add(_odo_session(id=1, date=date(2026, 5, 1), odo_km=1000.0, start_soc=30, end_soc=80))
        s.add(_odo_session(id=2, date=date(2026, 5, 5), odo_km=1080.0, start_soc=30, end_soc=80))
        s.add(_odo_session(id=3, date=date(2026, 5, 9), odo_km=1160.0, start_soc=30, end_soc=80))
        await s.commit()

        observed = await _observed_mi_per_kwh(s, car_id=1, user_id=1, battery_kwh=50.0)
        expected = (160.0 / _KM_PER_MILE) / 50.0
        assert observed == pytest.approx(expected, abs=1e-6)


@pytest.mark.asyncio
async def test_observed_skips_non_advancing_leg(test_sessionmaker):
    """A same-odometer (non-advancing) leg is skipped without dividing by
    zero — only the advancing leg contributes.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # B has the same odometer as A (no advance) — skipped.
        # B→C advances 80 km, consumed = end_soc(B) 80 - start_soc(C) 30 = 50pp.
        s.add(_odo_session(id=1, date=date(2026, 5, 1), odo_km=1000.0, start_soc=30, end_soc=80))
        s.add(_odo_session(id=2, date=date(2026, 5, 5), odo_km=1000.0, start_soc=30, end_soc=80))
        s.add(_odo_session(id=3, date=date(2026, 5, 9), odo_km=1080.0, start_soc=30, end_soc=80))
        await s.commit()

        observed = await _observed_mi_per_kwh(s, car_id=1, user_id=1, battery_kwh=50.0)
        # Only the B→C leg: 80 km / consumed. Seg = [B, C]; drop = 80-30 = 50pp = 25 kWh.
        expected = (80.0 / _KM_PER_MILE) / 25.0
        assert observed == pytest.approx(expected, abs=1e-6)


@pytest.mark.asyncio
async def test_observed_soc_rise_clamps_to_zero(test_sessionmaker):
    """A SoC-rise pair within a leg clamps to 0 (unlogged charging), not a
    negative — the leg is not corrupted.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # Two advancing legs, A→M and M→B (each 120.7008 km = 75 mi):
        #   Leg A→M, seg [A, M]: A.end_soc 80 - M.start_soc 90 = -10 →
        #     clamps to 0 → consumed 0 → leg skipped (not corrupted by the
        #     negative).
        #   Leg M→B, seg [M, B]: M.end_soc 95 - B.start_soc 45 = 50pp =
        #     25 kWh → 75 mi / 25 kWh = 3.0 mi/kWh.
        # Only M→B contributes; the SoC-rise pair did not poison it.
        s.add(_odo_session(id=1, date=date(2026, 5, 1), odo_km=1000.0, start_soc=30, end_soc=80))
        s.add(_odo_session(id=2, date=date(2026, 5, 5), odo_km=1000.0 + 120.7008, start_soc=90, end_soc=95))
        s.add(_odo_session(id=3, date=date(2026, 5, 9), odo_km=1000.0 + 2 * 120.7008, start_soc=45, end_soc=80))
        await s.commit()

        observed = await _observed_mi_per_kwh(s, car_id=1, user_id=1, battery_kwh=50.0)
        assert observed == pytest.approx(3.0, abs=1e-4)


@pytest.mark.asyncio
async def test_observed_implausible_returns_none(test_sessionmaker):
    """An observed result outside the [1.0, 8.0] band → None (nominal fallback)."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # Tiny distance for a large SoC drop → implausibly low mi/kWh.
        # A→B: 2 km = 1.24 mi; consumed = 50pp = 25 kWh → 0.05 mi/kWh < 1.0.
        s.add(_odo_session(id=1, date=date(2026, 5, 1), odo_km=1000.0, start_soc=30, end_soc=80))
        s.add(_odo_session(id=2, date=date(2026, 5, 5), odo_km=1002.0, start_soc=30, end_soc=80))
        await s.commit()

        observed = await _observed_mi_per_kwh(s, car_id=1, user_id=1, battery_kwh=50.0)
        assert observed is None


@pytest.mark.asyncio
async def test_observed_fewer_than_two_readings_returns_none(test_sessionmaker):
    """Fewer than two odometer readings → None (no leg can form)."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        s.add(_odo_session(id=1, date=date(2026, 5, 1), odo_km=1000.0, start_soc=30, end_soc=80))
        await s.commit()

        observed = await _observed_mi_per_kwh(s, car_id=1, user_id=1, battery_kwh=50.0)
        assert observed is None


# ---------------------------------------------------------------------------
# compute_savings_for_sessions — the batch path must agree, byte-for-byte,
# with compute_session_metrics for every row (the consistency guarantee).
# ---------------------------------------------------------------------------


async def _assert_batch_matches_single(s, rows):
    """For each row, the batch (saved, basis) equals the per-session metrics'
    (savings_vs_petrol_p, comparison_basis)."""
    from sqlalchemy import select

    batch = await compute_savings_for_sessions(s, list(rows))
    for cs in rows:
        m = await compute_session_metrics(s, cs)
        saved, basis = batch[cs.id]
        assert saved == m.savings_vs_petrol_p, (
            f"session {cs.id}: batch saved={saved} != single "
            f"{m.savings_vs_petrol_p}"
        )
        assert basis == m.comparison_basis, (
            f"session {cs.id}: batch basis={basis} != single "
            f"{m.comparison_basis}"
        )


@pytest.mark.asyncio
async def test_batch_savings_matches_single_measured_and_chain(test_sessionmaker):
    """Measured anchor + zero-mile follow-ups: batch agrees with single."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        s.add(_session(id=3, date=date(2026, 5, 1), odo_km=1100.0, cost_pence=300))
        s.add(_session(id=4, date=date(2026, 5, 2), odo_km=1100.0, cost_pence=400))
        await s.commit()

        rows = [await s.get(ChargingSession, i) for i in (1, 2, 3, 4)]
        await _assert_batch_matches_single(s, rows)

        # Spot-check the basis breakdown: id=2 is the measured anchor, the
        # follow-ups (3, 4) anchor back (basis None), id=1 has no prior
        # odometer so it estimates.
        batch = await compute_savings_for_sessions(s, rows)
        assert batch[2][1] == "measured"
        assert batch[3] == (None, None)
        assert batch[4] == (None, None)


@pytest.mark.asyncio
async def test_batch_savings_matches_single_estimated_and_none(test_sessionmaker):
    """A mix of estimated (no odometer) and none (zero-energy) rows."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.5)
        _add_petrol_settings(s)
        # Estimated — no odometer, has energy + cost.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=17.7,
            cost_pence=368, cost_basis="home_rate", source="manual",
        ))
        # None — zero energy, no estimate possible.
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 15),
            start_soc=80, end_soc=80, kwh_added=0.0, kwh_calculated=0.0,
            cost_pence=100, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        rows = [await s.get(ChargingSession, i) for i in (1, 2)]
        await _assert_batch_matches_single(s, rows)

        batch = await compute_savings_for_sessions(s, rows)
        assert batch[1][1] == "estimated"
        assert batch[2] == (None, None)


@pytest.mark.asyncio
async def test_batch_savings_matches_single_no_petrol_settings(test_sessionmaker):
    """Estimated basis but petrol settings missing → saved None, basis
    'estimated'. Batch must mirror the single path exactly."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.5)
        # No petrol settings.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=17.7,
            cost_pence=368, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        rows = [await s.get(ChargingSession, 1)]
        await _assert_batch_matches_single(s, rows)
        batch = await compute_savings_for_sessions(s, rows)
        assert batch[1] == (None, "estimated")


@pytest.mark.asyncio
async def test_batch_savings_uses_full_history_not_input_window(test_sessionmaker):
    """The batch derives observed efficiency from the car's FULL history,
    even when only a subset of rows is passed in. Passing just the estimated
    row must still produce the observed-efficiency answer that the single
    path (which sees the whole DB) computes.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # Nominal (5.0) far from observed (3.0).
        _seed_car(s, battery_kwh=50.0, mi_per_kwh=5.0)
        _add_petrol_settings(s)
        # Three measured legs implying observed 3.0 mi/kWh.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 1),
            start_soc=30, end_soc=80, kwh_added=25.0,
            odometer_at_session_km=1000.0,
            cost_basis="home_rate", source="manual",
        ))
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 5),
            start_soc=30, end_soc=80, kwh_added=25.0,
            odometer_at_session_km=1000.0 + 120.7008,
            cost_basis="home_rate", source="manual",
        ))
        s.add(ChargingSession(
            id=3, user_id=1, car_id=1, date=date(2026, 5, 9),
            start_soc=30, end_soc=80, kwh_added=25.0,
            odometer_at_session_km=1000.0 + 2 * 120.7008,
            cost_basis="home_rate", source="manual",
        ))
        # Estimated session — no odometer.
        s.add(ChargingSession(
            id=4, user_id=1, car_id=1, date=date(2026, 5, 12),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=15.0,
            cost_pence=300, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        estimated = await s.get(ChargingSession, 4)
        # Pass ONLY the estimated row — the earlier measured legs are not in
        # the input set but must still drive observed efficiency.
        batch = await compute_savings_for_sessions(s, [estimated])
        single = await compute_session_metrics(s, estimated)
        assert batch[4] == (
            single.savings_vs_petrol_p,
            single.comparison_basis,
        )
        assert batch[4][1] == "estimated"


@pytest.mark.asyncio
async def test_batch_savings_empty_rows_returns_empty(test_sessionmaker):
    async with test_sessionmaker() as s:
        assert await compute_savings_for_sessions(s, []) == {}


@pytest.mark.asyncio
async def test_measured_anchor_does_not_absorb_later_null_odometer_charge(
    test_sessionmaker,
):
    """Regression: a measured anchor must NOT fold a *later* odometer-less
    manual charge into its chain.

    Before the fix the forward chain absorbed every subsequent
    NULL-odometer session, double-counting its cost against the anchor's
    miles AND on its own estimate row — the production -£13.08 bug. Since
    the energy-estimate fallback landed, most charges are manual (no
    odometer), so a null no longer means "didn't move since the anchor";
    such sessions are independent estimates.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(Setting(key="petrol_price_p_per_litre", value="150.0", value_type="float", group_name="cost", label="x", description=None, default_value="150.0"))
        s.add(Setting(key="petrol_mpg", value="50.0", value_type="float", group_name="cost", label="x", description=None, default_value="50.0"))
        # Prior reading so the anchor has a measured span.
        s.add(_session(id=1, date=date(2026, 1, 1), odo_km=900.0, cost_pence=50))
        # Anchor: measured span, cost 1000p.
        s.add(_session(id=2, date=date(2026, 1, 3), odo_km=1000.0, cost_pence=1000))
        # Later independent manual charge — NO odometer, weeks later.
        s.add(ChargingSession(
            id=3, user_id=1, car_id=1, date=date(2026, 1, 20),
            start_soc=60, end_soc=90, kwh_added=12.0, kwh_calculated=12.0,
            odometer_at_session_km=None, cost_pence=300,
            cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        anchor = await s.get(ChargingSession, 2)
        m_anchor = await compute_session_metrics(s, anchor)
        # Anchor's chain is itself only — the later null charge is excluded.
        assert m_anchor.chain_session_ids == [2]
        assert m_anchor.chain_total_cost_pence == 1000
        assert m_anchor.comparison_basis == "measured"

        # The later manual charge stands on its own as an estimate.
        later = await s.get(ChargingSession, 3)
        m_later = await compute_session_metrics(s, later)
        assert m_later.comparison_basis == "estimated"

        # Batch agrees with single for both rows.
        batch = await compute_savings_for_sessions(s, [anchor, later])
        assert batch[2] == (m_anchor.savings_vs_petrol_p, m_anchor.comparison_basis)
        assert batch[3] == (m_later.savings_vs_petrol_p, m_later.comparison_basis)
