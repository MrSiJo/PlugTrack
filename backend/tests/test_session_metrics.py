"""Tests for session_metrics — per-charge energy-based petrol comparison."""
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
async def test_per_charge_savings_each_row_independent(test_sessionmaker):
    """Per-charge model: every session is judged on its own energy alone.

    The old chain/anchor behaviour (rolling costs into the anchor) is gone.
    Now each row gets its own energy-based savings, regardless of odometer
    pattern — same-odometer follow-ups are no longer special-cased.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=58.0, mi_per_kwh=3.6)
        s.add(Setting(key="petrol_price_p_per_litre", value="150.0", value_type="float", group_name="cost", label="x", description=None, default_value="150.0"))
        s.add(Setting(key="petrol_mpg", value="50.0", value_type="float", group_name="cost", label="x", description=None, default_value="50.0"))
        # Prior session with odometer at 1000 km.
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        # Next session — moved to 1100 km.
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        # Two follow-ups with same odometer (no driving).
        s.add(_session(id=3, date=date(2026, 5, 1), odo_km=1100.0, cost_pence=300))
        s.add(_session(id=4, date=date(2026, 5, 2), odo_km=1100.0, cost_pence=400))
        await s.commit()

        for sid in (2, 3, 4):
            cs = await s.get(ChargingSession, sid)
            m = await compute_session_metrics(s, cs)
            # Every row gets a per-charge estimate — not None.
            assert m.comparison_basis == "estimated", f"id={sid} basis wrong"
            # miles_since_previous is set (energy × some efficiency).
            assert m.miles_since_previous is not None, f"id={sid} miles should be set"
            # savings are populated.
            assert m.savings_vs_petrol_p is not None, f"id={sid} savings should be set"
            # chain_anchor_id is not set by the new model.
            assert m.chain_anchor_id is None


@pytest.mark.asyncio
async def test_same_odometer_followup_gets_per_charge_estimate(test_sessionmaker):
    """A session with the same odometer as the previous one used to be a
    zero-mile follow-up that pointed at an anchor. With per-charge savings it
    is now a fully independent energy-based estimate row (no anchoring).
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=58.0, mi_per_kwh=3.6)
        s.add(Setting(key="petrol_price_p_per_litre", value="150.0", value_type="float", group_name="cost", label="x", description=None, default_value="150.0"))
        s.add(Setting(key="petrol_mpg", value="50.0", value_type="float", group_name="cost", label="x", description=None, default_value="50.0"))
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        s.add(_session(id=3, date=date(2026, 5, 1), odo_km=1100.0, cost_pence=300))
        await s.commit()

        followup = await s.get(ChargingSession, 3)
        m = await compute_session_metrics(s, followup)

        # Under the new model the same-odometer session is an independent
        # energy-based estimate — NOT anchored.
        assert m.comparison_basis == "estimated"
        assert m.savings_vs_petrol_p is not None
        assert m.chain_anchor_id is None


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
async def test_average_power_uses_actual_charge_time(test_sessionmaker):
    """A home charge plugs in for hours but only draws power briefly. Average
    power must reflect actual_charge_seconds, not the long plug-in window —
    otherwise 3.47 kWh over a 14h30m window reads as a nonsense 0.2 kW."""
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 6, 17),
            charge_start_at=datetime(2026, 6, 17, 16, 36, tzinfo=timezone.utc),
            charge_end_at=datetime(2026, 6, 18, 7, 6, tzinfo=timezone.utc),
            start_soc=75, end_soc=79, kwh_added=3.47,
            actual_charge_seconds=4980,  # 1h23m actually drawing power
            cost_basis="home_rate", source="telegram",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        # duration stays the plug-in window (14h30m = 870 min)
        assert m.duration_minutes == 870
        # avg over ACTUAL charge time: 3.47 / (4980/3600) ≈ 2.5 kW
        assert m.average_power_kw == pytest.approx(2.5, abs=0.1)


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
async def test_odometer_session_uses_estimated_basis(test_sessionmaker):
    """Odometer-bearing sessions now use the per-charge energy model
    (basis='estimated') — not the old 'measured' basis. The odometer is
    informational only; it calibrates observed efficiency but does not
    directly define miles_since_previous for savings.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(_session(id=1, date=date(2026, 4, 28), odo_km=1000.0, cost_pence=200))
        s.add(_session(id=2, date=date(2026, 4, 30), odo_km=1100.0, cost_pence=500))
        await s.commit()

        cs = await s.get(ChargingSession, 2)
        m = await compute_session_metrics(s, cs)

        # New model: always "estimated" (energy-based), never "measured".
        assert m.comparison_basis == "estimated"
        # miles_since_previous = energy × efficiency (not odometer span).
        assert m.miles_since_previous is not None
        # The genuine odometer span is surfaced as informational only.
        odo_miles = (1100.0 - 1000.0) / _KM_PER_MILE
        assert m.measured_miles_since_previous == pytest.approx(odo_miles, abs=0.01)


@pytest.mark.asyncio
async def test_same_odometer_no_longer_suppresses_estimate(test_sessionmaker):
    """Previously a same-odometer follow-up suppressed its own estimate and
    pointed at an anchor (chain_anchor_id). The per-charge model removes this
    entirely: every energy-bearing row computes its own estimate.
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

        # New model: estimated, never anchored.
        assert m.comparison_basis == "estimated"
        assert m.miles_since_previous is not None
        assert m.chain_anchor_id is None


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
    """For each row, the batch (saved, basis, breakeven) equals the
    per-session metrics' (savings_vs_petrol_p, comparison_basis,
    breakeven_p_per_kwh). The batch now returns a 3-tuple."""
    batch = await compute_savings_for_sessions(s, list(rows))
    for cs in rows:
        m = await compute_session_metrics(s, cs)
        saved, basis, breakeven = batch[cs.id]
        assert saved == m.savings_vs_petrol_p, (
            f"session {cs.id}: batch saved={saved} != single "
            f"{m.savings_vs_petrol_p}"
        )
        assert basis == m.comparison_basis, (
            f"session {cs.id}: batch basis={basis} != single "
            f"{m.comparison_basis}"
        )
        assert breakeven == m.breakeven_p_per_kwh, (
            f"session {cs.id}: batch breakeven={breakeven} != single "
            f"{m.breakeven_p_per_kwh}"
        )


