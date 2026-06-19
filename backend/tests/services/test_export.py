"""Tests for the export service (Task 3).

Covers:
- export_sessions_rows: user-scoped query, location_name from LEFT JOIN,
  multi-user isolation, ordering, NULL-safe mapping, column set.
- export_locations_rows: user-scoped, correct columns, isolation.
- rows_to_csv: header line, one row per session, correct delimiter.
- rows_to_json: round-trips to a list of dicts, handles dates/datetimes as
  strings via default=str.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date

import pytest
import pytest_asyncio

from plugtrack.services.export import (
    SESSION_EXPORT_COLUMNS,
    export_locations_rows,
    export_sessions_rows,
    rows_to_csv,
    rows_to_json,
)


# ---------------------------------------------------------------------------
# Helpers — seed two fully isolated users
# ---------------------------------------------------------------------------

async def _seed_two_users(sm):
    """Seed User A and User B, each with a Car, a Location, and a ChargingSession.

    Returns ``(user_a_id, user_b_id, session_a_id, session_b_id,
               loc_a_id, loc_b_id)``.
    """
    from plugtrack.models import Car, ChargingSession, Location, User

    async with sm() as s:
        user_a = User(username="export_alice", password_hash="x")
        user_b = User(username="export_bob", password_hash="y")
        s.add_all([user_a, user_b])
        await s.commit()
        await s.refresh(user_a)
        await s.refresh(user_b)

        car_a = Car(
            user_id=user_a.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        car_b = Car(
            user_id=user_b.id,
            make="VW",
            model="ID.3",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.0,
            provider="manual",
            active=True,
        )
        s.add_all([car_a, car_b])
        await s.commit()
        await s.refresh(car_a)
        await s.refresh(car_b)

        loc_a = Location(
            user_id=user_a.id,
            name="Alice Home",
            centroid_lat=51.5,
            centroid_lng=-0.1,
        )
        loc_b = Location(
            user_id=user_b.id,
            name="Bob Work",
            centroid_lat=53.4,
            centroid_lng=-2.2,
        )
        s.add_all([loc_a, loc_b])
        await s.commit()
        await s.refresh(loc_a)
        await s.refresh(loc_b)

        sess_a = ChargingSession(
            user_id=user_a.id,
            car_id=car_a.id,
            date=date(2026, 6, 1),
            start_soc=20,
            end_soc=80,
            kwh_added=30.0,
            charging_type="ac",
            charging_mode="manual",
            interrupted=False,
            cost_basis="home_rate",
            source="synthesis",
            location_id=loc_a.id,
        )
        sess_b = ChargingSession(
            user_id=user_b.id,
            car_id=car_b.id,
            date=date(2026, 6, 2),
            start_soc=10,
            end_soc=90,
            kwh_added=46.4,
            charging_type="dc",
            charging_mode="manual",
            interrupted=False,
            cost_basis="unknown",
            source="manual",
            location_id=loc_b.id,
        )
        s.add_all([sess_a, sess_b])
        await s.commit()
        await s.refresh(sess_a)
        await s.refresh(sess_b)

        return (
            user_a.id, user_b.id,
            sess_a.id, sess_b.id,
            loc_a.id, loc_b.id,
        )


# ---------------------------------------------------------------------------
# SESSION_EXPORT_COLUMNS
# ---------------------------------------------------------------------------

def test_session_export_columns_stable():
    """SESSION_EXPORT_COLUMNS must contain exactly the specified fields."""
    expected = [
        "id", "date", "car_id", "charge_start_at", "charge_end_at",
        "start_soc", "end_soc", "kwh_added", "kwh_calculated",
        "odometer_at_session_km", "charging_type", "charging_mode",
        "actual_charge_seconds", "interrupted", "cost_pence", "cost_basis",
        "tariff_p_per_kwh", "cost_per_kwh_override_p", "total_cost_pence_override",
        "location_id", "location_name", "user_label", "charge_network", "notes",
        "source",
    ]
    assert SESSION_EXPORT_COLUMNS == expected


# ---------------------------------------------------------------------------
# export_sessions_rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_sessions_rows_returns_only_own_rows(test_sessionmaker):
    """User A sees only their own session; User B's session is absent."""
    user_a_id, user_b_id, sess_a_id, sess_b_id, *_ = await _seed_two_users(
        test_sessionmaker
    )

    async with test_sessionmaker() as s:
        rows_a = await export_sessions_rows(s, user_a_id)

    assert len(rows_a) == 1
    assert rows_a[0]["id"] == sess_a_id


@pytest.mark.asyncio
async def test_export_sessions_rows_user_b_isolation(test_sessionmaker):
    """User B sees only their own session; User A's session is absent."""
    user_a_id, user_b_id, sess_a_id, sess_b_id, *_ = await _seed_two_users(
        test_sessionmaker
    )

    async with test_sessionmaker() as s:
        rows_b = await export_sessions_rows(s, user_b_id)

    assert len(rows_b) == 1
    assert rows_b[0]["id"] == sess_b_id


@pytest.mark.asyncio
async def test_export_sessions_rows_location_name_populated(test_sessionmaker):
    """location_name comes from the LEFT JOIN on Location."""
    user_a_id, _, _, _, loc_a_id, _ = await _seed_two_users(test_sessionmaker)

    async with test_sessionmaker() as s:
        rows = await export_sessions_rows(s, user_a_id)

    assert rows[0]["location_name"] == "Alice Home"


