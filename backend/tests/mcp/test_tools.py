"""Tests for the MCP tool core (Task 3).

Validates:
- find_charges: recent-first ordering, user-scoped (user B sees none of A's)
- get_charge: owned-only (another user's charge → None)
- get_insights: returns the spec-03 aggregator shapes
- propose_edit_charge(kwh=): returns summary+token, writes NOTHING (re-read row);
  commit_change then re-scales cost at the frozen tariff (basis unchanged)
- propose_edit_charge(price_p_per_kwh=): commit sets override_per_kwh basis
- propose_set_location + commit: sets location_id and recomputes cost
- propose_create_location + commit: creates a new Location row
- commit_change with stale/unknown token → error dict
- token minted for user A used by user B → error dict
- single-use: second commit → error dict
- cross-user isolation throughout
"""

from __future__ import annotations

import datetime as dt
from datetime import date

import pytest
from plugtrack.models import Car, ChargingSession, Location, Setting, User
from plugtrack.settings.seeds import seed_defaults

# ---------------------------------------------------------------------------
# limit clamping (pure helper)
# ---------------------------------------------------------------------------


def test_clamp_limit_caps_excessive_values():
    from plugtrack.mcp.tools import _clamp_limit

    assert _clamp_limit(10_000_000) == 200
    assert _clamp_limit(0) == 1
    assert _clamp_limit(-5) == 1
    assert _clamp_limit(25) == 25
    assert _clamp_limit(None) == 10  # default when unset/invalid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_home_rate(sm, rate: float) -> None:
    """Seed default settings and set the home rate to `rate`."""
    async with sm() as s:
        await seed_defaults(s)
        await s.commit()

    from sqlalchemy import select as sa_select

    async with sm() as s:
        result = await s.execute(
            sa_select(Setting).where(Setting.key == "default_home_rate_p_per_kwh")
        )
        row = result.scalar_one()
        row.value = str(rate)
        await s.commit()