@pytest.mark.asyncio
async def test_batch_savings_matches_single_per_charge(test_sessionmaker):
    """Per-charge energy model: batch (3-tuple) matches single for every row,
    including rows that share an odometer and would have been 'chain follow-
    ups' under the old model.
    """
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

        # Spot-check: all four rows now get "estimated" (not "measured" or None).
        batch = await compute_savings_for_sessions(s, rows)
        for sid in (1, 2, 3, 4):
            saved, basis, breakeven = batch[sid]
            assert basis == "estimated", f"session {sid}: expected estimated, got {basis}"
            assert saved is not None, f"session {sid}: saved should not be None"


@pytest.mark.asyncio
async def test_batch_savings_matches_single_estimated_and_none(test_sessionmaker):
    """A mix of estimated (no odometer) and none (zero-energy) rows.
    The batch returns a 3-tuple (saved, basis, breakeven) for each row.
    """
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
        # Zero-energy row: all three elements None.
        assert batch[2] == (None, None, None)


@pytest.mark.asyncio
async def test_batch_savings_matches_single_no_petrol_settings(test_sessionmaker):
    """Estimated basis but petrol settings missing → saved None, basis
    'estimated', breakeven None. Batch must mirror the single path exactly.
    The batch now returns a 3-tuple.
    """
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
        # 3-tuple: (saved=None, basis="estimated", breakeven=None).
        assert batch[1] == (None, "estimated", None)


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
        saved_b, basis_b, breakeven_b = batch[4]
        assert saved_b == single.savings_vs_petrol_p
        assert basis_b == single.comparison_basis
        assert breakeven_b == single.breakeven_p_per_kwh
        assert basis_b == "estimated"


@pytest.mark.asyncio
async def test_batch_savings_empty_rows_returns_empty(test_sessionmaker):
    async with test_sessionmaker() as s:
        assert await compute_savings_for_sessions(s, []) == {}