@pytest.mark.asyncio
async def test_export_sessions_rows_location_name_null_when_no_location(
    test_sessionmaker,
):
    """location_name is None when the session has no location_id."""
    from plugtrack.models import Car, ChargingSession, User

    async with test_sessionmaker() as s:
        user = User(username="noloc_user", password_hash="x")
        s.add(user)
        await s.commit()
        await s.refresh(user)

        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)

        sess = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=date(2026, 6, 5),
            start_soc=30,
            end_soc=70,
            kwh_added=20.0,
            charging_type="ac",
            charging_mode="manual",
            interrupted=False,
            cost_basis="unknown",
            source="manual",
            location_id=None,
        )
        s.add(sess)
        await s.commit()
        await s.refresh(sess)
        uid = user.id

    async with test_sessionmaker() as s:
        rows = await export_sessions_rows(s, uid)

    assert len(rows) == 1
    assert rows[0]["location_name"] is None


@pytest.mark.asyncio
async def test_export_sessions_rows_keys_match_columns(test_sessionmaker):
    """Every row dict must have exactly the SESSION_EXPORT_COLUMNS keys."""
    user_a_id, *_ = await _seed_two_users(test_sessionmaker)

    async with test_sessionmaker() as s:
        rows = await export_sessions_rows(s, user_a_id)

    assert len(rows) == 1
    assert set(rows[0].keys()) == set(SESSION_EXPORT_COLUMNS)


@pytest.mark.asyncio
async def test_export_sessions_rows_empty_for_unknown_user(test_sessionmaker):
    """Querying with a non-existent user_id returns an empty list."""
    async with test_sessionmaker() as s:
        rows = await export_sessions_rows(s, user_id=999999)

    assert rows == []


# ---------------------------------------------------------------------------
# export_locations_rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_locations_rows_isolation(test_sessionmaker):
    """User A sees only their location; User B's location is absent."""
    user_a_id, user_b_id, _, _, loc_a_id, loc_b_id = await _seed_two_users(
        test_sessionmaker
    )

    async with test_sessionmaker() as s:
        rows_a = await export_locations_rows(s, user_a_id)
        rows_b = await export_locations_rows(s, user_b_id)

    assert len(rows_a) == 1
    assert rows_a[0]["id"] == loc_a_id

    assert len(rows_b) == 1
    assert rows_b[0]["id"] == loc_b_id


@pytest.mark.asyncio
async def test_export_locations_rows_expected_keys(test_sessionmaker):
    """Each location row must contain the expected export columns."""
    user_a_id, *_ = await _seed_two_users(test_sessionmaker)
    expected_keys = {
        "id", "name", "address", "latitude", "longitude",
        "is_free", "default_cost_per_kwh_p", "radius_m",
    }

    async with test_sessionmaker() as s:
        rows = await export_locations_rows(s, user_a_id)

    assert set(rows[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# rows_to_csv
# ---------------------------------------------------------------------------

def test_rows_to_csv_header_and_one_row():
    """CSV output must start with the correct header and have one data row."""
    columns = ["id", "date", "location_name"]
    rows = [{"id": 1, "date": date(2026, 6, 1), "location_name": "Home"}]

    output = rows_to_csv(columns, rows)

    reader = csv.DictReader(io.StringIO(output))
    assert reader.fieldnames == columns

    data_rows = list(reader)
    assert len(data_rows) == 1
    assert data_rows[0]["id"] == "1"
    assert data_rows[0]["location_name"] == "Home"


def test_rows_to_csv_empty_rows_produces_header_only():
    """Empty rows should still produce a header line."""
    columns = ["id", "date"]
    output = rows_to_csv(columns, [])

    reader = csv.DictReader(io.StringIO(output))
    assert reader.fieldnames == columns
    assert list(reader) == []


def test_rows_to_csv_uses_all_session_export_columns():
    """rows_to_csv with SESSION_EXPORT_COLUMNS should produce a valid CSV."""
    row = {col: None for col in SESSION_EXPORT_COLUMNS}
    row["id"] = 42
    row["date"] = date(2026, 6, 1)

    output = rows_to_csv(SESSION_EXPORT_COLUMNS, [row])
    reader = csv.DictReader(io.StringIO(output))
    assert reader.fieldnames == SESSION_EXPORT_COLUMNS
    data = list(reader)
    assert len(data) == 1
    assert data[0]["id"] == "42"


def test_rows_to_csv_multiple_rows():
    """Two rows produce two data lines in the CSV."""
    columns = ["id", "date"]
    rows = [
        {"id": 1, "date": date(2026, 6, 1)},
        {"id": 2, "date": date(2026, 6, 2)},
    ]
    output = rows_to_csv(columns, rows)
    reader = csv.DictReader(io.StringIO(output))
    data = list(reader)
    assert len(data) == 2
    assert data[0]["id"] == "1"
    assert data[1]["id"] == "2"


# ---------------------------------------------------------------------------
# rows_to_json
# ---------------------------------------------------------------------------

def test_rows_to_json_round_trips():
    """rows_to_json must produce valid JSON that round-trips to a list."""
    rows = [{"id": 1, "date": date(2026, 6, 1), "location_name": "Home"}]
    output = rows_to_json(rows)
    parsed = json.loads(output)

    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["id"] == 1
    # date is serialised as a string via default=str
    assert isinstance(parsed[0]["date"], str)
    assert "2026-06-01" in parsed[0]["date"]


def test_rows_to_json_empty_produces_empty_array():
    """Empty input must produce a JSON array, not null or an error."""
    output = rows_to_json([])
    assert json.loads(output) == []


def test_rows_to_json_none_values_survive():
    """None values must come out as JSON null, not be omitted."""
    rows = [{"id": 1, "location_name": None}]
    output = rows_to_json(rows)
    parsed = json.loads(output)
    assert parsed[0]["location_name"] is None
