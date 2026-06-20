"""TDD tests for two bugs in charge_planner.py.

Bug 1 — home-actual power uses wall-clock instead of actual_charge_seconds:
  resolve_plan_inputs computes effective_kw as kwh_added / wall_clock_hours.
  For overnight granny charges with long idle tail, actual_charge_seconds gives
  the correct energy-transfer duration and must be preferred when set and > 0.

Bug 2 — AC scenario rows (7 kW, 11 kW) wrongly capped by observed home granny power:
  The ac_ceiling_kw derived from max(effective_kws) (the observed home granny rate)
  is used to cap the fixed "7 kW" and "11 kW" hypothetical-charger scenario rows.
  Those rows represent plugging into a 7/11 kW EVSE and must only be capped by
  car.max_ac_kw (or uncapped when that is None).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio

from plugtrack.services.charge_planner import (
    build_scenario_table,
    build_dc_capability,
    DcSession,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AC_WINDOW = {
    "window_minutes": 450,
    "window_start_str": "23:45",
    "home_rate_p_per_kwh": 7.5,
    "is_free": False,
}


def _empty_dc(ceiling: float = 150.0) -> dict:
    cap = build_dc_capability(battery_kwh=77.0, dc_sessions=[], max_dc_kw=ceiling)
    return {"capability": cap, "ceiling": ceiling}


# ---------------------------------------------------------------------------
# Bug 1 — DB fixture: home AC sessions with short actual_charge_seconds
#          but long wall-clock window
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def granny_sessions_db(test_sessionmaker):
    """Seed: user + car + home location + 5 home AC sessions.

    Each session has:
      - kwh_added = 8.0
      - actual_charge_seconds = 3600  (1 hour  → effective 8.0 kW)
      - wall-clock window = 8 hours   (big idle tail → wall-clock effective ~1.0 kW)

    The test asserts that resolve_plan_inputs returns ~8 kW (actual), NOT ~1 kW (wall).
    """
    from plugtrack.models import Car, ChargingSession, Location, User

    async with test_sessionmaker() as s:
        user = User(username="granny_test_user", password_hash="x")
        s.add(user)
        await s.flush()

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
            max_ac_kw=None,
            max_dc_kw=100.0,
        )
        s.add(car)
        await s.flush()

        home = Location(
            user_id=user.id,
            centroid_lat=51.5,
            centroid_lng=-0.1,
            is_home=True,
            is_free=False,
            default_cost_per_kwh_p=28.0,
        )
        s.add(home)
        await s.flush()

        for day_offset in range(5):
            # Wall-clock = 8 hours (plug-in to plug-out including idle)
            wall_start = datetime(2026, 1, 10 + day_offset, 22, 0, tzinfo=timezone.utc)
            wall_end = wall_start + timedelta(hours=8)  # 8-hour plug-in window

            cs = ChargingSession(
                user_id=user.id,
                car_id=car.id,
                date=date(2026, 1, 10 + day_offset),
                charging_type="ac",
                start_soc=30,
                end_soc=44,
                kwh_added=8.0,
                charge_start_at=wall_start,
                charge_end_at=wall_end,
                actual_charge_seconds=3600,  # only 1 hour actually charging
                source="manual",
                cost_basis="unknown",
                location_id=home.id,
            )
            s.add(cs)

        await s.commit()
        await s.refresh(user)
        await s.refresh(car)
        return user.id, car.id


@pytest.mark.asyncio
class TestBug1HomeActualUsesActualChargeSeconds:
    """Bug 1: home-actual power must be derived from actual_charge_seconds, not wall-clock."""

    async def test_wall_clock_based_power_is_low(self, test_sessionmaker, granny_sessions_db):
        """Baseline: if we used wall-clock hours the result would be ~1 kW.

        8 kWh / 8 hours = 1.0 kW (the bug).
        We assert that the resolved power is NOT near 1.0 kW — it must be near 8.0 kW.
        """
        user_id, car_id = granny_sessions_db
        from plugtrack.models import Car
        from plugtrack.services.charge_planner import resolve_plan_inputs

        async with test_sessionmaker() as s:
            car = await s.get(Car, car_id)
            inputs = await resolve_plan_inputs(s, car, user_id)

        # Bug: wall-clock gives ~1.0 kW.  Fix: actual_charge_seconds gives ~8.0 kW.
        assert inputs.power_basis == "history", (
            f"Expected 'history' but got '{inputs.power_basis}' — "
            "not enough sessions found; check fixture."
        )
        # With the fix: median of [8.0, 8.0, 8.0, 8.0, 8.0] = 8.0 kW
        # Without the fix: median of [1.0, 1.0, 1.0, 1.0, 1.0] = 1.0 kW
        assert inputs.power_kw >= 6.0, (
            f"power_kw={inputs.power_kw:.2f} kW — expected ~8.0 kW (actual_charge_seconds). "
            f"Wall-clock would give ~1.0 kW. Bug 1 is not fixed."
        )

    async def test_power_reflects_actual_charge_seconds_not_wall_clock(
        self, test_sessionmaker, granny_sessions_db
    ):
        """Concrete assertion: power_kw ≈ kwh / actual_hours ≈ 8 kW."""
        user_id, car_id = granny_sessions_db
        from plugtrack.models import Car
        from plugtrack.services.charge_planner import resolve_plan_inputs

        async with test_sessionmaker() as s:
            car = await s.get(Car, car_id)
            inputs = await resolve_plan_inputs(s, car, user_id)

        # 8 kWh / (3600 s / 3600) h = 8.0 kW — the correct actual rate
        assert inputs.power_kw == pytest.approx(8.0, abs=0.2), (
            f"power_kw={inputs.power_kw:.2f} kW; expected ~8.0 kW (kwh/actual_charge_h). "
            f"Bug 1: wall-clock hours used instead of actual_charge_seconds."
        )

    async def test_fallback_to_wall_clock_when_actual_charge_seconds_null(
        self, test_sessionmaker
    ):
        """When actual_charge_seconds is NULL, fall back to wall-clock hours."""
        from plugtrack.models import Car, ChargingSession, Location, User

        async with test_sessionmaker() as s:
            user = User(username="no_actual_user", password_hash="x")
            s.add(user)
            await s.flush()

            car = Car(
                user_id=user.id,
                make="VW",
                model="ID.3",
                battery_kwh=58.0,
                nominal_efficiency_mi_per_kwh=4.0,
                provider="manual",
                active=True,
                max_ac_kw=None,
                max_dc_kw=None,
            )
            s.add(car)
            await s.flush()

            home = Location(
                user_id=user.id,
                centroid_lat=51.5,
                centroid_lng=-0.1,
                is_home=True,
                is_free=False,
            )
            s.add(home)
            await s.flush()

            # 3 sessions: no actual_charge_seconds, wall-clock = 2 h → ~7 kW
            for day_offset in range(3):
                wall_start = datetime(
                    2026, 3, 1 + day_offset, 22, 0, tzinfo=timezone.utc
                )
                wall_end = wall_start + timedelta(hours=2)  # 2-hour wall-clock
                cs = ChargingSession(
                    user_id=user.id,
                    car_id=car.id,
                    date=date(2026, 3, 1 + day_offset),
                    charging_type="ac",
                    start_soc=20,
                    end_soc=44,
                    kwh_added=14.0,
                    charge_start_at=wall_start,
                    charge_end_at=wall_end,
                    actual_charge_seconds=None,  # NULL → must fall back to wall-clock
                    source="manual",
                    cost_basis="unknown",
                    location_id=home.id,
                )
                s.add(cs)

            await s.commit()
            await s.refresh(car)
            user_id = user.id
            car_obj = car

        from plugtrack.services.charge_planner import resolve_plan_inputs

        async with test_sessionmaker() as s:
            car_reloaded = await s.get(Car, car_obj.id)
            inputs = await resolve_plan_inputs(s, car_reloaded, user_id)

        # Fallback: 14 kWh / 2 h = 7.0 kW
        assert inputs.power_kw == pytest.approx(7.0, abs=0.2), (
            f"power_kw={inputs.power_kw:.2f}; expected ~7.0 kW (wall-clock fallback). "
            "Fallback to wall_clock when actual_charge_seconds is NULL is broken."
        )


# ---------------------------------------------------------------------------
# Bug 2 — AC scenario rows capped by observed home granny power, not car onboard
# ---------------------------------------------------------------------------


class TestBug2ACRowsCappedByCarOnboardNotHomeGranny:
    """Bug 2: 7 kW / 11 kW scenario rows must NOT be capped by observed home granny power.

    When car.max_ac_kw is None, the AC ceiling for fixed scenario rows must be
    uncapped (each row uses its nominal kW directly, not min(nominal, granny_observed)).

    When car.max_ac_kw is set, it caps all AC rows (including fixed ones).
    """

    def _ac_dict_with_granny_observed(
        self,
        observed_kw: float,
        max_ac_kw: Optional[float],
    ) -> dict:
        """Build the ac dict as resolve_plan_inputs would produce it.

        home_actual_kw = observed_kw (the granny rate).
        ac_ceiling_kw = max_ac_kw if set, else observed_kw (the BUG) or None (the FIX).
        """
        return {
            "home_actual_kw": observed_kw,
            "ac_ceiling_kw": max_ac_kw if max_ac_kw is not None else observed_kw,
            **_AC_WINDOW,
        }

    def _ac_dict_fixed(
        self,
        home_actual_kw: float,
        max_ac_kw: Optional[float],
    ) -> dict:
        """Build the ac dict as it should look AFTER the fix.

        ac_ceiling_kw = max_ac_kw if set, else None (meaning uncapped for fixed rows).
        """
        return {
            "home_actual_kw": home_actual_kw,
            "ac_ceiling_kw": max_ac_kw,  # None means uncapped
            **_AC_WINDOW,
        }

    def test_7kw_row_not_capped_by_granny_when_max_ac_kw_none(self):
        """With max_ac_kw=None and observed granny ~2.3 kW, '7 kW' row power must be ~7 kW.

        This test calls build_scenario_table with the FIXED ac dict (ac_ceiling_kw=None)
        to verify that a None ceiling means uncapped.
        """
        ac = self._ac_dict_fixed(home_actual_kw=2.3, max_ac_kw=None)
        table = build_scenario_table(
            start_soc=20, target_soc=80, battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac, dc=_empty_dc(), custom_kw=None,
        )
        row_7 = next(r for r in table if r.label == "7 kW")
        # Without the fix (ac_ceiling_kw=2.3): power_kw = min(7, 2.3) = 2.3 kW
        # With the fix (ac_ceiling_kw=None): power_kw = 7.0 kW
        assert row_7.power_kw == pytest.approx(7.0, abs=0.1), (
            f"'7 kW' row power_kw={row_7.power_kw:.2f}; expected ~7.0 kW when "
            f"max_ac_kw=None. Bug 2: capped by observed home power instead."
        )

    def test_11kw_row_not_capped_by_granny_when_max_ac_kw_none(self):
        """With max_ac_kw=None and observed granny ~2.3 kW, '11 kW' row power must be ~11 kW."""
        ac = self._ac_dict_fixed(home_actual_kw=2.3, max_ac_kw=None)
        table = build_scenario_table(
            start_soc=20, target_soc=80, battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac, dc=_empty_dc(), custom_kw=None,
        )
        row_11 = next(r for r in table if r.label == "11 kW")
        assert row_11.power_kw == pytest.approx(11.0, abs=0.1), (
            f"'11 kW' row power_kw={row_11.power_kw:.2f}; expected ~11.0 kW when "
            f"max_ac_kw=None. Bug 2: capped by observed home power instead."
        )

    def test_home_actual_row_shows_granny_power_not_capped(self):
        """'Your home (actual)' row must show the observed granny power (~2.3 kW)."""
        ac = self._ac_dict_fixed(home_actual_kw=2.3, max_ac_kw=None)
        table = build_scenario_table(
            start_soc=20, target_soc=80, battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac, dc=_empty_dc(), custom_kw=None,
        )
        home_row = next(r for r in table if r.label == "Your home (actual)")
        assert home_row.power_kw == pytest.approx(2.3, abs=0.1), (
            f"'Your home (actual)' power_kw={home_row.power_kw:.2f}; expected ~2.3 kW."
        )

    def test_11kw_row_capped_at_max_ac_kw_when_set(self):
        """When car.max_ac_kw=7.4, '11 kW' row must cap at 7.4 kW."""
        ac = self._ac_dict_fixed(home_actual_kw=2.3, max_ac_kw=7.4)
        table = build_scenario_table(
            start_soc=20, target_soc=80, battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac, dc=_empty_dc(), custom_kw=None,
        )
        row_11 = next(r for r in table if r.label == "11 kW")
        assert row_11.power_kw == pytest.approx(7.4, abs=0.1), (
            f"'11 kW' row power_kw={row_11.power_kw:.2f}; expected 7.4 kW (car.max_ac_kw)."
        )

    def test_7kw_row_not_capped_when_max_ac_kw_above_7(self):
        """When car.max_ac_kw=11.0, '7 kW' row must remain at 7.0 kW (not capped)."""
        ac = self._ac_dict_fixed(home_actual_kw=2.3, max_ac_kw=11.0)
        table = build_scenario_table(
            start_soc=20, target_soc=80, battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac, dc=_empty_dc(), custom_kw=None,
        )
        row_7 = next(r for r in table if r.label == "7 kW")
        assert row_7.power_kw == pytest.approx(7.0, abs=0.1), (
            f"'7 kW' row power_kw={row_7.power_kw:.2f}; expected 7.0 kW (under car max)."
        )

    def test_home_actual_capped_by_max_ac_kw_when_set_and_lower(self):
        """If car.max_ac_kw < home_actual_kw, the home-actual row must be capped."""
        # Unusual scenario: car can only do 2.0 kW AC but observed 2.3 kW
        # (data artefact). Should cap at car.max_ac_kw.
        ac = self._ac_dict_fixed(home_actual_kw=2.3, max_ac_kw=2.0)
        table = build_scenario_table(
            start_soc=20, target_soc=80, battery_kwh=77.0,
            loss_factor=1.0,
            ac=ac, dc=_empty_dc(), custom_kw=None,
        )
        home_row = next(r for r in table if r.label == "Your home (actual)")
        assert home_row.power_kw <= 2.0 + 0.1, (
            f"'Your home (actual)' power_kw={home_row.power_kw:.2f}; "
            f"expected ≤ 2.0 kW (capped by car.max_ac_kw=2.0)."
        )


# ---------------------------------------------------------------------------
# Bug 2 — Integration: verify resolve_plan_inputs emits correct ac_ceiling_kw
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def granny_no_max_ac_db(test_sessionmaker):
    """Seed: car with max_ac_kw=None and 3 home AC sessions at ~2.3 kW (wall-clock).

    Wall-clock: 8 kWh / 3.5 h ≈ 2.29 kW.
    actual_charge_seconds is None so wall-clock is used for the power derivation.

    Before Bug 2 fix: ac_ceiling_kw = observed_ac_max ≈ 2.3 kW → caps 7/11 kW rows.
    After Bug 2 fix:  ac_ceiling_kw = None (no cap) → 7/11 kW rows show nominal.
    """
    from plugtrack.models import Car, ChargingSession, Location, User

    async with test_sessionmaker() as s:
        user = User(username="granny_no_max_ac", password_hash="x")
        s.add(user)
        await s.flush()

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
            max_ac_kw=None,  # ← no onboard AC cap known
            max_dc_kw=100.0,
        )
        s.add(car)
        await s.flush()

        home = Location(
            user_id=user.id,
            centroid_lat=51.5,
            centroid_lng=-0.1,
            is_home=True,
            is_free=False,
            default_cost_per_kwh_p=28.0,
        )
        s.add(home)
        await s.flush()

        # 3 sessions: 8 kWh / 3.5 hours ≈ 2.29 kW wall-clock effective
        for day_offset in range(3):
            wall_start = datetime(2026, 2, 1 + day_offset, 22, 0, tzinfo=timezone.utc)
            wall_end = wall_start + timedelta(hours=3, minutes=30)
            cs = ChargingSession(
                user_id=user.id,
                car_id=car.id,
                date=date(2026, 2, 1 + day_offset),
                charging_type="ac",
                start_soc=20,
                end_soc=34,
                kwh_added=8.0,
                charge_start_at=wall_start,
                charge_end_at=wall_end,
                actual_charge_seconds=None,
                source="manual",
                cost_basis="unknown",
                location_id=home.id,
            )
            s.add(cs)

        await s.commit()
        await s.refresh(car)
        return user.id, car.id


@pytest.mark.asyncio
class TestBug2IntegrationViaResolveInputs:
    """Verify that resolve_plan_inputs sets ac_ceiling_kw=None when max_ac_kw=None."""

    async def test_ac_ceiling_kw_is_none_when_max_ac_kw_none(
        self, test_sessionmaker, granny_no_max_ac_db
    ):
        """After fix: ac_ceiling_kw must be None (not the observed granny rate)."""
        user_id, car_id = granny_no_max_ac_db
        from plugtrack.models import Car
        from plugtrack.services.charge_planner import resolve_plan_inputs

        async with test_sessionmaker() as s:
            car = await s.get(Car, car_id)
            inputs = await resolve_plan_inputs(s, car, user_id)

        # Before fix: ac_ceiling_kw ≈ 2.3 (observed_ac_max)
        # After fix:  ac_ceiling_kw is None
        assert inputs.ac_ceiling_kw is None, (
            f"ac_ceiling_kw={inputs.ac_ceiling_kw}; expected None when max_ac_kw=None. "
            f"Bug 2: observed home power used as AC ceiling instead of None."
        )