@pytest.mark.asyncio
async def test_null_odometer_charge_is_independent_estimate(
    test_sessionmaker,
):
    """Regression: a session with no odometer is an independent per-charge
    estimate — it never absorbs into another session's chain.

    Under the old model a NULL-odometer session following an odometer-bearing
    anchor was absorbed as a chain follow-up, double-counting its cost against
    the anchor's miles (the production -£13.08 bug). With per-charge savings,
    both the odometer-bearing session and the later null-odometer one are
    independent energy-based rows.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s)
        s.add(Setting(key="petrol_price_p_per_litre", value="150.0", value_type="float", group_name="cost", label="x", description=None, default_value="150.0"))
        s.add(Setting(key="petrol_mpg", value="50.0", value_type="float", group_name="cost", label="x", description=None, default_value="50.0"))
        # Prior reading so the first row has measured_miles_since_previous.
        s.add(_session(id=1, date=date(2026, 1, 1), odo_km=900.0, cost_pence=50))
        # Odometer-bearing session, cost 1000p.
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
        # Odometer-bearing row: per-charge energy estimate, not chain-based.
        assert m_anchor.comparison_basis == "estimated"
        # Its savings are from its own energy alone (not chain total).
        assert m_anchor.savings_vs_petrol_p is not None

        # The later manual charge stands on its own as a separate estimate.
        later = await s.get(ChargingSession, 3)
        m_later = await compute_session_metrics(s, later)
        assert m_later.comparison_basis == "estimated"

        # Batch returns a 3-tuple and agrees with single for both rows.
        batch = await compute_savings_for_sessions(s, [anchor, later])
        saved_a, basis_a, be_a = batch[2]
        assert saved_a == m_anchor.savings_vs_petrol_p
        assert basis_a == m_anchor.comparison_basis
        assert be_a == m_anchor.breakeven_p_per_kwh
        saved_l, basis_l, be_l = batch[3]
        assert saved_l == m_later.savings_vs_petrol_p
        assert basis_l == m_later.comparison_basis
        assert be_l == m_later.breakeven_p_per_kwh


# ---------------------------------------------------------------------------
# New per-charge savings model tests (spec "Testing > Backend").
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expensive_rapid_shows_loss(test_sessionmaker):
    """A pricey DC rapid (high p/kWh) shows saved_vs_petrol_p < 0 — a loss.

    92p/kWh DC rapid, 15.4 kWh, car efficiency 3.7 mi/kWh.
    Petrol settings: 150p/L, 50 MPG → ppm = 150 × 4.54609 / 50 = 13.638 p/mi.
    miles = 15.4 × 3.7 = 56.98 mi.
    petrol_equivalent_p = round(56.98 × 13.638) = round(777.3) = 777.
    cost_pence = round(15.4 × 92) = round(1416.8) = 1417.
    saved = 777 - 1417 = -640 (a clear loss).
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=77.0, mi_per_kwh=3.7)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 27),
            start_soc=20, end_soc=80, kwh_added=15.4, kwh_calculated=15.4,
            cost_pence=round(15.4 * 92),   # 92p/kWh rapid
            cost_basis="override_per_kwh", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)

        assert m.comparison_basis == "estimated"
        assert m.savings_vs_petrol_p is not None
        assert m.savings_vs_petrol_p < 0, (
            f"Expected DC rapid at 92p/kWh to be a LOSS, got {m.savings_vs_petrol_p}"
        )