async def _seed_user(sm, username: str) -> int:
    async with sm() as s:
        user = User(username=username, password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user.id


async def _seed_car(sm, user_id: int) -> int:
    async with sm() as s:
        car = Car(
            user_id=user_id,
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
        return car.id


async def _seed_session(sm, user_id: int, car_id: int, *, date_offset: int = 0, **kwargs) -> int:
    async with sm() as s:
        defaults = dict(
            user_id=user_id,
            car_id=car_id,
            date=date(2026, 6, 1) + dt.timedelta(days=date_offset),
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
        cs = ChargingSession(**defaults)
        s.add(cs)
        await s.commit()
        await s.refresh(cs)
        return cs.id


async def _seed_location(sm, user_id: int, *, name: str = "Home") -> int:
    async with sm() as s:
        loc = Location(
            user_id=user_id,
            name=name,
            centroid_lat=51.5,
            centroid_lng=-0.1,
            radius_m=100,
            is_home=True,
            is_free=False,
            default_cost_per_kwh_p=None,
        )
        s.add(loc)
        await s.commit()
        await s.refresh(loc)
        return loc.id


# ---------------------------------------------------------------------------
# find_charges tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_charges_recent_first(test_sessionmaker):
    """find_charges returns sessions in descending date order."""
    from plugtrack.mcp.tools import find_charges

    user_id = await _seed_user(test_sessionmaker, "alice")
    car_id = await _seed_car(test_sessionmaker, user_id)

    # Seed 3 sessions with different dates
    id1 = await _seed_session(test_sessionmaker, user_id, car_id, date_offset=0)
    id2 = await _seed_session(test_sessionmaker, user_id, car_id, date_offset=2)
    id3 = await _seed_session(test_sessionmaker, user_id, car_id, date_offset=1)

    async with test_sessionmaker() as session:
        results = await find_charges(session, user_id)

    assert len(results) == 3
    # Most recent (offset=2) should be first
    dates = [r["date"] for r in results]
    assert dates == sorted(dates, reverse=True), "Should be most-recent first"
    ids = [r["id"] for r in results]
    assert id2 in ids and id1 in ids and id3 in ids


@pytest.mark.asyncio
async def test_find_charges_user_scoped(test_sessionmaker):
    """User B sees none of user A's charges."""
    from plugtrack.mcp.tools import find_charges

    user_a = await _seed_user(test_sessionmaker, "alice")
    user_b = await _seed_user(test_sessionmaker, "bob")
    car_a = await _seed_car(test_sessionmaker, user_a)
    await _seed_car(test_sessionmaker, user_b)

    await _seed_session(test_sessionmaker, user_a, car_a)
    await _seed_session(test_sessionmaker, user_a, car_a, date_offset=1)

    async with test_sessionmaker() as session:
        results_b = await find_charges(session, user_b)

    assert results_b == [], "User B should see no sessions from user A"


@pytest.mark.asyncio
async def test_find_charges_limit(test_sessionmaker):
    """find_charges honours the limit parameter."""
    from plugtrack.mcp.tools import find_charges

    user_id = await _seed_user(test_sessionmaker, "alice2")
    car_id = await _seed_car(test_sessionmaker, user_id)
    for i in range(5):
        await _seed_session(test_sessionmaker, user_id, car_id, date_offset=i)

    async with test_sessionmaker() as session:
        results = await find_charges(session, user_id, limit=3)

    assert len(results) == 3


@pytest.mark.asyncio
async def test_find_charges_date_filter(test_sessionmaker):
    """find_charges filters by date_from / date_to."""
    from plugtrack.mcp.tools import find_charges

    user_id = await _seed_user(test_sessionmaker, "alice3")
    car_id = await _seed_car(test_sessionmaker, user_id)
    await _seed_session(test_sessionmaker, user_id, car_id, date_offset=0)  # Jun 1
    await _seed_session(test_sessionmaker, user_id, car_id, date_offset=5)  # Jun 6
    await _seed_session(test_sessionmaker, user_id, car_id, date_offset=10)  # Jun 11

    async with test_sessionmaker() as session:
        results = await find_charges(
            session,
            user_id,
            date_from=date(2026, 6, 4),
            date_to=date(2026, 6, 8),
        )

    assert len(results) == 1
    assert results[0]["date"] == date(2026, 6, 6)


@pytest.mark.asyncio
async def test_find_charges_result_shape(test_sessionmaker):
    """find_charges result has the required fields."""
    from plugtrack.mcp.tools import find_charges

    user_id = await _seed_user(test_sessionmaker, "alice4")
    car_id = await _seed_car(test_sessionmaker, user_id)
    loc_id = await _seed_location(test_sessionmaker, user_id)
    await _seed_session(
        test_sessionmaker, user_id, car_id, location_id=loc_id, charge_network="Pod Point"
    )

    async with test_sessionmaker() as session:
        results = await find_charges(session, user_id)

    assert len(results) == 1
    r = results[0]
    for field in ("id", "date", "kwh", "cost", "soc", "location_name", "network", "source"):
        assert field in r, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_find_charges_location_id_zero_is_no_filter(test_sessionmaker):
    """location_id=0 (models pass 0 for unset optionals) must NOT filter to nothing."""
    from plugtrack.mcp.tools import find_charges

    user_id = await _seed_user(test_sessionmaker, "alice_locfilter")
    car_id = await _seed_car(test_sessionmaker, user_id)
    await _seed_session(test_sessionmaker, user_id, car_id)
    await _seed_session(test_sessionmaker, user_id, car_id, date_offset=1)

    async with test_sessionmaker() as session:
        zero = await find_charges(session, user_id, location_id=0)
        none = await find_charges(session, user_id, location_id=None)

    assert len(zero) == 2, "location_id=0 must behave as no filter, not match location 0"
    assert len(none) == 2


@pytest.mark.asyncio
async def test_find_charges_formats_money(test_sessionmaker):
    """Per-charge cost is shown in pounds (£X.XX); tariff in pence (Np/kWh)."""
    from plugtrack.mcp.tools import find_charges

    user_id = await _seed_user(test_sessionmaker, "alice_money")
    car_id = await _seed_car(test_sessionmaker, user_id)
    await _seed_session(test_sessionmaker, user_id, car_id, cost_pence=985, tariff_p_per_kwh=7.5)

    async with test_sessionmaker() as session:
        r = (await find_charges(session, user_id))[0]

    assert r["cost"] == "£9.85", r["cost"]  # total in pounds
    assert r["cost_pence"] == 985  # raw still available
    assert r["tariff"] == "7.5p/kWh", r["tariff"]  # rate in pence


@pytest.mark.asyncio
async def test_get_insights_formats_spend_in_pounds(test_sessionmaker):
    """get_insights totals carry a pounds-formatted `spend` alongside spend_pence."""
    from plugtrack.mcp.tools import get_insights

    user_id = await _seed_user(test_sessionmaker, "alice_insights_money")
    car_id = await _seed_car(test_sessionmaker, user_id)
    await _seed_session(test_sessionmaker, user_id, car_id, cost_pence=985)

    async with test_sessionmaker() as session:
        ins = await get_insights(session, user_id)

    totals = ins["totals"]
    assert "spend_pence" in totals
    assert totals.get("spend") == _format_gbp_expected(totals["spend_pence"])


def _format_gbp_expected(pence) -> str:
    return f"£{pence / 100:.2f}"


# ---------------------------------------------------------------------------
# get_charge tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_charge_returns_owned(test_sessionmaker):
    """get_charge returns a dict for the owning user."""
    from plugtrack.mcp.tools import get_charge

    user_id = await _seed_user(test_sessionmaker, "charlie")
    car_id = await _seed_car(test_sessionmaker, user_id)
    session_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await get_charge(session, user_id, session_id)

    assert result is not None
    assert result["id"] == session_id


@pytest.mark.asyncio
async def test_get_charge_returns_none_for_other_user(test_sessionmaker):
    """get_charge returns None when the charge belongs to a different user."""
    from plugtrack.mcp.tools import get_charge

    user_a = await _seed_user(test_sessionmaker, "diana")
    user_b = await _seed_user(test_sessionmaker, "eve")
    car_a = await _seed_car(test_sessionmaker, user_a)
    session_id = await _seed_session(test_sessionmaker, user_a, car_a)

    async with test_sessionmaker() as session:
        result = await get_charge(session, user_b, session_id)

    assert result is None, "Should return None for another user's session"


@pytest.mark.asyncio
async def test_get_charge_returns_none_for_nonexistent(test_sessionmaker):
    """get_charge returns None for a non-existent charge id."""
    from plugtrack.mcp.tools import get_charge

    user_id = await _seed_user(test_sessionmaker, "frank")

    async with test_sessionmaker() as session:
        result = await get_charge(session, user_id, 99999)

    assert result is None


# ---------------------------------------------------------------------------
# get_insights tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_insights_returns_aggregator_shapes(test_sessionmaker):
    """get_insights composes spec-03 aggregators into one dict."""
    from plugtrack.mcp.tools import get_insights

    user_id = await _seed_user(test_sessionmaker, "grace")
    car_id = await _seed_car(test_sessionmaker, user_id)
    await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await get_insights(session, user_id)

    # Must be a dict (not an error)
    assert isinstance(result, dict)
    assert "error" not in result

    # Check top-level keys for spec-03 aggregators
    assert "totals" in result, "Missing 'totals'"
    assert "home_public_split" in result, "Missing 'home_public_split'"
    assert "network_breakdown" in result, "Missing 'network_breakdown'"

    # Totals shape
    totals = result["totals"]
    for key in ("spend_pence", "kwh", "sessions"):
        assert key in totals, f"Missing totals.{key}"

    # home_public_split shape
    split = result["home_public_split"]
    assert "home" in split and "public" in split

    # network_breakdown is a list
    assert isinstance(result["network_breakdown"], list)


@pytest.mark.asyncio
async def test_get_insights_user_scoped(test_sessionmaker):
    """get_insights sees only the caller's data."""
    from plugtrack.mcp.tools import get_insights

    user_a = await _seed_user(test_sessionmaker, "grace2a")
    user_b = await _seed_user(test_sessionmaker, "grace2b")
    car_a = await _seed_car(test_sessionmaker, user_a)
    # Seed 5 sessions for A
    for i in range(5):
        await _seed_session(test_sessionmaker, user_a, car_a, date_offset=i, kwh_added=10.0)

    async with test_sessionmaker() as session:
        result_b = await get_insights(session, user_b)

    assert result_b["totals"]["sessions"] == 0


# ---------------------------------------------------------------------------
# propose_edit_charge: kwh edit → writes nothing, commit re-scales cost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_edit_charge_kwh_writes_nothing(test_sessionmaker):
    """propose_edit_charge(kwh=) returns summary+token but writes NOTHING to DB."""
    from plugtrack.mcp.tools import propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "henry")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        kwh_added=10.0,
        cost_pence=75,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
    )

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(session, user_id, charge_id=cs_id, edits={"kwh": 20.0})

    assert "error" not in result, f"Unexpected error: {result}"
    assert "summary" in result
    assert "change_token" in result
    assert result["change_token"] is not None

    # Verify NOTHING was written to DB
    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.kwh_added == 10.0, "propose must NOT write to DB"
        assert row.cost_pence == 75, "propose must NOT write to DB"


@pytest.mark.asyncio
async def test_commit_kwh_edit_rescales_at_frozen_tariff(test_sessionmaker):
    """commit_change after kwh edit re-scales at frozen tariff, basis unchanged."""
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 15.0)  # different from frozen tariff
    user_id = await _seed_user(test_sessionmaker, "ivan")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        kwh_added=10.0,
        cost_pence=75,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(session, user_id, charge_id=cs_id, edits={"kwh": 20.0})

    token = proposal["change_token"]

    async with test_sessionmaker() as session:
        commit_result = await commit_change(session, user_id, token)

    assert "error" not in commit_result, f"commit failed: {commit_result}"

    # Re-read the row
    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.kwh_added == 20.0, "kwh_added should be updated"
        # Should rescale at frozen tariff 7.5, NOT settings rate 15.0
        assert row.cost_pence == round(20.0 * 7.5), "cost should be re-scaled at frozen tariff"
        assert row.cost_basis == "home_rate", "cost_basis should be unchanged"
        assert row.tariff_p_per_kwh == 7.5, "tariff should be unchanged (frozen)"


