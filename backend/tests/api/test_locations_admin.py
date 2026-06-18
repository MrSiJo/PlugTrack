"""Tests for the Phase 5.3 locations admin CRUD endpoints.

Covers:
- GET /api/locations — list with aggregates, unlabelled-first sort.
- PUT /api/locations/{id} — forward-going edit, NEVER recomputes.
- POST /api/locations/{id}/recalculate-past-costs — explicit recompute,
  excludes override_* sessions.
- POST /api/locations/{id}/merge — atomic redirect of sessions +
  plug-ins, sums visit_count, deletes source, recomputes only when
  target's cost config differs.
- DELETE /api/locations/{id} — sessions preserved with location_id=NULL.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from plugtrack.models import ChargingSession, Location, PlugInRecord, User
from tests.api.conftest import csrf_headers


async def _create_car(client) -> int:
    r = await client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 77.0,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
        headers=csrf_headers(client),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _user_id(test_sessionmaker) -> int:
    async with test_sessionmaker() as session:
        row = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        return row.id


async def _make_location(
    test_sessionmaker,
    user_id: int,
    *,
    name: str | None = None,
    is_free: bool = False,
    default_cost_per_kwh_p: float | None = None,
    centroid_lat: float = 50.85,
    centroid_lng: float = -0.13,
    visit_count: int = 0,
) -> int:
    async with test_sessionmaker() as session:
        loc = Location(
            user_id=user_id,
            name=name,
            centroid_lat=centroid_lat,
            centroid_lng=centroid_lng,
            radius_m=100,
            is_free=is_free,
            default_cost_per_kwh_p=default_cost_per_kwh_p,
            visit_count=visit_count,
        )
        session.add(loc)
        await session.commit()
        await session.refresh(loc)
        return loc.id


# ---------------------------------------------------------------------------
# GET /api/locations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_locations_requires_auth(seeded_client):
    r = await seeded_client.get("/api/locations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_locations_unlabelled_first(authed_client, test_sessionmaker):
    user_id = await _user_id(test_sessionmaker)
    labelled_id = await _make_location(
        test_sessionmaker, user_id, name="Home", default_cost_per_kwh_p=7.5
    )
    unlabelled_id = await _make_location(
        test_sessionmaker, user_id, name=None, centroid_lat=51.5, centroid_lng=-0.1
    )

    r = await authed_client.get("/api/locations")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    # Unlabelled (name None) sorts first.
    assert body[0]["id"] == unlabelled_id
    assert body[0]["name"] is None
    assert body[1]["id"] == labelled_id
    assert body[1]["name"] == "Home"


@pytest.mark.asyncio
async def test_list_locations_with_aggregates(authed_client, test_sessionmaker):
    user_id = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    loc_id = await _make_location(
        test_sessionmaker, user_id, name="Home", default_cost_per_kwh_p=10.0
    )

    # Create two sessions linked to the location.
    for kwh in (10.0, 20.0):
        r = await authed_client.post(
            "/api/sessions",
            json={
                "car_id": car_id,
                "date": date.today().isoformat(),
                "start_soc": 20,
                "end_soc": 80,
                "kwh_added": kwh,
                "location_id": loc_id,
            },
            headers=csrf_headers(authed_client),
        )
        assert r.status_code == 201

    r = await authed_client.get("/api/locations")
    assert r.status_code == 200
    body = r.json()
    [entry] = [e for e in body if e["id"] == loc_id]
    assert entry["visit_count"] == 2
    assert entry["total_kwh"] == pytest.approx(30.0, abs=0.01)
    # 10kwh * 10p + 20kwh * 10p = 300p
    assert entry["total_cost_pence"] == 300


# ---------------------------------------------------------------------------
# PUT /api/locations/{id} — forward-going only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_location_forward_only_does_not_recompute(
    authed_client, test_sessionmaker
):
    user_id = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    loc_id = await _make_location(
        test_sessionmaker,
        user_id,
        name="Home",
        default_cost_per_kwh_p=10.0,
    )

    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
            "location_id": loc_id,
        },
        headers=csrf_headers(authed_client),
    )
    assert create.status_code == 201
    sid = create.json()["id"]
    pre_cost = create.json()["cost_pence"]
    assert pre_cost == 100  # 10 * 10p

    # Now bump the rate via PUT — past session must NOT change.
    r = await authed_client.put(
        f"/api/locations/{loc_id}",
        json={"default_cost_per_kwh_p": 50.0},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["default_cost_per_kwh_p"] == 50.0

    # Past session is untouched.
    cur = await authed_client.get(f"/api/sessions/{sid}")
    assert cur.json()["cost_pence"] == pre_cost


@pytest.mark.asyncio
async def test_put_location_404_when_other_user(authed_client, test_sessionmaker):
    # Wrong user id (we never created one for this id).
    r = await authed_client.put(
        "/api/locations/99999",
        json={"name": "Nope"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/locations/{id}/recalculate-past-costs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recalculate_past_costs_excludes_override_sessions(
    authed_client, test_sessionmaker
):
    user_id = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    loc_id = await _make_location(
        test_sessionmaker,
        user_id,
        name="Public",
        default_cost_per_kwh_p=10.0,
    )

    payloads = [
        {"kwh_added": 10.0},  # location_rate @ 10p
        {"kwh_added": 10.0, "cost_per_kwh_override_p": 50.0},  # override_per_kwh
        {"kwh_added": 10.0, "total_cost_pence_override": 999},  # override_total
    ]
    sids = []
    for extra in payloads:
        r = await authed_client.post(
            "/api/sessions",
            json={
                "car_id": car_id,
                "date": date.today().isoformat(),
                "start_soc": 20,
                "end_soc": 80,
                "location_id": loc_id,
                **extra,
            },
            headers=csrf_headers(authed_client),
        )
        assert r.status_code == 201
        sids.append(r.json()["id"])

    pre = [
        (await authed_client.get(f"/api/sessions/{sid}")).json() for sid in sids
    ]

    # Bump rate via PUT (forward-only), THEN explicit recalc.
    await authed_client.put(
        f"/api/locations/{loc_id}",
        json={"default_cost_per_kwh_p": 25.0},
        headers=csrf_headers(authed_client),
    )

    r = await authed_client.post(
        f"/api/locations/{loc_id}/recalculate-past-costs",
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["sessions_recomputed_count"] == 1

    post = [
        (await authed_client.get(f"/api/sessions/{sid}")).json() for sid in sids
    ]
    # Non-override session got recomputed at the new rate.
    assert post[0]["cost_pence"] == round(10.0 * 25.0)
    assert post[0]["tariff_p_per_kwh"] == 25.0
    # Override sessions untouched.
    assert post[1]["cost_pence"] == pre[1]["cost_pence"]
    assert post[2]["cost_pence"] == pre[2]["cost_pence"]


# ---------------------------------------------------------------------------
# POST /api/locations/{id}/merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_redirects_sessions_and_plug_ins(
    authed_client, test_sessionmaker
):
    user_id = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    src_id = await _make_location(
        test_sessionmaker, user_id, name="A", visit_count=3,
        centroid_lat=50.0, centroid_lng=0.0,
    )
    tgt_id = await _make_location(
        test_sessionmaker, user_id, name="B", visit_count=2,
        centroid_lat=51.0, centroid_lng=1.0,
    )

    # Two sessions on source.
    sids = []
    for _ in range(2):
        r = await authed_client.post(
            "/api/sessions",
            json={
                "car_id": car_id,
                "date": date.today().isoformat(),
                "start_soc": 20,
                "end_soc": 80,
                "kwh_added": 5.0,
                "location_id": src_id,
            },
            headers=csrf_headers(authed_client),
        )
        sids.append(r.json()["id"])

    # One plug-in row also on source.
    async with test_sessionmaker() as s:
        from datetime import datetime, timezone
        pir = PlugInRecord(
            user_id=user_id, car_id=car_id,
            plug_in_at=datetime.now(timezone.utc), plug_in_soc=40,
            location_id=src_id,
        )
        s.add(pir)
        await s.commit()
        await s.refresh(pir)
        pir_id = pir.id

    r = await authed_client.post(
        f"/api/locations/{src_id}/merge",
        json={"target_id": tgt_id},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessions_redirected"] == 2
    assert body["plug_ins_redirected"] == 1

    # Source row deleted.
    async with test_sessionmaker() as s:
        assert (await s.get(Location, src_id)) is None
        # All sessions now point at target.
        for sid in sids:
            cs = await s.get(ChargingSession, sid)
            assert cs.location_id == tgt_id
        # Plug-in points at target.
        pir = await s.get(PlugInRecord, pir_id)
        assert pir.location_id == tgt_id
        # Visits summed.
        tgt = await s.get(Location, tgt_id)
        assert tgt.visit_count == 5  # 3 + 2


@pytest.mark.asyncio
async def test_merge_recomputes_only_when_target_cost_differs(
    authed_client, test_sessionmaker
):
    user_id = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    # Source and target both 10p — identical → no recompute.
    src_id = await _make_location(
        test_sessionmaker, user_id, name="src", default_cost_per_kwh_p=10.0,
    )
    tgt_id = await _make_location(
        test_sessionmaker, user_id, name="tgt", default_cost_per_kwh_p=10.0,
        centroid_lat=51.0, centroid_lng=1.0,
    )
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id, "date": date.today().isoformat(),
            "start_soc": 20, "end_soc": 80, "kwh_added": 10.0,
            "location_id": src_id,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    pre = create.json()["cost_pence"]

    r = await authed_client.post(
        f"/api/locations/{src_id}/merge",
        json={"target_id": tgt_id},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200
    assert r.json()["sessions_recomputed_count"] == 0

    cur = await authed_client.get(f"/api/sessions/{sid}")
    assert cur.json()["cost_pence"] == pre

    # Now do another merge where costs DO differ.
    src2_id = await _make_location(
        test_sessionmaker, user_id, name="src2", default_cost_per_kwh_p=10.0,
        centroid_lat=52.0, centroid_lng=2.0,
    )
    tgt2_id = await _make_location(
        test_sessionmaker, user_id, name="tgt2", default_cost_per_kwh_p=40.0,
        centroid_lat=53.0, centroid_lng=3.0,
    )
    create2 = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id, "date": date.today().isoformat(),
            "start_soc": 20, "end_soc": 80, "kwh_added": 10.0,
            "location_id": src2_id,
        },
        headers=csrf_headers(authed_client),
    )
    sid2 = create2.json()["id"]

    r = await authed_client.post(
        f"/api/locations/{src2_id}/merge",
        json={"target_id": tgt2_id},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200
    assert r.json()["sessions_recomputed_count"] == 1
    cur = await authed_client.get(f"/api/sessions/{sid2}")
    # Recomputed at target's 40p rate.
    assert cur.json()["cost_pence"] == round(10.0 * 40.0)
    assert cur.json()["tariff_p_per_kwh"] == 40.0


@pytest.mark.asyncio
async def test_merge_self_returns_400(authed_client, test_sessionmaker):
    user_id = await _user_id(test_sessionmaker)
    loc_id = await _make_location(test_sessionmaker, user_id, name="A")
    r = await authed_client.post(
        f"/api/locations/{loc_id}/merge",
        json={"target_id": loc_id},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/locations/{id} — preserves sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_location_preserves_sessions(
    authed_client, test_sessionmaker
):
    user_id = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    loc_id = await _make_location(
        test_sessionmaker, user_id, name="X", default_cost_per_kwh_p=10.0,
    )
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id, "date": date.today().isoformat(),
            "start_soc": 20, "end_soc": 80, "kwh_added": 10.0,
            "location_id": loc_id,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    pre_cost = create.json()["cost_pence"]

    r = await authed_client.delete(
        f"/api/locations/{loc_id}",
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 204

    async with test_sessionmaker() as s:
        assert (await s.get(Location, loc_id)) is None
        cs = await s.get(ChargingSession, sid)
        assert cs is not None  # Session preserved.
        assert cs.location_id is None  # Detached.
        # cost_pence retained — recompute is an explicit user action.
        assert cs.cost_pence == pre_cost


# ---------------------------------------------------------------------------
# POST /api/locations — manual create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_location_requires_auth(seeded_client):
    r = await seeded_client.post(
        "/api/locations",
        json={"centroid_lat": 50.85, "centroid_lng": -0.13},
        headers=csrf_headers(seeded_client),
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_location_full(authed_client, test_sessionmaker):
    r = await authed_client.post(
        "/api/locations",
        json={
            "name": "Tesla Camborne",
            "centroid_lat": 50.2276,
            "centroid_lng": -5.2801,
            "radius_m": 120,
            "is_free": False,
            "default_cost_per_kwh_p": 45.0,
            "default_charge_network": "Tesla",
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Tesla Camborne"
    assert body["centroid_lat"] == pytest.approx(50.2276)
    assert body["centroid_lng"] == pytest.approx(-5.2801)
    assert body["radius_m"] == 120
    assert body["default_cost_per_kwh_p"] == 45.0
    assert body["default_charge_network"] == "Tesla"

    # Persisted and owned by the authenticated user, visit_count seeded 0.
    async with test_sessionmaker() as s:
        loc = await s.get(Location, body["id"])
        assert loc is not None
        assert loc.visit_count == 0
        assert loc.is_home is False


@pytest.mark.asyncio
async def test_create_location_blank_name_becomes_null(authed_client):
    r = await authed_client.post(
        "/api/locations",
        json={"name": "   ", "centroid_lat": 51.5, "centroid_lng": -0.1},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] is None
    # Unlabelled rows default radius and surface in the list.
    assert body["radius_m"] == 100


@pytest.mark.asyncio
async def test_create_location_rejects_out_of_range_coords(authed_client):
    r = await authed_client.post(
        "/api/locations",
        json={"centroid_lat": 200.0, "centroid_lng": -0.1},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/locations/{id} — bake rate into a frozen override (spec 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_location_bakes_rate_into_override(
    authed_client, test_sessionmaker
):
    """location_rate + location_free sessions are baked into a frozen
    cost_per_kwh_override_p before detach, so a later edit can never silently
    drop them to the home rate."""
    user_id = await _user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    paid_id = await _make_location(
        test_sessionmaker, user_id, name="Public", default_cost_per_kwh_p=42.0
    )
    free_id = await _make_location(
        test_sessionmaker,
        user_id,
        name="Free",
        is_free=True,
        centroid_lat=52.0,
        centroid_lng=2.0,
    )

    rate_s = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
            "location_id": paid_id,
        },
        headers=csrf_headers(authed_client),
    )
    free_s = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
            "location_id": free_id,
        },
        headers=csrf_headers(authed_client),
    )
    rate_sid = rate_s.json()["id"]
    free_sid = free_s.json()["id"]
    assert rate_s.json()["cost_basis"] == "location_rate"
    assert rate_s.json()["cost_pence"] == round(10.0 * 42.0)
    assert free_s.json()["cost_basis"] == "location_free"
    assert free_s.json()["cost_pence"] == 0

    # Delete the paid location → bake into override.
    r = await authed_client.delete(
        f"/api/locations/{paid_id}", headers=csrf_headers(authed_client)
    )
    assert r.status_code == 204
    rate_after = (await authed_client.get(f"/api/sessions/{rate_sid}")).json()
    assert rate_after["location_id"] is None
    assert rate_after["cost_basis"] == "override_per_kwh"
    assert rate_after["cost_per_kwh_override_p"] == 42.0
    assert rate_after["cost_pence"] == round(10.0 * 42.0)  # unchanged

    # Delete the free location → baked as 0 override, £0 preserved.
    r2 = await authed_client.delete(
        f"/api/locations/{free_id}", headers=csrf_headers(authed_client)
    )
    assert r2.status_code == 204
    free_after = (await authed_client.get(f"/api/sessions/{free_sid}")).json()
    assert free_after["location_id"] is None
    assert free_after["cost_basis"] == "override_per_kwh"
    assert free_after["cost_per_kwh_override_p"] == 0.0
    assert free_after["cost_pence"] == 0

    # The bake is durable: editing kWh now re-scales at the frozen override,
    # not the home rate.
    upd = await authed_client.put(
        f"/api/sessions/{rate_sid}",
        json={"kwh_added": 20.0},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    assert upd.json()["cost_basis"] == "override_per_kwh"
    assert upd.json()["cost_pence"] == round(20.0 * 42.0)
