"""API tests for GET /api/charge-plan — scenario-table endpoint.

Uses the authed_client fixture (from tests/api/conftest.py) which gives
a live app with a seeded settings table and a signed session cookie.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from plugtrack.models import Car, ChargingSession, Location, User
from tests.api.conftest import csrf_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_car(
    client,
    battery_kwh: float = 77.0,
    max_ac_kw: float | None = None,
    max_dc_kw: float | None = None,
) -> int:
    payload: dict = {
        "make": "Cupra",
        "model": "Born",
        "battery_kwh": battery_kwh,
        "nominal_efficiency_mi_per_kwh": 3.6,
    }
    if max_ac_kw is not None:
        payload["max_ac_kw"] = max_ac_kw
    if max_dc_kw is not None:
        payload["max_dc_kw"] = max_dc_kw

    r = await client.post(
        "/api/cars",
        json=payload,
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _get_user_id(test_sessionmaker) -> int:
    async with test_sessionmaker() as session:
        row = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        return row.id


async def _make_home_location(
    test_sessionmaker,
    user_id: int,
    *,
    is_free: bool = False,
    default_cost_per_kwh_p: float | None = None,
) -> int:
    async with test_sessionmaker() as session:
        loc = Location(
            user_id=user_id,
            name="Home",
            centroid_lat=50.85,
            centroid_lng=-0.13,
            radius_m=100,
            is_home=True,
            is_free=is_free,
            default_cost_per_kwh_p=default_cost_per_kwh_p,
        )
        session.add(loc)
        await session.commit()
        await session.refresh(loc)
        return loc.id


async def _make_ac_session(
    test_sessionmaker,
    user_id: int,
    car_id: int,
    location_id: int,
    kwh_added: float,
    duration_hours: float,
    days_ago: int = 0,
) -> None:
    """Insert a home AC charging session directly into the DB."""
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    start = now - timedelta(hours=duration_hours)
    async with test_sessionmaker() as session:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            location_id=location_id,
            date=now.date(),
            charge_start_at=start,
            charge_end_at=now,
            start_soc=20,
            end_soc=80,
            kwh_added=kwh_added,
            charging_type="ac",
            charging_mode="timer",
            source="synthesis",
            interrupted=False,
            cost_pence=None,
            cost_basis="unknown",
        )
        session.add(cs)
        await session.commit()


async def _make_dc_session(
    test_sessionmaker,
    user_id: int,
    car_id: int,
    *,
    start_soc: int = 20,
    end_soc: int = 80,
    kwh_added: float = 40.0,
    actual_charge_seconds: int | None = 1800,
    wall_seconds: int | None = 1900,
    power_curve: list | None = None,
    days_ago: int = 1,
) -> None:
    """Insert a DC charging session directly into the DB."""
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    start_dt = now - timedelta(seconds=wall_seconds or 1800)
    async with test_sessionmaker() as session:
        cs = ChargingSession(
            user_id=user_id,
            car_id=car_id,
            date=now.date(),
            charge_start_at=start_dt,
            charge_end_at=now,
            start_soc=start_soc,
            end_soc=end_soc,
            kwh_added=kwh_added,
            actual_charge_seconds=actual_charge_seconds,
            charging_type="dc",
            charging_mode="manual",
            source="synthesis",
            interrupted=False,
            cost_pence=None,
            cost_basis="unknown",
            power_curve=power_curve,
        )
        session.add(cs)
        await session.commit()


# ---------------------------------------------------------------------------
# Shared assertion helpers
# ---------------------------------------------------------------------------

REQUIRED_ROW_FIELDS = {"label", "power_kw", "minutes", "source_tag"}
VALID_SOURCE_TAGS = {"curve", "average", "modelled", "history", "spec"}


def _assert_valid_row(row: dict) -> None:
    """Assert that a scenario row has the expected shape."""
    for f in REQUIRED_ROW_FIELDS:
        assert f in row, f"Missing field {f!r} in row {row}"
    assert isinstance(row["power_kw"], (int, float)) and row["power_kw"] > 0
    assert isinstance(row["minutes"], int) and row["minutes"] > 0
    assert row["source_tag"], f"source_tag must be non-empty, got {row['source_tag']!r} in row {row}"
    assert row["source_tag"] in VALID_SOURCE_TAGS, f"Unexpected source_tag: {row['source_tag']!r}"


# ---------------------------------------------------------------------------
# Auth test (unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_plan_requires_auth(seeded_client):
    r = await seeded_client.get("/api/charge-plan?car_id=1&start_soc=20&target_soc=80")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Happy-path: scenario table shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_plan_returns_scenario_table(authed_client):
    """Happy-path: returns new scenario table contract with 'rows' list."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level envelope fields.
    assert body["car_id"] == car_id
    assert body["start_soc"] == 20
    assert body["target_soc"] == 80
    assert body["battery_kwh"] == 77.0
    assert isinstance(body["loss_factor"], float)
    assert 0 < body["loss_factor"] <= 1.0
    assert isinstance(body["home_rate_p_per_kwh"], float)
    assert isinstance(body["is_free"], bool)

    # 'rows' field.
    assert "rows" in body
    rows = body["rows"]
    assert isinstance(rows, list)
    # Default (no custom_kw): 3 AC + 3 DC = at least 6 rows.
    assert len(rows) >= 6, f"Expected at least 6 rows, got {len(rows)}: {[r['label'] for r in rows]}"

    # All rows must have the expected shape.
    for row in rows:
        _assert_valid_row(row)

    # Check fixed labels in order.
    labels = [r["label"] for r in rows]
    assert labels == ["Your home (actual)", "7 kW", "11 kW", "50 kW", "150 kW", "Car max"]