# ---------------------------------------------------------------------------
# propose_edit_charge: price_p_per_kwh → commit sets override_per_kwh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_edit_charge_price_writes_nothing(test_sessionmaker):
    """propose_edit_charge(price_p_per_kwh=) writes nothing to DB."""
    from plugtrack.mcp.tools import propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "julia")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        kwh_added=10.0,
        cost_pence=75,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
    )

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"price_p_per_kwh": 25.0}
        )

    assert "error" not in result
    assert "change_token" in result

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.cost_per_kwh_override_p is None, "propose must NOT write to DB"


@pytest.mark.asyncio
async def test_commit_price_edit_sets_override_per_kwh(test_sessionmaker):
    """commit_change after price_p_per_kwh edit sets override_per_kwh basis."""
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "kevin")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        kwh_added=10.0,
        cost_pence=75,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"price_p_per_kwh": 25.0}
        )

    async with test_sessionmaker() as session:
        await commit_change(session, user_id, proposal["change_token"])

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.cost_per_kwh_override_p == 25.0
        assert row.cost_basis == "override_per_kwh"
        assert row.cost_pence == round(10.0 * 25.0)


@pytest.mark.asyncio
async def test_commit_total_cost_sets_override_total(test_sessionmaker):
    """commit_change with total_cost_p sets override_total basis."""
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "lara")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        kwh_added=10.0,
        cost_pence=75,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"total_cost_p": 500}
        )

    async with test_sessionmaker() as session:
        await commit_change(session, user_id, proposal["change_token"])

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.total_cost_pence_override == 500
        assert row.cost_basis == "override_total"
        assert row.cost_pence == 500


# ---------------------------------------------------------------------------
# propose_set_location + commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_set_location_writes_nothing(test_sessionmaker):
    """propose_set_location returns summary+token, writes nothing to DB."""
    from plugtrack.mcp.tools import propose_set_location

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "mike")
    car_id = await _seed_car(test_sessionmaker, user_id)
    loc_id = await _seed_location(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await propose_set_location(session, user_id, charge_id=cs_id, location_id=loc_id)

    assert "error" not in result
    assert "summary" in result
    assert "change_token" in result

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.location_id is None, "propose must NOT write to DB"


@pytest.mark.asyncio
async def test_commit_set_location_updates_location_and_recomputes_cost(test_sessionmaker):
    """commit_change for set_location sets location_id and recomputes cost."""
    from plugtrack.mcp.tools import commit_change, propose_set_location

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "nina")
    car_id = await _seed_car(test_sessionmaker, user_id)
    loc_id = await _seed_location(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        kwh_added=10.0,
        cost_pence=75,
        cost_basis="home_rate",
        tariff_p_per_kwh=7.5,
    )

    async with test_sessionmaker() as session:
        proposal = await propose_set_location(session, user_id, charge_id=cs_id, location_id=loc_id)

    async with test_sessionmaker() as session:
        result = await commit_change(session, user_id, proposal["change_token"])

    assert "error" not in result

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.location_id == loc_id, "location_id should be set after commit"