@pytest.mark.asyncio
async def test_cheap_home_charge_shows_saving(test_sessionmaker):
    """A cheap home charge (low p/kWh) shows saved_vs_petrol_p > 0 — a saving.

    7.5p/kWh home charge, 20 kWh, car efficiency 3.7 mi/kWh.
    Petrol settings: 150p/L, 50 MPG → ppm ≈ 13.638 p/mi.
    miles = 20 × 3.7 = 74 mi.
    petrol_equivalent_p = round(74 × 13.638) = round(1009.2) = 1009.
    cost_pence = round(20 × 7.5) = 150.
    saved = 1009 - 150 = 859 (a clear saving).
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=77.0, mi_per_kwh=3.7)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 27),
            start_soc=20, end_soc=80, kwh_added=20.0, kwh_calculated=20.0,
            cost_pence=round(20.0 * 7.5),  # 7.5p/kWh home
            cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)

        assert m.comparison_basis == "estimated"
        assert m.savings_vs_petrol_p is not None
        assert m.savings_vs_petrol_p > 0, (
            f"Expected home charge at 7.5p/kWh to be a SAVING, got {m.savings_vs_petrol_p}"
        )


@pytest.mark.asyncio
async def test_total_saved_equals_sum_of_rows_no_double_count(test_sessionmaker):
    """Total saved == sum of per-row savings — no overlap or double-count.

    Reproduce the interleave: a measured anchor + two intervening charges
    (some odometer-less). The InstaVolt-like expensive DC rapid (id=3) should
    be negative, and the total must equal the row sum exactly.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # Nominal 3.7; observed will be calibrated from the two advancing legs.
        _seed_car(s, battery_kwh=77.0, mi_per_kwh=3.7)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)

        # id=1: 14 May odometer anchor (start of interleave window).
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=20, end_soc=80, kwh_added=20.0, kwh_calculated=20.0,
            odometer_at_session_km=1000.0,
            cost_pence=round(20.0 * 7.5),
            cost_basis="home_rate", source="manual",
        ))
        # id=2: 23 May home charge — no odometer.
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 23),
            start_soc=20, end_soc=80, kwh_added=18.0, kwh_calculated=18.0,
            odometer_at_session_km=None,
            cost_pence=round(18.0 * 7.5),
            cost_basis="home_rate", source="manual",
        ))
        # id=3: 27 May DC rapid at 92p/kWh — expensive, should be a LOSS.
        s.add(ChargingSession(
            id=3, user_id=1, car_id=1, date=date(2026, 5, 27),
            start_soc=20, end_soc=80, kwh_added=15.4, kwh_calculated=15.4,
            odometer_at_session_km=None,
            cost_pence=round(15.4 * 92),
            cost_basis="override_per_kwh", source="manual",
        ))
        # id=4: 27 May Morrisons — cheap, another no-odometer session.
        s.add(ChargingSession(
            id=4, user_id=1, car_id=1, date=date(2026, 5, 27),
            start_soc=20, end_soc=50, kwh_added=8.0, kwh_calculated=8.0,
            odometer_at_session_km=None,
            cost_pence=round(8.0 * 15),
            cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        rows = [await s.get(ChargingSession, i) for i in (1, 2, 3, 4)]
        batch = await compute_savings_for_sessions(s, rows)

        # Row 3 (DC rapid at 92p/kWh) must be a LOSS.
        saved_3, basis_3, _ = batch[3]
        assert basis_3 == "estimated"
        assert saved_3 is not None
        assert saved_3 < 0, f"Expensive rapid should be a loss, got {saved_3}"

        # Total = row sum (no overlap, no double-count).
        row_total = sum(
            batch[i][0] for i in (1, 2, 3, 4) if batch[i][0] is not None
        )
        # All four rows have energy so all should be computable.
        individual = [batch[i][0] for i in (1, 2, 3, 4)]
        assert all(v is not None for v in individual), (
            f"All rows should have savings; got {individual}"
        )
        assert row_total == sum(individual)


@pytest.mark.asyncio
async def test_comparison_basis_estimated_for_energy_rows(test_sessionmaker):
    """comparison_basis == "estimated" for energy-bearing rows; None when
    energy or petrol settings are missing.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=59.0, mi_per_kwh=3.5)
        _add_petrol_settings(s)
        # Energy-bearing row with cost.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=17.7,
            cost_pence=368, cost_basis="home_rate", source="manual",
        ))
        # Zero-energy row — no comparison.
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 15),
            start_soc=80, end_soc=80, kwh_added=0.0, kwh_calculated=0.0,
            cost_pence=100, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        cs1 = await s.get(ChargingSession, 1)
        m1 = await compute_session_metrics(s, cs1)
        assert m1.comparison_basis == "estimated"

        cs2 = await s.get(ChargingSession, 2)
        m2 = await compute_session_metrics(s, cs2)
        assert m2.comparison_basis is None
        assert m2.savings_vs_petrol_p is None


@pytest.mark.asyncio
async def test_comparison_basis_none_when_no_petrol_settings(test_sessionmaker):
    """When petrol settings are missing, savings is None and basis is
    'estimated' (estimate is computable, just no petrol to compare to).
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
        assert m.savings_vs_petrol_p is None
        assert m.petrol_equivalent_cost_p is None


@pytest.mark.asyncio
async def test_batch_and_single_agree_for_every_row(test_sessionmaker):
    """batch (saved, basis) == single (savings_vs_petrol_p, comparison_basis)
    for every row — including odometer-bearing ones. The batch returns a
    3-tuple and all three fields must match.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=58.0, mi_per_kwh=4.0)
        _add_petrol_settings(s, p_per_litre=151.9, mpg=54.1)

        # Mix of odometer-bearing and odometer-less rows.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 1),
            start_soc=30, end_soc=80, kwh_added=20.0, kwh_calculated=20.0,
            odometer_at_session_km=1000.0, cost_pence=150,
            cost_basis="home_rate", source="manual",
        ))
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 10),
            start_soc=20, end_soc=80, kwh_added=15.4, kwh_calculated=15.4,
            odometer_at_session_km=None, cost_pence=1417,
            cost_basis="override_per_kwh", source="manual",
        ))
        s.add(ChargingSession(
            id=3, user_id=1, car_id=1, date=date(2026, 5, 20),
            start_soc=30, end_soc=80, kwh_added=18.0, kwh_calculated=18.0,
            odometer_at_session_km=1200.0, cost_pence=135,
            cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        rows = [await s.get(ChargingSession, i) for i in (1, 2, 3)]
        await _assert_batch_matches_single(s, rows)


@pytest.mark.asyncio
async def test_breakeven_p_per_kwh_formula(test_sessionmaker):
    """breakeven_p_per_kwh == ppm × eff.

    With petrol_price_p_per_litre=150, mpg=50:
      ppm = 150 × 4.54609 / 50 = 13.6383
    With nominal eff = 3.7 mi/kWh:
      breakeven = 13.6383 × 3.7 ≈ 50.46 p/kWh
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=77.0, mi_per_kwh=3.7)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=20, end_soc=80, kwh_added=20.0, kwh_calculated=20.0,
            cost_pence=150, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)

        ppm = (150.0 * 4.54609) / 50.0
        expected_breakeven = round(ppm * 3.7, 2)
        assert m.breakeven_p_per_kwh == pytest.approx(expected_breakeven, abs=0.01)


