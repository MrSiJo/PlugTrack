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