@pytest.mark.asyncio
async def test_propose_set_location_by_name(test_sessionmaker):
    """propose_set_location resolves location by name if no location_id."""
    from plugtrack.mcp.tools import propose_set_location

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "oscar")
    car_id = await _seed_car(test_sessionmaker, user_id)
    await _seed_location(test_sessionmaker, user_id, name="Workplace")
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await propose_set_location(
            session, user_id, charge_id=cs_id, location_name="Workplace"
        )

    assert "error" not in result
    assert "change_token" in result


@pytest.mark.asyncio
async def test_propose_set_location_other_users_location_is_error(test_sessionmaker):
    """propose_set_location with another user's location_id returns error dict."""
    from plugtrack.mcp.tools import propose_set_location

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_a = await _seed_user(test_sessionmaker, "peter")
    user_b = await _seed_user(test_sessionmaker, "quinn")
    car_a = await _seed_car(test_sessionmaker, user_a)
    loc_b = await _seed_location(test_sessionmaker, user_b)  # belongs to B
    cs_id = await _seed_session(test_sessionmaker, user_a, car_a)

    async with test_sessionmaker() as session:
        result = await propose_set_location(session, user_a, charge_id=cs_id, location_id=loc_b)

    assert "error" in result, "Should return error when location belongs to another user"


