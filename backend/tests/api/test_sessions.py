"""Tests for /api/sessions and /api/locations/{id}/label."""
from __future__ import annotations

from datetime import date

import pytest

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


@pytest.mark.asyncio
async def test_list_sessions_requires_auth(seeded_client):
    r = await seeded_client.get("/api/sessions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_session_round_trip(authed_client):
    car_id = await _create_car(authed_client)

    r = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 46.2,
            "notes": "manual log",
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    sid = body["id"]
    assert body["source"] == "manual"
    assert body["start_soc"] == 20
    assert body["end_soc"] == 80
    # Default home rate from catalogue is 7.5 p/kWh.
    assert body["cost_basis"] == "home_rate"
    assert body["tariff_p_per_kwh"] == 7.5
    assert body["cost_pence"] == round(46.2 * 7.5)
    assert body["notes"] == "manual log"

    # GET single
    r = await authed_client.get(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid

    # LIST
    r = await authed_client.get("/api/sessions")
    assert r.status_code == 200
    assert any(s["id"] == sid for s in r.json())

    # filter by car
    r = await authed_client.get(f"/api/sessions?car_id={car_id}")
    assert r.status_code == 200
    assert all(s["car_id"] == car_id for s in r.json())


@pytest.mark.asyncio
async def test_create_session_with_per_kwh_override(authed_client):
    car_id = await _create_car(authed_client)
    r = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 46.2,
            "cost_per_kwh_override_p": 79.0,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["cost_basis"] == "override_per_kwh"
    assert body["tariff_p_per_kwh"] == 79.0
    assert body["cost_pence"] == round(46.2 * 79.0)


@pytest.mark.asyncio
async def test_create_session_with_total_override(authed_client):
    car_id = await _create_car(authed_client)
    r = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 21.5,
            "cost_per_kwh_override_p": 79.0,
            "total_cost_pence_override": 1840,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Mixed override: total wins, per-kwh preserved as tariff for breakdown.
    assert body["cost_pence"] == 1840
    assert body["cost_basis"] == "override_total"
    assert body["tariff_p_per_kwh"] == 79.0


@pytest.mark.asyncio
async def test_create_session_derives_kwh_calculated_from_soc_delta(authed_client):
    """Energy banked in the pack = (Δsoc/100) × battery_kwh.

    Distinct from `kwh_added` (charger reading) so efficiency_percent
    can mean something on a manual entry.
    """
    car_id = await _create_car(authed_client)
    r = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 60,
            "end_soc": 86,
            "kwh_added": 18.0,  # charger reading
            "total_cost_pence_override": 1199,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # 77 kWh battery × 26 pp / 100 = 20.02 kWh banked.
    assert body["kwh_calculated"] == pytest.approx(20.02, abs=0.01)
    assert body["kwh_added"] == 18.0  # untouched


@pytest.mark.asyncio
async def test_update_session_recomputes_kwh_calculated_on_soc_change(authed_client):
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 60, "end_soc": 80,
            "kwh_added": 18.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    # Initial: 20 pp × 77 / 100 = 15.4
    assert create.json()["kwh_calculated"] == pytest.approx(15.4, abs=0.01)

    # Adjust end_soc up to 90; kwh_calculated should track.
    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"end_soc": 90},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    # 30 pp × 77 / 100 = 23.1
    assert upd.json()["kwh_calculated"] == pytest.approx(23.1, abs=0.01)


@pytest.mark.asyncio
async def test_update_session_kwh_added_alone_leaves_kwh_calculated(authed_client):
    """kwh_calculated tracks SoC, not the charger reading."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 60, "end_soc": 86,
            "kwh_added": 18.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    original_calc = create.json()["kwh_calculated"]

    # Adjust only kwh_added — the user corrected their charger reading.
    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"kwh_added": 19.5},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    assert upd.json()["kwh_calculated"] == original_calc
    assert upd.json()["kwh_added"] == 19.5


@pytest.mark.asyncio
async def test_update_recomputes_cost_when_kwh_changes(authed_client):
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    assert create.json()["cost_pence"] == round(10.0 * 7.5)

    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"kwh_added": 20.0},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    assert upd.json()["cost_pence"] == round(20.0 * 7.5)


@pytest.mark.asyncio
async def test_update_does_not_recompute_when_only_notes_change(authed_client):
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
            "cost_per_kwh_override_p": 50.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    original_cost = create.json()["cost_pence"]

    # Notes-only change. Cost stays put (no recompute even if a global
    # rate changed elsewhere).
    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"notes": "still 50p override"},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    assert upd.json()["cost_pence"] == original_cost
    assert upd.json()["notes"] == "still 50p override"


@pytest.mark.asyncio
async def test_delete_session(authed_client):
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]

    r = await authed_client.delete(
        f"/api/sessions/{sid}", headers=csrf_headers(authed_client)
    )
    assert r.status_code == 204

    r = await authed_client.get(f"/api/sessions/{sid}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Location label endpoint
# ---------------------------------------------------------------------------


async def _create_location_for(test_sessionmaker, user_id: int) -> int:
    """Helper: insert an unlabelled location directly into the DB."""
    from plugtrack.models import Location

    async with test_sessionmaker() as session:
        loc = Location(
            user_id=user_id,
            centroid_lat=50.85,
            centroid_lng=-0.13,
            radius_m=100,
        )
        session.add(loc)
        await session.commit()
        await session.refresh(loc)
        return loc.id


async def _bootstrap_user_id(test_sessionmaker) -> int:
    from sqlalchemy import select

    from plugtrack.models import User

    async with test_sessionmaker() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        return result.scalar_one().id


@pytest.mark.asyncio
async def test_label_location_first_label_succeeds(authed_client, test_sessionmaker):
    user_id = await _bootstrap_user_id(test_sessionmaker)
    loc_id = await _create_location_for(test_sessionmaker, user_id)

    r = await authed_client.patch(
        f"/api/locations/{loc_id}/label",
        json={
            "name": "Home",
            "is_home": True,
            "is_free": False,
            "default_cost_per_kwh_p": 7.5,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["location"]["name"] == "Home"
    assert body["location"]["is_home"] is True
    assert body["sessions_recomputed_count"] == 0


@pytest.mark.asyncio
async def test_label_location_second_label_refused_409(authed_client, test_sessionmaker):
    user_id = await _bootstrap_user_id(test_sessionmaker)
    loc_id = await _create_location_for(test_sessionmaker, user_id)

    # First label.
    r1 = await authed_client.patch(
        f"/api/locations/{loc_id}/label",
        json={"name": "Home", "is_home": True, "is_free": False},
        headers=csrf_headers(authed_client),
    )
    assert r1.status_code == 200

    # Second attempt is refused.
    r2 = await authed_client.patch(
        f"/api/locations/{loc_id}/label",
        json={"name": "Different name"},
        headers=csrf_headers(authed_client),
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_label_location_is_forward_only(authed_client, test_sessionmaker):
    """First-labelling a location no longer rewrites past costs (freeze
    invariant). Past home_rate charges keep their frozen cost; only the
    non-cost network gap-fill still applies. The user presses 'recalculate
    past costs' to apply the new rate to history.
    """
    user_id = await _bootstrap_user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)
    loc_id = await _create_location_for(test_sessionmaker, user_id)

    # A plain charge on the unlabelled location lands on home_rate (7.5p),
    # with no charge_network set yet.
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "location_id": loc_id,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    assert create.status_code == 201, create.text
    sid = create.json()["id"]
    assert create.json()["cost_basis"] == "home_rate"
    assert create.json()["tariff_p_per_kwh"] == 7.5
    assert create.json()["cost_pence"] == 75
    assert create.json()["charge_network"] is None

    # Label the location with a per-kWh default AND a network.
    label = await authed_client.patch(
        f"/api/locations/{loc_id}/label",
        json={
            "name": "Public ChargePoint",
            "is_home": False,
            "is_free": False,
            "default_cost_per_kwh_p": 35.0,
            "default_charge_network": "BP Pulse",
        },
        headers=csrf_headers(authed_client),
    )
    assert label.status_code == 200, label.text
    # Forward-only: no past cost was rewritten.
    assert label.json()["sessions_recomputed_count"] == 0

    s0 = (await authed_client.get(f"/api/sessions/{sid}")).json()
    # Cost is FROZEN at the original home_rate — not re-rated to 35p.
    assert s0["cost_basis"] == "home_rate"
    assert s0["tariff_p_per_kwh"] == 7.5
    assert s0["cost_pence"] == 75
    # Non-cost network gap-fill still applies.
    assert s0["charge_network"] == "BP Pulse"

    # The explicit recalculate button is the way to apply the rate to history.
    recalc = await authed_client.post(
        f"/api/locations/{loc_id}/recalculate-past-costs",
        headers=csrf_headers(authed_client),
    )
    assert recalc.status_code == 200
    assert recalc.json()["sessions_recomputed_count"] == 1
    s0_after = (await authed_client.get(f"/api/sessions/{sid}")).json()
    assert s0_after["cost_basis"] == "location_rate"
    assert s0_after["tariff_p_per_kwh"] == 35.0
    assert s0_after["cost_pence"] == round(10.0 * 35.0)


@pytest.mark.asyncio
async def test_session_payload_exposes_charge_context(authed_client):
    """GET /api/sessions/{id} returns battery_care + max_charge_current."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    body = create.json()
    # Fields present on the response, default null for a manual session.
    assert "battery_care" in body
    assert "max_charge_current" in body
    assert body["battery_care"] is None
    assert body["max_charge_current"] is None

    got = (await authed_client.get(f"/api/sessions/{sid}")).json()
    assert "battery_care" in got
    assert "max_charge_current" in got


@pytest.mark.asyncio
async def test_update_session_accepts_charge_context(authed_client):
    """PUT accepts battery_care + max_charge_current and persists them."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]

    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"battery_care": True, "max_charge_current": "maximum"},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["battery_care"] is True
    assert body["max_charge_current"] == "maximum"

    # Survives a reload.
    got = (await authed_client.get(f"/api/sessions/{sid}")).json()
    assert got["battery_care"] is True
    assert got["max_charge_current"] == "maximum"


@pytest.mark.asyncio
async def test_update_session_accepts_timestamps_and_interrupted(authed_client):
    """PUT can correct charge_start_at/charge_end_at and the interrupted flag.

    This is the public-charging repair path: synthesis often captures only the
    tail of a public DC charge (cloud reports `charging` late), so the user
    needs to push the start time back and clear/keep the interrupted flag.
    """
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": "2026-06-01",
            "start_soc": 77,
            "end_soc": 100,
            "kwh_added": 15.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]

    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={
            "charge_start_at": "2026-06-01T17:30:00",
            "charge_end_at": "2026-06-01T18:01:01",
            "interrupted": False,
        },
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["charge_start_at"].startswith("2026-06-01T17:30:00")
    assert body["charge_end_at"].startswith("2026-06-01T18:01:01")
    assert body["interrupted"] is False

    # Survives a reload.
    got = (await authed_client.get(f"/api/sessions/{sid}")).json()
    assert got["charge_start_at"].startswith("2026-06-01T17:30:00")
    assert got["interrupted"] is False


@pytest.mark.asyncio
async def test_create_update_default_savings_fields_to_none(authed_client):
    """`_to_payload` defaults saved_vs_petrol_p/comparison_basis to None, so
    create + update responses (which don't run the batch pass) carry None for
    both — only the list endpoint populates them."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert "saved_vs_petrol_p" in body
    assert "comparison_basis" in body
    assert body["saved_vs_petrol_p"] is None
    assert body["comparison_basis"] is None

    sid = body["id"]
    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"notes": "tweak"},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    upd_body = upd.json()
    assert upd_body["saved_vs_petrol_p"] is None
    assert upd_body["comparison_basis"] is None


@pytest.mark.asyncio
async def test_override_columns_survive_unrelated_updates(authed_client):
    """Updating non-cost fields must not clobber the override columns."""
    from sqlalchemy import select

    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
            "cost_per_kwh_override_p": 50.0,
            "total_cost_pence_override": 700,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]

    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"charge_network": "BP Pulse"},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["cost_per_kwh_override_p"] == 50.0
    assert body["total_cost_pence_override"] == 700
    assert body["charge_network"] == "BP Pulse"


