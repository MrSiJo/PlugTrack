"""Tests for the extracted cost_apply service (spec §cost-freezing invariant).

Verifies three paths:
  1. kWh edit on a rate-derived session re-scales at the FROZEN tariff
     (cost = round(kwh * tariff), basis unchanged).
  2. Setting cost_per_kwh_override_p (override_changed=True) flips basis
     to 'override_per_kwh' via the normal precedence rule.
  3. first_compute=True (new session) derives via the cost-precedence rule.
"""

from __future__ import annotations

from datetime import date

import pytest
from plugtrack.models import ChargingSession, Setting
from plugtrack.models.car import Car
from plugtrack.models.user import User

# Setting is imported here for type clarity; actual seeding uses seed_defaults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_user_car(sm):
    async with sm() as s:
        user = User(username="tester", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        car = Car(
            user_id=user.id,
            make="Test",
            model="Car",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return user.id, car.id


async def _seed_home_rate(sm, rate: float):
    """Seed all default settings then update the home rate to the given value."""
    from plugtrack.settings.seeds import seed_defaults
    from sqlalchemy import select as sa_select

    async with sm() as s:
        await seed_defaults(s)
        await s.commit()

    async with sm() as s:
        result = await s.execute(
            sa_select(Setting).where(Setting.key == "default_home_rate_p_per_kwh")
        )
        row = result.scalar_one()
        row.value = str(rate)
        await s.commit()


def _make_session(user_id, car_id, **kwargs) -> ChargingSession:
    defaults = dict(
        user_id=user_id,
        car_id=car_id,
        date=date(2026, 6, 1),
        start_soc=20,
        end_soc=80,
        kwh_added=10.0,
        charging_type="ac",
        charging_mode="manual",
        source="manual",
        cost_pence=75,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
    )
    defaults.update(kwargs)
    return ChargingSession(**defaults)


# ---------------------------------------------------------------------------
# Test 1: kWh edit on a home_rate session → re-scales at FROZEN tariff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kwh_edit_rescales_at_frozen_tariff(test_sessionmaker, seeded_user_car):
    """On a kWh-only edit of a rate-derived session, cost is re-scaled
    at the stored tariff_p_per_kwh, not re-derived from settings.
    """
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    # Seed a home rate that differs from the frozen tariff so we can confirm
    # the service uses the frozen one.
    await _seed_home_rate(test_sessionmaker, rate=15.0)  # different from frozen 7.5

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=20.0,  # edited: was 10 kWh, now 20 kWh
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,  # frozen tariff (from when session was created)
        cost_pence=75,  # old cost (10 * 7.5)
    )

    async with test_sessionmaker() as session:
        await apply_cost(
            session,
            cs,
            first_compute=False,
            override_changed=False,
        )

    # Should re-scale at frozen 7.5, NOT the current settings rate of 15.0
    assert cs.cost_pence == round(20.0 * 7.5)  # 150
    assert cs.cost_basis == "home_rate"  # basis unchanged
    assert cs.tariff_p_per_kwh == 7.5  # tariff unchanged


@pytest.mark.asyncio
async def test_location_rate_edit_rescales_at_frozen_tariff(test_sessionmaker, seeded_user_car):
    """location_rate basis also re-scales at frozen tariff on kWh edit."""
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker, rate=7.5)

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=15.0,
        cost_basis="location_rate",
        tariff_p_per_kwh=12.5,  # frozen location rate
        cost_pence=125,
    )

    async with test_sessionmaker() as session:
        await apply_cost(session, cs, first_compute=False, override_changed=False)

    assert cs.cost_pence == round(15.0 * 12.5)  # 188
    assert cs.cost_basis == "location_rate"
    assert cs.tariff_p_per_kwh == 12.5


@pytest.mark.asyncio
async def test_location_free_edit_rescales_at_frozen_tariff(test_sessionmaker, seeded_user_car):
    """location_free basis also re-scales at frozen tariff (0) on kWh edit."""
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker, rate=7.5)

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=20.0,
        cost_basis="location_free",
        tariff_p_per_kwh=0.0,
        cost_pence=0,
    )

    async with test_sessionmaker() as session:
        await apply_cost(session, cs, first_compute=False, override_changed=False)

    assert cs.cost_pence == 0
    assert cs.cost_basis == "location_free"