# ---------------------------------------------------------------------------
# propose_attach_location (coords -> create/match location -> set on charge) + commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_attach_location_writes_nothing(test_sessionmaker):
    from plugtrack.mcp.tools import propose_attach_location
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "rhea")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await propose_attach_location(
            session, user_id, charge_id=cs_id, lat=50.148, lng=-5.665
        )
        assert "error" not in result
        assert "change_token" in result
        # nothing written yet
        assert (await session.execute(sa_select(func.count(Location.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_commit_attach_location_creates_and_sets(test_sessionmaker):
    from plugtrack.mcp.tools import commit_change, propose_attach_location
    from sqlalchemy import func
    from sqlalchemy import select as sa_select

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "silas")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        proposal = await propose_attach_location(
            session, user_id, charge_id=cs_id, lat=50.148, lng=-5.665
        )
    async with test_sessionmaker() as session:
        result = await commit_change(session, user_id, proposal["change_token"])
    assert "error" not in result

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.location_id is not None, "charge should be linked to the new location"
        loc = await session.get(Location, row.location_id)
        assert abs(loc.centroid_lat - 50.148) < 0.01 and abs(loc.centroid_lng - -5.665) < 0.01
        assert (await session.execute(sa_select(func.count(Location.id)))).scalar_one() == 1


@pytest.mark.asyncio
async def test_propose_attach_location_other_users_charge_is_error(test_sessionmaker):
    from plugtrack.mcp.tools import propose_attach_location

    user_a = await _seed_user(test_sessionmaker, "tara")
    user_b = await _seed_user(test_sessionmaker, "ulric")
    car_b = await _seed_car(test_sessionmaker, user_b)
    cs_b = await _seed_session(test_sessionmaker, user_b, car_b)

    async with test_sessionmaker() as session:
        result = await propose_attach_location(session, user_a, charge_id=cs_b, lat=50.1, lng=-5.6)
    assert "error" in result


# ---------------------------------------------------------------------------
# propose_create_location + commit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_create_location_writes_nothing(test_sessionmaker):
    """propose_create_location writes nothing to DB."""
    from plugtrack.mcp.tools import propose_create_location
    from sqlalchemy import select as sa_select

    user_id = await _seed_user(test_sessionmaker, "rachel")

    async with test_sessionmaker() as session:
        result = await propose_create_location(session, user_id, name="Work", lat=51.5, lng=-0.1)

    assert "error" not in result
    assert "summary" in result
    assert "change_token" in result

    # Verify no location was created
    async with test_sessionmaker() as session:
        rows = (
            (await session.execute(sa_select(Location).where(Location.user_id == user_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 0, "propose_create_location must NOT create DB rows"


@pytest.mark.asyncio
async def test_commit_create_location_creates_location_row(test_sessionmaker):
    """commit_change after propose_create_location creates a Location row."""
    from plugtrack.mcp.tools import commit_change, propose_create_location
    from sqlalchemy import select as sa_select

    user_id = await _seed_user(test_sessionmaker, "sam")

    async with test_sessionmaker() as session:
        proposal = await propose_create_location(
            session, user_id, name="Supercharger", lat=52.0, lng=-1.5
        )

    async with test_sessionmaker() as session:
        result = await commit_change(session, user_id, proposal["change_token"])

    assert "error" not in result

    async with test_sessionmaker() as session:
        rows = (
            (await session.execute(sa_select(Location).where(Location.user_id == user_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].name == "Supercharger"


# ---------------------------------------------------------------------------
# change-token security: stale/unknown, cross-user, single-use
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_unknown_token_returns_error(test_sessionmaker):
    """commit_change with an unknown token returns an error dict."""
    from plugtrack.mcp.tools import commit_change

    user_id = await _seed_user(test_sessionmaker, "tom")

    async with test_sessionmaker() as session:
        result = await commit_change(session, user_id, "nonexistent-token-xyz")

    assert "error" in result


@pytest.mark.asyncio
async def test_commit_expired_token_returns_error(test_sessionmaker):
    """commit_change with an expired token (past TTL) returns an error dict."""
    import plugtrack.mcp.tools as tools_module
    from plugtrack.mcp.tools import commit_change, propose_create_location

    user_id = await _seed_user(test_sessionmaker, "uma")

    async with test_sessionmaker() as session:
        proposal = await propose_create_location(
            session, user_id, name="Expired Place", lat=50.0, lng=-2.0
        )

    token = proposal["change_token"]

    # Manually expire the token by backdating its timestamp
    old_time = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=15)
    tools_module._CHANGE_STORE[token]["created_at"] = old_time

    async with test_sessionmaker() as session:
        result = await commit_change(session, user_id, token)

    assert "error" in result
    assert "expired" in result["error"].lower()


@pytest.mark.asyncio
async def test_commit_cross_user_token_is_rejected(test_sessionmaker):
    """A token minted for user A must be rejected when user B tries to commit."""
    from plugtrack.mcp.tools import commit_change, propose_create_location

    user_a = await _seed_user(test_sessionmaker, "vera")
    user_b = await _seed_user(test_sessionmaker, "will")

    async with test_sessionmaker() as session:
        proposal = await propose_create_location(
            session, user_a, name="A's Place", lat=51.0, lng=-0.5
        )

    token = proposal["change_token"]

    async with test_sessionmaker() as session:
        result = await commit_change(session, user_b, token)

    assert "error" in result, "User B must not be able to commit user A's token"


@pytest.mark.asyncio
async def test_commit_single_use_second_commit_is_error(test_sessionmaker):
    """Committing the same token twice returns an error on the second attempt."""
    from plugtrack.mcp.tools import commit_change, propose_create_location

    user_id = await _seed_user(test_sessionmaker, "xena")

    async with test_sessionmaker() as session:
        proposal = await propose_create_location(
            session, user_id, name="One-shot", lat=53.0, lng=-1.0
        )

    token = proposal["change_token"]

    async with test_sessionmaker() as session:
        first = await commit_change(session, user_id, token)

    assert "error" not in first, "First commit should succeed"

    async with test_sessionmaker() as session:
        second = await commit_change(session, user_id, token)

    assert "error" in second, "Second commit of the same token must fail (single-use)"


# ---------------------------------------------------------------------------
# Cross-user isolation for propose_* / commit_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_edit_charge_other_users_session_is_error(test_sessionmaker):
    """propose_edit_charge on another user's session returns error dict."""
    from plugtrack.mcp.tools import propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_a = await _seed_user(test_sessionmaker, "yuki")
    user_b = await _seed_user(test_sessionmaker, "zara")
    car_a = await _seed_car(test_sessionmaker, user_a)
    cs_id = await _seed_session(test_sessionmaker, user_a, car_a)

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(session, user_b, charge_id=cs_id, edits={"kwh": 20.0})

    assert "error" in result


@pytest.mark.asyncio
async def test_propose_set_location_other_users_session_is_error(test_sessionmaker):
    """propose_set_location on another user's session returns error dict."""
    from plugtrack.mcp.tools import propose_set_location

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_a = await _seed_user(test_sessionmaker, "alex2")
    user_b = await _seed_user(test_sessionmaker, "beth2")
    car_a = await _seed_car(test_sessionmaker, user_a)
    loc_a = await _seed_location(test_sessionmaker, user_a)
    cs_id = await _seed_session(test_sessionmaker, user_a, car_a)

    async with test_sessionmaker() as session:
        result = await propose_set_location(session, user_b, charge_id=cs_id, location_id=loc_a)

    assert "error" in result


# ---------------------------------------------------------------------------
# Fix 3: find_charges location_id filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_charges_location_id_filter(test_sessionmaker):
    """find_charges(location_id=X) returns only sessions at location X."""
    from plugtrack.mcp.tools import find_charges

    user_id = await _seed_user(test_sessionmaker, "loc_filter_user")
    car_id = await _seed_car(test_sessionmaker, user_id)
    loc_a = await _seed_location(test_sessionmaker, user_id, name="LocationA")
    loc_b = await _seed_location(test_sessionmaker, user_id, name="LocationB")

    # Two sessions at loc_a, one at loc_b
    id_a1 = await _seed_session(
        test_sessionmaker, user_id, car_id, date_offset=0, location_id=loc_a
    )
    id_a2 = await _seed_session(
        test_sessionmaker, user_id, car_id, date_offset=1, location_id=loc_a
    )
    _id_b = await _seed_session(
        test_sessionmaker, user_id, car_id, date_offset=2, location_id=loc_b
    )

    async with test_sessionmaker() as session:
        results = await find_charges(session, user_id, location_id=loc_a)

    ids = [r["id"] for r in results]
    assert set(ids) == {id_a1, id_a2}, "Only loc_a sessions should be returned"
    assert all(r["location_id"] == loc_a for r in results)


# ---------------------------------------------------------------------------
# Fix 1: propose_create_location geocodes at propose time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_create_location_address_geocodes_at_propose(test_sessionmaker, monkeypatch):
    """propose_create_location(address=...) geocodes at propose time and stores coords."""
    from plugtrack.mcp import tools as tools_module
    from plugtrack.mcp.tools import commit_change, propose_create_location
    from plugtrack.services.geocoding import GeocodeResult
    from sqlalchemy import select as sa_select

    FAKE_LAT = 51.5074
    FAKE_LNG = -0.1278

    class _FakeProvider:
        async def forward(self, query: str):
            return GeocodeResult(
                address="10 Downing Street, London, SW1A 2AA",
                provider="fake",
                lat=FAKE_LAT,
                lng=FAKE_LNG,
            )

        async def reverse(self, lat, lng):
            return None

    monkeypatch.setattr(tools_module, "get_provider", lambda settings: _FakeProvider())

    user_id = await _seed_user(test_sessionmaker, "geocode_propose_user")

    async with test_sessionmaker() as session:
        result = await propose_create_location(
            session, user_id, name="Westminster", address="10 Downing Street, London"
        )

    assert "error" not in result, f"Unexpected error: {result}"
    assert "summary" in result
    assert "change_token" in result
    # Summary should contain resolved coords
    assert str(round(FAKE_LAT, 4)) in result["summary"] or "51.5074" in result["summary"]

    # Commit should succeed and create a location with the geocoded coords
    async with test_sessionmaker() as session:
        commit_result = await commit_change(session, user_id, result["change_token"])

    assert "error" not in commit_result, f"Commit failed: {commit_result}"

    async with test_sessionmaker() as session:
        rows = (
            (await session.execute(sa_select(Location).where(Location.user_id == user_id)))
            .scalars()
            .all()
        )
    assert len(rows) >= 1
    # The created location should have the geocoded coordinates
    created = next((r for r in rows if r.name == "Westminster"), None)
    assert created is not None, "Location named 'Westminster' not found"
    assert abs(created.centroid_lat - FAKE_LAT) < 0.01
    assert abs(created.centroid_lng - FAKE_LNG) < 0.01


@pytest.mark.asyncio
async def test_propose_create_location_address_geocode_fails_returns_error(
    test_sessionmaker, monkeypatch
):
    """propose_create_location(address=...) returns error at propose time if geocoding fails."""
    from plugtrack.mcp import tools as tools_module
    from plugtrack.mcp.tools import propose_create_location
    from sqlalchemy import select as sa_select

    class _NoMatchProvider:
        async def forward(self, query: str):
            return None

        async def reverse(self, lat, lng):
            return None

    monkeypatch.setattr(tools_module, "get_provider", lambda settings: _NoMatchProvider())

    user_id = await _seed_user(test_sessionmaker, "geocode_fail_user")

    async with test_sessionmaker() as session:
        result = await propose_create_location(
            session, user_id, address="totally unmatchable address xyz"
        )

    assert "error" in result
    assert "geocode" in result["error"].lower() or "could not" in result["error"].lower()

    # No location should have been created
    async with test_sessionmaker() as session:
        rows = (
            (await session.execute(sa_select(Location).where(Location.user_id == user_id)))
            .scalars()
            .all()
        )
    assert len(rows) == 0, "No location should be created when geocoding fails"


# ---------------------------------------------------------------------------
# Fix 2: _mint_token purges expired/used entries from _CHANGE_STORE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_token_purges_expired_entries(test_sessionmaker):
    """_mint_token evicts entries whose age exceeds TTL before inserting the new one."""
    import plugtrack.mcp.tools as tools_module

    user_id = await _seed_user(test_sessionmaker, "evict_user")

    # Mint two tokens and artificially backdate them beyond the TTL
    async with test_sessionmaker() as session:
        r1 = await tools_module.propose_create_location(
            session, user_id, name="Old Place 1", lat=1.0, lng=1.0
        )
    async with test_sessionmaker() as session:
        r2 = await tools_module.propose_create_location(
            session, user_id, name="Old Place 2", lat=2.0, lng=2.0
        )

    tok1 = r1["change_token"]
    tok2 = r2["change_token"]

    # Backdate both tokens beyond TTL
    old_time = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=tools_module._TOKEN_TTL_SECONDS + 60)
    tools_module._CHANGE_STORE[tok1]["created_at"] = old_time
    tools_module._CHANGE_STORE[tok2]["created_at"] = old_time

    assert tok1 in tools_module._CHANGE_STORE
    assert tok2 in tools_module._CHANGE_STORE

    # Minting a new token should purge the expired ones
    async with test_sessionmaker() as session:
        r3 = await tools_module.propose_create_location(
            session, user_id, name="Fresh Place", lat=3.0, lng=3.0
        )

    tok3 = r3["change_token"]
    assert tok3 in tools_module._CHANGE_STORE, "New token should be present"
    assert tok1 not in tools_module._CHANGE_STORE, "Expired token 1 should have been evicted"
    assert tok2 not in tools_module._CHANGE_STORE, "Expired token 2 should have been evicted"


@pytest.mark.asyncio
async def test_mint_token_purges_used_entries(test_sessionmaker):
    """_mint_token evicts already-used entries before inserting the new one."""
    import plugtrack.mcp.tools as tools_module

    user_id = await _seed_user(test_sessionmaker, "evict_used_user")

    # Mint a token and mark it as used
    async with test_sessionmaker() as session:
        r1 = await tools_module.propose_create_location(
            session, user_id, name="Used Place", lat=10.0, lng=10.0
        )

    tok1 = r1["change_token"]
    # Commit it so it's marked used
    async with test_sessionmaker() as session:
        await tools_module.commit_change(session, user_id, tok1)

    assert tools_module._CHANGE_STORE[tok1]["used"] is True

    # Minting a new token should purge the used one
    async with test_sessionmaker() as session:
        r2 = await tools_module.propose_create_location(
            session, user_id, name="New Place", lat=11.0, lng=11.0
        )

    tok2 = r2["change_token"]
    assert tok2 in tools_module._CHANGE_STORE
    assert tok1 not in tools_module._CHANGE_STORE, "Used token should have been evicted"


# ---------------------------------------------------------------------------
# Odometer: propose_edit_charge + _session_to_dict display
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_edit_charge_odometer_mi_default(test_sessionmaker):
    """Odometer in miles (default unit) is converted to km and committed correctly."""
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "odo_mi_user")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id, odometer_at_session_km=None)

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"odometer": 11056}
        )

    assert "error" not in result, f"Unexpected error: {result}"
    assert "change_token" in result
    assert "summary" in result
    assert "11056" in result["summary"]

    async with test_sessionmaker() as session:
        commit_result = await commit_change(session, user_id, result["change_token"])

    assert "error" not in commit_result, f"Commit failed: {commit_result}"

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        expected_km = 11056 * 1.609344
        assert abs(row.odometer_at_session_km - expected_km) < 0.01, (
            f"Expected ~{expected_km} km, got {row.odometer_at_session_km}"
        )


@pytest.mark.asyncio
async def test_propose_edit_charge_odometer_km_explicit(test_sessionmaker):
    """Odometer with explicit km unit is stored as-is."""
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "odo_km_user")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id, odometer_at_session_km=None)

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"odometer": 17800}, odometer_unit="km"
        )

    assert "error" not in result

    async with test_sessionmaker() as session:
        commit_result = await commit_change(session, user_id, result["change_token"])

    assert "error" not in commit_result

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert abs(row.odometer_at_session_km - 17800.0) < 0.01, (
            f"Expected 17800.0 km, got {row.odometer_at_session_km}"
        )


