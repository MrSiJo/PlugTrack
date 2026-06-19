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

import asyncio
import datetime as dt
from datetime import date, timezone

import pytest

from plugtrack.models import Car, ChargingSession, Location, Setting, User
from plugtrack.settings.seeds import seed_defaults

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


async def _seed_session(
    sm, user_id: int, car_id: int, *, date_offset: int = 0, **kwargs
) -> int:
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
    car_b = await _seed_car(test_sessionmaker, user_b)

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
            session, user_id,
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
        test_sessionmaker, user_id, car_id,
        kwh_added=10.0, cost_pence=75, cost_basis="home_rate", tariff_p_per_kwh=7.5
    )

    from sqlalchemy import select as sa_select

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(session, user_id, charge_id=cs_id, kwh=20.0)

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
    from plugtrack.mcp.tools import propose_edit_charge, commit_change

    await _seed_home_rate(test_sessionmaker, 15.0)  # different from frozen tariff
    user_id = await _seed_user(test_sessionmaker, "ivan")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker, user_id, car_id,
        kwh_added=10.0, cost_pence=75, cost_basis="home_rate", tariff_p_per_kwh=7.5
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(session, user_id, charge_id=cs_id, kwh=20.0)

    token = proposal["change_token"]

    async with test_sessionmaker() as session:
        commit_result = await commit_change(session, user_id, token)

    assert "error" not in commit_result, f"commit failed: {commit_result}"

    # Re-read the row
    from sqlalchemy import select as sa_select
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
        test_sessionmaker, user_id, car_id,
        kwh_added=10.0, cost_pence=75, cost_basis="home_rate", tariff_p_per_kwh=7.5
    )

    async with test_sessionmaker() as session:
        result = await propose_edit_charge(
            session, user_id, charge_id=cs_id, price_p_per_kwh=25.0
        )

    assert "error" not in result
    assert "change_token" in result

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.cost_per_kwh_override_p is None, "propose must NOT write to DB"


@pytest.mark.asyncio
async def test_commit_price_edit_sets_override_per_kwh(test_sessionmaker):
    """commit_change after price_p_per_kwh edit sets override_per_kwh basis."""
    from plugtrack.mcp.tools import propose_edit_charge, commit_change

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "kevin")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker, user_id, car_id,
        kwh_added=10.0, cost_pence=75, cost_basis="home_rate", tariff_p_per_kwh=7.5
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, price_p_per_kwh=25.0
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
    from plugtrack.mcp.tools import propose_edit_charge, commit_change

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "lara")
    car_id = await _seed_car(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker, user_id, car_id,
        kwh_added=10.0, cost_pence=75, cost_basis="home_rate", tariff_p_per_kwh=7.5
    )

    async with test_sessionmaker() as session:
        proposal = await propose_edit_charge(
            session, user_id, charge_id=cs_id, total_cost_p=500
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
        result = await propose_set_location(
            session, user_id, charge_id=cs_id, location_id=loc_id
        )

    assert "error" not in result
    assert "summary" in result
    assert "change_token" in result

    async with test_sessionmaker() as session:
        row = await session.get(ChargingSession, cs_id)
        assert row.location_id is None, "propose must NOT write to DB"


@pytest.mark.asyncio
async def test_commit_set_location_updates_location_and_recomputes_cost(test_sessionmaker):
    """commit_change for set_location sets location_id and recomputes cost."""
    from plugtrack.mcp.tools import propose_set_location, commit_change

    await _seed_home_rate(test_sessionmaker, 7.5)
    user_id = await _seed_user(test_sessionmaker, "nina")
    car_id = await _seed_car(test_sessionmaker, user_id)
    loc_id = await _seed_location(test_sessionmaker, user_id)
    cs_id = await _seed_session(
        test_sessionmaker, user_id, car_id,
        kwh_added=10.0, cost_pence=75, cost_basis="home_rate", tariff_p_per_kwh=7.5
    )

    async with test_sessionmaker() as session:
        proposal = await propose_set_location(
            session, user_id, charge_id=cs_id, location_id=loc_id
        )

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
    loc_id = await _seed_location(test_sessionmaker, user_id, name="Workplace")
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
        result = await propose_set_location(
            session, user_a, charge_id=cs_id, location_id=loc_b
        )

    assert "error" in result, "Should return error when location belongs to another user"


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
        result = await propose_create_location(
            session, user_id, name="Work", lat=51.5, lng=-0.1
        )

    assert "error" not in result
    assert "summary" in result
    assert "change_token" in result

    # Verify no location was created
    async with test_sessionmaker() as session:
        rows = (await session.execute(
            sa_select(Location).where(Location.user_id == user_id)
        )).scalars().all()
        assert len(rows) == 0, "propose_create_location must NOT create DB rows"


@pytest.mark.asyncio
async def test_commit_create_location_creates_location_row(test_sessionmaker):
    """commit_change after propose_create_location creates a Location row."""
    from plugtrack.mcp.tools import propose_create_location, commit_change
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
        rows = (await session.execute(
            sa_select(Location).where(Location.user_id == user_id)
        )).scalars().all()
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
    from plugtrack.mcp.tools import propose_create_location, commit_change
    import plugtrack.mcp.tools as tools_module

    user_id = await _seed_user(test_sessionmaker, "uma")

    async with test_sessionmaker() as session:
        proposal = await propose_create_location(
            session, user_id, name="Expired Place", lat=50.0, lng=-2.0
        )

    token = proposal["change_token"]

    # Manually expire the token by backdating its timestamp
    old_time = dt.datetime.now(timezone.utc) - dt.timedelta(minutes=15)
    tools_module._CHANGE_STORE[token]["created_at"] = old_time

    async with test_sessionmaker() as session:
        result = await commit_change(session, user_id, token)

    assert "error" in result
    assert "expired" in result["error"].lower()


@pytest.mark.asyncio
async def test_commit_cross_user_token_is_rejected(test_sessionmaker):
    """A token minted for user A must be rejected when user B tries to commit."""
    from plugtrack.mcp.tools import propose_create_location, commit_change

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
    from plugtrack.mcp.tools import propose_create_location, commit_change

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
        result = await propose_edit_charge(
            session, user_b, charge_id=cs_id, kwh=20.0
        )

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
        result = await propose_set_location(
            session, user_b, charge_id=cs_id, location_id=loc_a
        )

    assert "error" in result