# ---------------------------------------------------------------------------
# Cost freezing — session edits re-scale at the frozen tariff (spec 01)
# ---------------------------------------------------------------------------


async def _set_global_home_rate(test_sessionmaker, value: str) -> None:
    """Mutate the seeded default_home_rate_p_per_kwh setting directly."""
    from sqlalchemy import select

    from plugtrack.models import Setting

    async with test_sessionmaker() as s:
        row = (
            await s.execute(
                select(Setting).where(Setting.key == "default_home_rate_p_per_kwh")
            )
        ).scalar_one()
        row.value = value
        await s.commit()


@pytest.mark.asyncio
async def test_global_rate_change_does_not_alter_stored_cost_on_read(
    authed_client, test_sessionmaker
):
    """Invariant guard: changing the global home rate then re-reading an
    existing session leaves cost_pence untouched (reads never recompute)."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    pre = create.json()["cost_pence"]
    assert pre == 75  # 10 * 7.5p seeded default

    await _set_global_home_rate(test_sessionmaker, "30.0")

    got = (await authed_client.get(f"/api/sessions/{sid}")).json()
    assert got["cost_pence"] == pre
    assert got["tariff_p_per_kwh"] == 7.5


@pytest.mark.asyncio
async def test_edit_kwh_rescales_at_frozen_tariff_not_current_global_rate(
    authed_client, test_sessionmaker
):
    """A home_rate session edited to a new kWh re-scales at its STORED tariff,
    never the current global rate."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    assert create.json()["cost_basis"] == "home_rate"
    assert create.json()["tariff_p_per_kwh"] == 7.5
    assert create.json()["cost_pence"] == 75

    # Change the global home rate; the frozen session must ignore it.
    await _set_global_home_rate(test_sessionmaker, "30.0")

    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"kwh_added": 20.0},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["cost_basis"] == "home_rate"
    assert body["tariff_p_per_kwh"] == 7.5
    # Re-scaled at the FROZEN 7.5p (150), NOT the new 30p (600).
    assert body["cost_pence"] == round(20.0 * 7.5)