@pytest.mark.asyncio
async def test_propose_edit_charge_odometer_summary_line(test_sessionmaker):
    """propose_edit_charge summary contains 'odometer' and the reading value."""
    from plugtrack.mcp.tools import propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "odo_summary_user")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"odometer": 11056}
        )

    assert "error" not in result
    summary = result["summary"]
    assert "odometer" in summary.lower()
    assert "11056" in summary


@pytest.mark.asyncio
async def test_find_charges_includes_odometer_display(test_sessionmaker):
    """find_charges result includes odometer_km and formatted odometer string."""
    from plugtrack.mcp.tools import find_charges
    from sqlalchemy import select as sa_select

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "odo_find_user")
    car_id = await _seed_car(test_sessionmaker, user_id)
    await _seed_session(test_sessionmaker, user_id, car_id, odometer_at_session_km=17800.0)

    # Set distance_unit to "mi"
    async with test_sessionmaker() as s:
        result = await s.execute(sa_select(Setting).where(Setting.key == "distance_unit"))
        row = result.scalar_one_or_none()
        if row is not None:
            row.value = "mi"
            await s.commit()

    async with test_sessionmaker() as session:
        results = await find_charges(session, user_id)

    assert results, "Expected at least one result"
    r = results[0]
    assert r["odometer_km"] == 17800.0
    assert r["odometer"] is not None
    assert "mi" in r["odometer"]
    # 17800 km / 1.609344 ≈ 11060 miles (formatted with comma: "11,060 mi")
    assert "11" in r["odometer"]  # starts with 11xxx
    assert "060" in r["odometer"] or "11060" in r["odometer"].replace(",", "")