@pytest.mark.asyncio
async def test_charge_plan_with_custom_kw(authed_client):
    """custom_kw=120 adds a 7th 'Custom kW' row."""
    car_id = await _create_car(authed_client, battery_kwh=77.0, max_dc_kw=135.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80&custom_kw=120"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["rows"]
    assert len(rows) == 7
    custom_row = rows[-1]
    assert custom_row["label"] == "Custom kW"
    _assert_valid_row(custom_row)
    # No note when custom_kw < car max.
    assert custom_row.get("note") is None


@pytest.mark.asyncio
async def test_charge_plan_custom_kw_above_car_max(authed_client):
    """When custom_kw > car max, row note mentions car limit."""
    car_id = await _create_car(authed_client, battery_kwh=77.0, max_dc_kw=100.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80&custom_kw=200"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["rows"]
    custom_row = rows[-1]
    assert custom_row["label"] == "Custom kW"
    # Should carry a note about car limitation.
    assert custom_row.get("note") is not None
    assert "car" in custom_row["note"].lower() or "limited" in custom_row["note"].lower()


# ---------------------------------------------------------------------------
# AC home-actual row reflects seeded AC session median
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_home_actual_row_reflects_ac_session_median(authed_client, test_sessionmaker):
    """'Your home (actual)' power_kw reflects median of seeded home AC sessions."""
    # Three sessions each delivering exactly 7.0 kW effective.
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    user_id = await _get_user_id(test_sessionmaker)
    home_loc_id = await _make_home_location(test_sessionmaker, user_id)

    for i in range(3):
        await _make_ac_session(
            test_sessionmaker,
            user_id,
            car_id,
            home_loc_id,
            kwh_added=14.0,
            duration_hours=2.0,  # → 7.0 kW effective
            days_ago=i,
        )

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["rows"]
    home_row = rows[0]
    assert home_row["label"] == "Your home (actual)"
    assert home_row["source_tag"] == "history"
    # Median should be ~7.0 kW (capped by ac_ceiling; default fallback 7.4 kW ≥ 7.0 kW).
    assert abs(home_row["power_kw"] - 7.0) < 0.1


# ---------------------------------------------------------------------------
# DC sessions used for capability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dc_sessions_inform_capability(authed_client, test_sessionmaker):
    """Seeding DC sessions provides 'average' or 'curve' source_tag on DC rows."""
    # Car with known max_dc_kw=100.
    car_id = await _create_car(authed_client, battery_kwh=77.0, max_dc_kw=100.0)
    user_id = await _get_user_id(test_sessionmaker)

    # One DC session: 40 kWh in 1800 actual_charge_seconds = 80 kW effective.
    await _make_dc_session(
        test_sessionmaker,
        user_id,
        car_id,
        start_soc=20,
        end_soc=80,
        kwh_added=40.0,
        actual_charge_seconds=1800,  # 0.5 h → 80 kW
        wall_seconds=2000,
        days_ago=1,
    )

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["rows"]

    # DC rows are the last 3 (indices 3,4,5).
    dc_rows = rows[3:6]
    dc_tags = {row["source_tag"] for row in dc_rows}
    # At least one row should use observed data (average or curve), not all modelled.
    assert dc_tags & {"average", "curve"}, f"Expected average/curve in DC rows, got {dc_tags}"


@pytest.mark.asyncio
async def test_dc_sessions_with_curves_use_curve_tag(authed_client, test_sessionmaker):
    """DC sessions with power_curve data result in 'curve' source_tag for covered bands."""
    car_id = await _create_car(authed_client, battery_kwh=77.0, max_dc_kw=100.0)
    user_id = await _get_user_id(test_sessionmaker)

    # Power curve covering SoC 20-80 (every 10% with ~80 kW).
    power_curve = [
        [i * 60, 20 + i * 10, 80.0]  # [t_secs, soc, power_kw]
        for i in range(7)
    ]
    await _make_dc_session(
        test_sessionmaker,
        user_id,
        car_id,
        start_soc=20,
        end_soc=80,
        kwh_added=40.0,
        actual_charge_seconds=1800,
        wall_seconds=2000,
        power_curve=power_curve,
        days_ago=1,
    )

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["rows"]
    # "Car max" row (index 5) should show 'curve' (bands 20-80 covered).
    car_max_row = rows[5]
    assert car_max_row["label"] == "Car max"
    assert car_max_row["source_tag"] == "curve"


# ---------------------------------------------------------------------------
# loss_factor in response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loss_factor_in_response(authed_client):
    """loss_factor is returned in the response envelope."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    body = r.json()
    # Default charge_loss_factor is 0.90.
    assert abs(body["loss_factor"] - 0.90) < 0.001


# ---------------------------------------------------------------------------
# Error cases (unchanged semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_plan_404_unknown_car(authed_client):
    r = await authed_client.get(
        "/api/charge-plan?car_id=99999&start_soc=20&target_soc=80"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_charge_plan_400_target_not_greater_than_start(authed_client):
    car_id = await _create_car(authed_client)
    # target == start
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=50&target_soc=50"
    )
    assert r.status_code == 400

    # target < start
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=80&target_soc=20"
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_charge_plan_soc_validation_422(authed_client):
    """FastAPI should reject SoC values outside 0-100 with 422."""
    car_id = await _create_car(authed_client)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=-1&target_soc=80"
    )
    assert r.status_code == 422

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=101"
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Per-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_plan_car_not_owned_by_other_user(authed_client, test_sessionmaker):
    """A car owned by a different user should return 404."""
    async with test_sessionmaker() as session:
        from plugtrack.models import User as UserModel
        other = UserModel(username="other_user", password_hash="x")
        session.add(other)
        await session.commit()
        await session.refresh(other)
        other_id = other.id

        car = Car(
            user_id=other_id,
            make="Tesla",
            model="Model 3",
            battery_kwh=75.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=True,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)
        other_car_id = car.id

    r = await authed_client.get(
        f"/api/charge-plan?car_id={other_car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Archived car still plannable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archived_car_still_returns_plan(authed_client, test_sessionmaker):
    """Archived (active=False) cars should still return a scenario table (no active filter)."""
    user_id = await _get_user_id(test_sessionmaker)
    async with test_sessionmaker() as session:
        car = Car(
            user_id=user_id,
            make="Cupra",
            model="Born (archived)",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.6,
            provider="manual",
            active=False,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)
        archived_car_id = car.id

    r = await authed_client.get(
        f"/api/charge-plan?car_id={archived_car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["car_id"] == archived_car_id
    assert "rows" in body
    assert len(body["rows"]) >= 6


# ---------------------------------------------------------------------------
# Home location rate / is_free (preserved from original test suite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charge_plan_is_free_home_location(authed_client, test_sessionmaker):
    """Home location with is_free=True → is_free=True in response."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    user_id = await _get_user_id(test_sessionmaker)
    await _make_home_location(test_sessionmaker, user_id, is_free=True)

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_free"] is True


@pytest.mark.asyncio
async def test_charge_plan_home_location_custom_rate(authed_client, test_sessionmaker):
    """Home location with default_cost_per_kwh_p reflects that rate in response."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    user_id = await _get_user_id(test_sessionmaker)
    await _make_home_location(
        test_sessionmaker, user_id, default_cost_per_kwh_p=28.5
    )

    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_free"] is False
    assert body["home_rate_p_per_kwh"] == 28.5


@pytest.mark.asyncio
async def test_charge_plan_default_home_rate_fallback(authed_client):
    """No home location → uses 'default_home_rate_p_per_kwh' setting (7.5 p)."""
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    r = await authed_client.get(
        f"/api/charge-plan?car_id={car_id}&start_soc=20&target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_free"] is False
    assert body["home_rate_p_per_kwh"] == 7.5


# ---------------------------------------------------------------------------
# Blended two-phase plan: GET /api/charge-plan/blended
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blended_requires_auth(seeded_client):
    r = await seeded_client.get(
        "/api/charge-plan/blended?car_id=1&start_soc=20&dc_stop_soc=60&home_target_soc=80"
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_blended_happy_path_shape(authed_client):
    """Returns the blended envelope with dc_phase / home_phase / total."""
    car_id = await _create_car(authed_client, battery_kwh=77.0, max_dc_kw=150.0)
    r = await authed_client.get(
        f"/api/charge-plan/blended?car_id={car_id}"
        "&start_soc=20&dc_stop_soc=60&home_target_soc=80&dc_rate_p=50"
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["car_id"] == car_id
    assert body["start_soc"] == 20
    assert body["dc_stop_soc"] == 60
    assert body["target_soc"] == 80
    assert body["dc_rate_p"] == 50.0
    assert isinstance(body["is_free"], bool)

    # Phase energy: DC 30.8 kWh, home 15.4 kWh.
    assert abs(body["dc_phase"]["kwh"] - 30.8) < 0.05
    assert abs(body["home_phase"]["kwh"] - 15.4) < 0.05
    # Total energy + cost are the sum of phases.
    assert abs(body["total"]["kwh"] - 46.2) < 0.05
    assert (
        body["total"]["cost_pence"]
        == body["dc_phase"]["cost_pence"] + body["home_phase"]["cost_pence"]
    )
    assert body["total"]["minutes"] == body["dc_phase"]["minutes"] + body["home_phase"]["minutes"]
    # DC cost uses the supplied DC rate: 30.8 * 50 = 1540p.
    assert body["dc_phase"]["cost_pence"] == 1540
    # Efficiency echoed (car nominal 3.6) and cost-per-mile present.
    assert abs(body["total"]["mi_per_kwh"] - 3.6) < 0.001
    assert body["total"]["cost_per_mile_p"] is not None


@pytest.mark.asyncio
async def test_blended_default_dc_rate_when_omitted(authed_client):
    """dc_rate_p defaults to the public fallback (45 p) when not supplied."""
    car_id = await _create_car(authed_client, battery_kwh=77.0, max_dc_kw=150.0)
    r = await authed_client.get(
        f"/api/charge-plan/blended?car_id={car_id}"
        "&start_soc=20&dc_stop_soc=60&home_target_soc=80"
    )
    assert r.status_code == 200, r.text
    assert r.json()["dc_rate_p"] == 45.0


@pytest.mark.asyncio
async def test_blended_pure_dc_when_stop_equals_target(authed_client):
    """dc_stop_soc == home_target_soc → home phase is empty."""
    car_id = await _create_car(authed_client, battery_kwh=77.0, max_dc_kw=150.0)
    r = await authed_client.get(
        f"/api/charge-plan/blended?car_id={car_id}"
        "&start_soc=20&dc_stop_soc=80&home_target_soc=80"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["home_phase"]["kwh"] == 0
    assert body["home_phase"]["minutes"] == 0
    assert body["home_phase"]["cost_pence"] == 0


@pytest.mark.asyncio
async def test_blended_400_bad_ordering(authed_client):
    car_id = await _create_car(authed_client, battery_kwh=77.0)
    # dc_stop above target.
    r = await authed_client.get(
        f"/api/charge-plan/blended?car_id={car_id}"
        "&start_soc=20&dc_stop_soc=90&home_target_soc=80"
    )
    assert r.status_code == 400
    # target not above start.
    r = await authed_client.get(
        f"/api/charge-plan/blended?car_id={car_id}"
        "&start_soc=50&dc_stop_soc=50&home_target_soc=50"
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_blended_404_car_not_owned(authed_client, test_sessionmaker):
    """A car owned by another user returns 404 (per-user isolation)."""
    async with test_sessionmaker() as session:
        from plugtrack.models import User as UserModel
        other = UserModel(username="other_blended", password_hash="x")
        session.add(other)
        await session.commit()
        await session.refresh(other)
        car = Car(
            user_id=other.id,
            make="Tesla",
            model="Model 3",
            battery_kwh=75.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=True,
        )
        session.add(car)
        await session.commit()
        await session.refresh(car)
        other_car_id = car.id

    r = await authed_client.get(
        f"/api/charge-plan/blended?car_id={other_car_id}"
        "&start_soc=20&dc_stop_soc=60&home_target_soc=80"
    )
    assert r.status_code == 404