# ---------------------------------------------------------------------------
# Test 2: setting cost_per_kwh_override_p (override_changed=True)
#         → flips basis to 'override_per_kwh' via precedence rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_changed_flips_to_override_per_kwh(test_sessionmaker, seeded_user_car):
    """When override_changed=True the frozen-tariff re-scale is bypassed
    and the normal cost-precedence rule runs, yielding 'override_per_kwh'.
    """
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker, rate=7.5)

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=10.0,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
        cost_pence=75,
        cost_per_kwh_override_p=25.0,  # user just set this override
    )

    async with test_sessionmaker() as session:
        await apply_cost(
            session,
            cs,
            first_compute=False,
            override_changed=True,  # the override field changed
        )

    assert cs.cost_basis == "override_per_kwh"
    assert cs.tariff_p_per_kwh == 25.0
    assert cs.cost_pence == round(10.0 * 25.0)  # 250


@pytest.mark.asyncio
async def test_total_override_changed_sets_override_total(test_sessionmaker, seeded_user_car):
    """total_cost_pence_override change → override_total basis."""
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker, rate=7.5)

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=10.0,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
        cost_pence=75,
        total_cost_pence_override=500,  # user set a total override
    )

    async with test_sessionmaker() as session:
        await apply_cost(session, cs, first_compute=False, override_changed=True)

    assert cs.cost_basis == "override_total"
    assert cs.cost_pence == 500


# ---------------------------------------------------------------------------
# Test 3: first_compute=True (new session) → derives via precedence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_compute_uses_home_rate_from_settings(test_sessionmaker, seeded_user_car):
    """On first compute (new session), cost is derived from the settings
    home rate — no frozen tariff exists yet.
    """
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker, rate=7.5)

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=20.0,
        cost_basis="unknown",
        tariff_p_per_kwh=None,
        cost_pence=None,
    )

    async with test_sessionmaker() as session:
        await apply_cost(session, cs, first_compute=True, override_changed=False)

    assert cs.cost_basis == "home_rate"
    assert cs.tariff_p_per_kwh == 7.5
    assert cs.cost_pence == round(20.0 * 7.5)  # 150


@pytest.mark.asyncio
async def test_first_compute_with_per_kwh_override(test_sessionmaker, seeded_user_car):
    """first_compute with an override set → override_per_kwh basis."""
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker, rate=7.5)

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=10.0,
        cost_basis="unknown",
        tariff_p_per_kwh=None,
        cost_pence=None,
        cost_per_kwh_override_p=79.0,
    )

    async with test_sessionmaker() as session:
        await apply_cost(session, cs, first_compute=True, override_changed=False)

    assert cs.cost_basis == "override_per_kwh"
    assert cs.tariff_p_per_kwh == 79.0
    assert cs.cost_pence == round(10.0 * 79.0)  # 790


# ---------------------------------------------------------------------------
# Test 4: override_basis session (override_per_kwh) re-derives on edit
#         (not rate-derived, so frozen-tariff path is NOT taken)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_basis_session_rederives_on_kwh_edit(test_sessionmaker, seeded_user_car):
    """A session with override_per_kwh basis is NOT rate-derived,
    so it re-derives via precedence even when override_changed=False.
    This means changing kWh on an override session updates the cost
    using the stored override rate via the precedence rule.
    """
    from plugtrack.services.cost_apply import apply_cost

    user_id, car_id = seeded_user_car
    await _seed_home_rate(test_sessionmaker, rate=7.5)

    cs = _make_session(
        user_id,
        car_id,
        kwh_added=20.0,
        cost_basis="override_per_kwh",
        tariff_p_per_kwh=25.0,
        cost_pence=250,  # was 10 * 25
        cost_per_kwh_override_p=25.0,  # the override is still set
    )

    async with test_sessionmaker() as session:
        await apply_cost(session, cs, first_compute=False, override_changed=False)

    # override_per_kwh is NOT rate_derived → re-derives via precedence
    assert cs.cost_basis == "override_per_kwh"
    assert cs.cost_pence == round(20.0 * 25.0)  # 500