@pytest.mark.asyncio
async def test_get_charge_includes_odometer_display(test_sessionmaker):
    """get_charge result includes odometer_km and formatted odometer string."""
    from plugtrack.mcp.tools import get_charge
    from sqlalchemy import select as sa_select

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "odo_get_user")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id, odometer_at_session_km=17800.0)

    # Set distance_unit to "mi"
    async with test_sessionmaker() as s:
        result = await s.execute(sa_select(Setting).where(Setting.key == "distance_unit"))
        row = result.scalar_one_or_none()
        if row is not None:
            row.value = "mi"
            await s.commit()

    async with test_sessionmaker() as session:
        r = await get_charge(session, user_id, cs_id)

    assert r is not None
    assert r["odometer_km"] == 17800.0
    assert r["odometer"] is not None
    assert "mi" in r["odometer"]
    # 17800 km / 1.609344 ≈ 11060 miles (formatted with comma: "11,060 mi")
    assert "11060" in r["odometer"].replace(",", "")


# ---------------------------------------------------------------------------
# Regression: model-supplied zero/blank defaults must not wipe a session
#
# Real incident (prod session #36): the user asked only "update session 36 for
# an soc end of 81%", but the model called propose_edit_charge with EVERY
# parameter filled in — zeros for the numeric fields and "" for the text ones.
# `if x is not None` let 0 and "" through as legitimate edits, and the commit
# faithfully wiped kwh, odometer, cost and notes, flipping cost_basis to
# override_total (£0.00).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_edit_charge_ignores_zero_filled_defaults(test_sessionmaker):
    """Zero/blank values for fields where they're meaningless must be ignored.

    Only the field the user actually named (end_soc) may change.
    """
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    await _seed_home_rate(test_sessionmaker, 19.26)
    user_id = await _seed_user(test_sessionmaker, "simon")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        kwh_added=13.9,
        start_soc=59,
        end_soc=80,
        cost_pence=268,
        cost_basis="location_rate",
        tariff_p_per_kwh=19.26,
        odometer_at_session_km=18193.63,
        charge_network="Outfox Energy",
        notes="original note",
    )

    # The user named exactly one field, so the edits map carries exactly one key.
    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"end_soc": 81}
        )

    assert "error" not in proposal, f"propose failed: {proposal}"

    async with test_sessionmaker() as session:
        commit_result = await commit_change(session, user_id, proposal["change_token"])

    assert "error" not in commit_result, f"commit failed: {commit_result}"

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        # The one field the user actually asked for
        assert row.end_soc == 81, "end_soc should be updated"
        # Everything else must survive
        assert row.kwh_added == 13.9, "kwh must NOT be zeroed"
        assert row.odometer_at_session_km == 18193.63, "odometer must NOT be zeroed"
        assert row.charge_network == "Outfox Energy", "network must NOT be blanked"
        assert row.notes == "original note", "notes must NOT be blanked"
        assert row.total_cost_pence_override is None, "no override should be created"
        assert row.cost_per_kwh_override_p is None, "no override should be created"
        assert row.cost_basis == "location_rate", "cost_basis must NOT flip to override_total"
        assert row.cost_pence == 268, "cost must NOT be zeroed"