@pytest.mark.asyncio
async def test_edit_kwh_on_total_override_keeps_total_updates_display_rate(
    authed_client,
):
    """Editing kWh on a total-override session keeps cost_pence at the override
    total; only the derived display tariff moves."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
            "total_cost_pence_override": 1000,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    assert create.json()["cost_basis"] == "override_total"
    assert create.json()["cost_pence"] == 1000
    assert create.json()["tariff_p_per_kwh"] == 100.0  # 1000 / 10

    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"kwh_added": 20.0},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["cost_pence"] == 1000  # override total is the truth
    assert body["cost_basis"] == "override_total"
    assert body["tariff_p_per_kwh"] == 50.0  # 1000 / 20


@pytest.mark.asyncio
async def test_explicit_override_change_re_derives_from_source(authed_client):
    """Setting an override on an existing rate-derived session is a deliberate
    change → derive from source (override wins per precedence)."""
    car_id = await _create_car(authed_client)
    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
        },
        headers=csrf_headers(authed_client),
    )
    sid = create.json()["id"]
    assert create.json()["cost_basis"] == "home_rate"

    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"cost_per_kwh_override_p": 40.0},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200
    body = upd.json()
    assert body["cost_basis"] == "override_per_kwh"
    assert body["tariff_p_per_kwh"] == 40.0
    assert body["cost_pence"] == round(10.0 * 40.0)


@pytest.mark.asyncio
async def test_moving_charge_to_another_location_keeps_frozen_cost(
    authed_client, test_sessionmaker
):
    """Reassigning a charge to a DIFFERENT location does NOT re-rate it
    (strict freeze, confirmed product decision). Cost stays at the original
    frozen tariff/basis; only an explicit override edit re-derives. The user
    presses 'recalculate past costs' if they truly want history re-priced.
    """
    from plugtrack.models import Location

    user_id = await _bootstrap_user_id(test_sessionmaker)
    car_id = await _create_car(authed_client)

    # Two labelled locations with different per-kWh rates.
    async with test_sessionmaker() as s:
        loc_a = Location(
            user_id=user_id, name="A", centroid_lat=50.85, centroid_lng=-0.13,
            radius_m=100, default_cost_per_kwh_p=20.0,
        )
        loc_b = Location(
            user_id=user_id, name="B", centroid_lat=51.5, centroid_lng=-0.1,
            radius_m=100, default_cost_per_kwh_p=60.0,
        )
        s.add_all([loc_a, loc_b])
        await s.commit()
        await s.refresh(loc_a)
        await s.refresh(loc_b)
        a_id, b_id = loc_a.id, loc_b.id

    create = await authed_client.post(
        "/api/sessions",
        json={
            "car_id": car_id,
            "date": date.today().isoformat(),
            "start_soc": 20,
            "end_soc": 80,
            "kwh_added": 10.0,
            "location_id": a_id,
        },
        headers=csrf_headers(authed_client),
    )
    assert create.status_code == 201, create.text
    sid = create.json()["id"]
    assert create.json()["cost_basis"] == "location_rate"
    assert create.json()["tariff_p_per_kwh"] == 20.0
    assert create.json()["cost_pence"] == 200  # 10 * 20p

    # Move the charge to location B (60p). Strict freeze: cost is unchanged.
    upd = await authed_client.put(
        f"/api/sessions/{sid}",
        json={"location_id": b_id},
        headers=csrf_headers(authed_client),
    )
    assert upd.status_code == 200, upd.text
    body = upd.json()
    assert body["location_id"] == b_id  # the label moved
    assert body["cost_basis"] == "location_rate"  # basis frozen
    assert body["tariff_p_per_kwh"] == 20.0  # still A's frozen rate, NOT 60
    assert body["cost_pence"] == 200  # unchanged, NOT round(10 * 60)