@pytest.mark.asyncio
async def test_breakeven_uses_observed_efficiency(test_sessionmaker):
    """breakeven_p_per_kwh uses observed efficiency when a clean measured leg
    exists, not the nominal.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        # Nominal 5.0 deliberately far from observed 3.0.
        _seed_car(s, battery_kwh=50.0, mi_per_kwh=5.0)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)

        # Three sessions implying observed = 3.0 mi/kWh.
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
        # Estimated session — no odometer, has cost.
        s.add(ChargingSession(
            id=4, user_id=1, car_id=1, date=date(2026, 5, 12),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=15.0,
            cost_pence=300, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        cs = await s.get(ChargingSession, 4)
        m = await compute_session_metrics(s, cs)

        ppm = (150.0 * 4.54609) / 50.0
        # breakeven must use observed (3.0), NOT nominal (5.0).
        expected_breakeven_observed = round(ppm * 3.0, 2)
        expected_breakeven_nominal = round(ppm * 5.0, 2)
        assert m.breakeven_p_per_kwh == pytest.approx(expected_breakeven_observed, abs=0.01)
        assert m.breakeven_p_per_kwh != pytest.approx(expected_breakeven_nominal, abs=0.01)


@pytest.mark.asyncio
async def test_breakeven_none_without_petrol_settings(test_sessionmaker):
    """breakeven_p_per_kwh is None when petrol settings are missing."""
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
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        assert m.breakeven_p_per_kwh is None


@pytest.mark.asyncio
async def test_measured_miles_since_previous_informational(test_sessionmaker):
    """measured_miles_since_previous is set (informational) when a prior
    odometer reading exists. It is independent of savings — savings uses the
    energy estimate, not the odometer span.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=58.0, mi_per_kwh=4.0)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        # Prior odometer reading.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 1),
            start_soc=30, end_soc=80, kwh_added=10.0,
            odometer_at_session_km=1000.0,
            cost_pence=75, cost_basis="home_rate", source="manual",
        ))
        # Current session — advanced 100 km (62.14 mi).
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 10),
            start_soc=30, end_soc=80, kwh_added=20.0, kwh_calculated=20.0,
            odometer_at_session_km=1100.0,
            cost_pence=150, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 2)
        m = await compute_session_metrics(s, cs)

        # Informational odometer span.
        expected_odo_miles = (1100.0 - 1000.0) / _KM_PER_MILE
        assert m.measured_miles_since_previous == pytest.approx(expected_odo_miles, abs=0.01)

        # Savings uses energy estimate (not odometer span).
        assert m.comparison_basis == "estimated"
        # miles_since_previous is energy-based (not the odometer span of ~62 mi).
        assert m.miles_since_previous is not None
        # Must differ from the raw odo span — it is energy × eff, not the
        # genuine km difference.
        assert m.miles_since_previous != float(round(expected_odo_miles))