@pytest.mark.asyncio
async def test_propose_edit_charge_clear_fields_blanks_explicitly(test_sessionmaker):
    """Genuine blanking is still possible, but only via the explicit clear_fields list."""
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    user_id = await _seed_user(test_sessionmaker, "clearer")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker,
        user_id,
        car_id,
        charge_network="Outfox Energy",
        notes="original note",
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"notes": None, "network": None}
        )

    assert "error" not in proposal, f"propose failed: {proposal}"

    async with test_sessionmaker() as session:
        commit_result = await commit_change(session, user_id, proposal["change_token"])

    assert "error" not in commit_result, f"commit failed: {commit_result}"

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.notes is None, "notes should be cleared"
        assert row.charge_network is None, "network should be cleared"


@pytest.mark.asyncio
async def test_propose_edit_charge_summary_is_before_after_diff(test_sessionmaker):
    """The confirmation summary must show before → after so a wipe can't hide."""
    from plugtrack.mcp.tools import propose_edit_charge

    user_id = await _seed_user(test_sessionmaker, "differ")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker, user_id, car_id, start_soc=59, end_soc=80, kwh_added=13.9
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"end_soc": 81}
        )

    summary = proposal["summary"]
    assert "80" in summary and "81" in summary, f"summary must show before→after: {summary}"
    # Untouched fields must not appear as changes
    assert "13.9" not in summary.split(":", 1)[1], f"unchanged kwh leaked into changes: {summary}"


@pytest.mark.asyncio
async def test_propose_edit_charge_has_no_per_field_parameters(test_sessionmaker):
    """The padding surface must not come back.

    Prod #37 happened because the signature offered ten optional scalar slots
    for a model to fill. Naming a field in `edits` is now the only way to
    change it, so there is nothing to pad — this pins that shape rather than
    the value-sniffing heuristics that replaced it once and failed.
    """
    import inspect

    from plugtrack.mcp.tools import propose_edit_charge

    params = set(inspect.signature(propose_edit_charge).parameters)
    leaked = params & {
        "kwh",
        "price_p_per_kwh",
        "total_cost_p",
        "start_soc",
        "end_soc",
        "date",
        "network",
        "notes",
        "odometer",
        "clear_fields",
    }
    assert not leaked, f"per-field parameters reintroduce the padding surface: {sorted(leaked)}"
    assert "edits" in params


@pytest.mark.asyncio
async def test_propose_edit_charge_end_soc_leaves_start_soc_alone(test_sessionmaker):
    """Prod #37: editing end SoC must not touch start SoC.

    The model padded `start_soc=0` alongside a real `end_soc=81`; SoC was
    exempt from the zero-guard, so a 60% start SoC was written to 0.
    """
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    user_id = await _seed_user(test_sessionmaker, "s37")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker, user_id, car_id, start_soc=60, end_soc=80, kwh_added=13.48
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"end_soc": 81}
        )
    async with test_sessionmaker() as session:
        await commit_change(session, user_id, proposal["change_token"])

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.end_soc == 81
        assert row.start_soc == 60, "start SoC must survive an end-SoC-only edit"


@pytest.mark.asyncio
async def test_propose_edit_charge_rejects_unknown_field(test_sessionmaker):
    """An invented or misspelled field is an error, never a silent no-op."""
    from plugtrack.mcp.tools import propose_edit_charge

    user_id = await _seed_user(test_sessionmaker, "typo")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(session, user_id, charge_id=cs_id, edits={"soc_end": 81})

    assert "soc_end" in result.get("error", ""), f"expected an unknown-field error: {result}"


@pytest.mark.asyncio
async def test_propose_edit_charge_empty_edits_is_an_error(test_sessionmaker):
    """An empty map is inert — it must never mint a token that writes nothing."""
    from plugtrack.mcp.tools import propose_edit_charge

    user_id = await _seed_user(test_sessionmaker, "empty")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id)

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(session, user_id, charge_id=cs_id, edits={})

    assert "error" in result
    assert "change_token" not in result


@pytest.mark.asyncio
async def test_propose_edit_charge_cannot_clear_a_required_field(test_sessionmaker):
    """Null is an erase, and erasing SoC/kwh/date is not a legitimate edit."""
    from plugtrack.mcp.tools import propose_edit_charge

    user_id = await _seed_user(test_sessionmaker, "nuller")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id, start_soc=60)

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"start_soc": None}
        )

    assert "error" in result, f"clearing start_soc must be refused: {result}"


@pytest.mark.asyncio
async def test_propose_edit_charge_zero_start_soc_is_still_valid(test_sessionmaker):
    """0% SoC is physically real — a named field is taken at face value."""
    from plugtrack.mcp.tools import commit_change, propose_edit_charge

    user_id = await _seed_user(test_sessionmaker, "flat")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(test_sessionmaker, user_id, car_id, start_soc=20)

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, edits={"start_soc": 0}
        )

    assert "error" not in proposal, f"propose failed: {proposal}"

    async with test_sessionmaker() as session:
        await commit_change(session, user_id, proposal["change_token"])

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.start_soc == 0, "an explicit 0% start SoC must be honoured"