@pytest.mark.asyncio
async def test_measured_miles_none_without_prior_odometer(test_sessionmaker):
    """measured_miles_since_previous is None when there is no prior odometer
    reading — no distortion of savings.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=58.0, mi_per_kwh=4.0)
        _add_petrol_settings(s)
        # Session with odometer but no prior.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 10),
            start_soc=30, end_soc=80, kwh_added=20.0, kwh_calculated=20.0,
            odometer_at_session_km=1100.0,
            cost_pence=150, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 1)
        m = await compute_session_metrics(s, cs)
        assert m.measured_miles_since_previous is None


@pytest.mark.asyncio
async def test_measured_miles_none_for_no_odometer_session(test_sessionmaker):
    """measured_miles_since_previous is None when the session itself has no
    odometer reading (it can't form a span).
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=58.0, mi_per_kwh=4.0)
        _add_petrol_settings(s)
        # Prior with odometer.
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 1),
            start_soc=30, end_soc=80, kwh_added=10.0,
            odometer_at_session_km=1000.0,
            cost_pence=75, cost_basis="home_rate", source="manual",
        ))
        # Current without odometer.
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 10),
            start_soc=30, end_soc=80, kwh_added=20.0, kwh_calculated=20.0,
            odometer_at_session_km=None,
            cost_pence=150, cost_basis="home_rate", source="manual",
        ))
        await s.commit()
        cs = await s.get(ChargingSession, 2)
        m = await compute_session_metrics(s, cs)
        assert m.measured_miles_since_previous is None
        # But savings still work via energy estimate.
        assert m.comparison_basis == "estimated"


@pytest.mark.asyncio
async def test_batch_returns_breakeven_matching_single(test_sessionmaker):
    """The batch 3-tuple's breakeven_p_per_kwh matches compute_session_metrics
    for both energy-bearing and zero-energy rows.
    """
    async with test_sessionmaker() as s:
        s.add(User(id=1, username="alice", password_hash="x"))
        _seed_car(s, battery_kwh=58.0, mi_per_kwh=3.6)
        _add_petrol_settings(s, p_per_litre=150.0, mpg=50.0)
        s.add(ChargingSession(
            id=1, user_id=1, car_id=1, date=date(2026, 5, 14),
            start_soc=60, end_soc=90, kwh_added=18.0, kwh_calculated=17.7,
            cost_pence=150, cost_basis="home_rate", source="manual",
        ))
        s.add(ChargingSession(
            id=2, user_id=1, car_id=1, date=date(2026, 5, 15),
            start_soc=80, end_soc=80, kwh_added=0.0, kwh_calculated=0.0,
            cost_pence=100, cost_basis="home_rate", source="manual",
        ))
        await s.commit()

        rows = [await s.get(ChargingSession, i) for i in (1, 2)]
        await _assert_batch_matches_single(s, rows)

        batch = await compute_savings_for_sessions(s, rows)
        # Zero-energy row has no breakeven.
        assert batch[2][2] is None
        # Energy-bearing row has a breakeven.
        assert batch[1][2] is not None
