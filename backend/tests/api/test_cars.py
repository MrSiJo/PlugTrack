"""Tests for /api/cars CRUD."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.api.conftest import csrf_headers


@pytest.mark.asyncio
async def test_list_cars_requires_auth(seeded_client):
    r = await seeded_client.get("/api/cars")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_car_requires_csrf(authed_client):
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 77.0,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_car_round_trip_with_vin(authed_client):
    payload = {
        "make": "Cupra",
        "model": "Born",
        "vin": "TESTVIN0000000001",
        "battery_kwh": 77.0,
        "nominal_efficiency_mi_per_kwh": 3.6,
        "provider": "cupra_connect",
        "provider_vehicle_id": "abc-123",
    }
    r = await authed_client.post(
        "/api/cars", json=payload, headers=csrf_headers(authed_client)
    )
    assert r.status_code == 201, r.text
    body = r.json()
    car_id = body["id"]
    # VIN is now masked in the payload — last 5 chars only.
    assert body["vin"] == "············00001"
    assert body["battery_kwh"] == 77.0
    assert body["active"] is True

    # Fetch single car — also masked.
    r = await authed_client.get(f"/api/cars/{car_id}")
    assert r.status_code == 200
    assert r.json()["vin"] == "············00001"

    # Full VIN only via the reveal endpoint.
    r = await authed_client.get(f"/api/cars/{car_id}/vin")
    assert r.status_code == 200
    assert r.json()["vin"] == "TESTVIN0000000001"

    # List
    r = await authed_client.get("/api/cars")
    assert r.status_code == 200
    cars = r.json()
    assert len(cars) == 1
    assert cars[0]["id"] == car_id


@pytest.mark.asyncio
async def test_vin_is_encrypted_in_db(authed_client, test_sessionmaker):
    plain_vin = "TESTVIN0000000077"
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "vin": plain_vin,
            "battery_kwh": 77.0,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    car_id = r.json()["id"]

    # Read raw column via raw SQL — plaintext must never appear.
    async with test_sessionmaker() as session:
        result = await session.execute(
            text("SELECT vin_encrypted FROM car WHERE id = :id"),
            {"id": car_id},
        )
        raw_value = result.scalar_one()

    assert raw_value is not None
    assert plain_vin not in raw_value
    # Sanity: ciphertext is much longer than plaintext.
    assert len(raw_value) > len(plain_vin) + 16

    # And the property still decrypts back to plaintext via the model.
    from plugtrack.models import Car
    from sqlalchemy import select

    async with test_sessionmaker() as session:
        car = (await session.execute(select(Car).where(Car.id == car_id))).scalar_one()
        assert car.vin == plain_vin


@pytest.mark.asyncio
async def test_update_car(authed_client):
    create = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 77.0,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
        headers=csrf_headers(authed_client),
    )
    car_id = create.json()["id"]

    r = await authed_client.put(
        f"/api/cars/{car_id}",
        json={"model": "Tavascan", "battery_kwh": 82.0},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "Tavascan"
    assert body["battery_kwh"] == 82.0
    assert body["make"] == "Cupra"  # untouched


@pytest.mark.asyncio
async def test_update_car_can_set_vin_to_none(authed_client, test_sessionmaker):
    create = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "vin": "TESTVIN0000000088",
            "battery_kwh": 77.0,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
        headers=csrf_headers(authed_client),
    )
    car_id = create.json()["id"]

    r = await authed_client.put(
        f"/api/cars/{car_id}",
        json={"vin": None},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200
    assert r.json()["vin"] is None


@pytest.mark.asyncio
async def test_delete_car(authed_client):
    create = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 77.0,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
        headers=csrf_headers(authed_client),
    )
    car_id = create.json()["id"]

    r = await authed_client.delete(
        f"/api/cars/{car_id}", headers=csrf_headers(authed_client)
    )
    assert r.status_code == 204

    r = await authed_client.get(f"/api/cars/{car_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cross_user_isolation(app, test_sessionmaker):
    """User A cannot read or modify user B's cars."""
    from httpx import ASGITransport, AsyncClient

    from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME, make_serializer
    from plugtrack.security.csrf import CSRF_COOKIE_NAME
    from plugtrack.models import User
    from plugtrack.security.crypto import hash_password
    from plugtrack.services.auth_service import bootstrap_user

    async with app.router.lifespan_context(app):
        async with test_sessionmaker() as session:
            user_a = await bootstrap_user(session, "alice", "test-password-12chars")
            # bootstrap_user refuses if any user exists; create user B
            # directly via the model so we can prove isolation.
            user_b = User(username="bob", password_hash=hash_password("test-password-12chars"))
            session.add(user_b)
            await session.commit()
            await session.refresh(user_b)

        serializer = make_serializer("test-secret-key-for-tests-only-padding-padding")
        token_a = serializer.dumps({"user_id": user_a.id})
        token_b = serializer.dumps({"user_id": user_b.id})

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client_a, AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client_b:
            client_a.cookies.set(SESSION_COOKIE_NAME, token_a)
            client_b.cookies.set(SESSION_COOKIE_NAME, token_b)
            # Prime CSRF for both.
            await client_a.get("/api/cars")
            await client_b.get("/api/cars")

            csrf_a = {"X-CSRF-Token": client_a.cookies.get(CSRF_COOKIE_NAME, "")}
            csrf_b = {"X-CSRF-Token": client_b.cookies.get(CSRF_COOKIE_NAME, "")}

            # User A creates a car.
            r = await client_a.post(
                "/api/cars",
                json={
                    "make": "Cupra",
                    "model": "Born",
                    "battery_kwh": 77.0,
                    "nominal_efficiency_mi_per_kwh": 3.6,
                },
                headers=csrf_a,
            )
            assert r.status_code == 201
            car_a_id = r.json()["id"]

            # User B can't see it in the list.
            r = await client_b.get("/api/cars")
            assert r.status_code == 200
            assert r.json() == []

            # User B can't fetch it directly.
            r = await client_b.get(f"/api/cars/{car_a_id}")
            assert r.status_code == 404

            # User B can't update it.
            r = await client_b.put(
                f"/api/cars/{car_a_id}",
                json={"model": "hacked"},
                headers=csrf_b,
            )
            assert r.status_code == 404

            # User B can't delete it.
            r = await client_b.delete(
                f"/api/cars/{car_a_id}",
                headers=csrf_b,
            )
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# VIN masking + owner-gated reveal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_cars_masks_vin(authed_client):
    """List and get payloads must carry the masked VIN, not the plaintext."""
    await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "vin": "VSSZZZK1ZNP123456",
            "battery_kwh": 58,
            "nominal_efficiency_mi_per_kwh": 3.8,
        },
        headers=csrf_headers(authed_client),
    )
    r = await authed_client.get("/api/cars")
    assert r.status_code == 200
    vin = r.json()[0]["vin"]
    assert vin is not None
    assert "VSSZZZK1ZNP" not in vin          # body hidden
    assert vin.endswith("23456")             # last 5 preserved
    assert vin != "VSSZZZK1ZNP123456"        # not the full string


@pytest.mark.asyncio
async def test_reveal_vin_returns_full_for_owner(authed_client):
    """The reveal endpoint returns the full plaintext VIN to the owner."""
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "vin": "VSSZZZK1ZNP123456",
            "battery_kwh": 58,
            "nominal_efficiency_mi_per_kwh": 3.8,
        },
        headers=csrf_headers(authed_client),
    )
    cid = r.json()["id"]
    r = await authed_client.get(f"/api/cars/{cid}/vin")
    assert r.status_code == 200
    assert r.json()["vin"] == "VSSZZZK1ZNP123456"


@pytest.mark.asyncio
async def test_reveal_vin_rejects_non_owner(app, authed_client, other_user_headers):
    """The reveal endpoint returns 404 when a different user requests the VIN."""
    from httpx import ASGITransport, AsyncClient
    from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME

    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "vin": "VSSZZZK1ZNP123456",
            "battery_kwh": 58,
            "nominal_efficiency_mi_per_kwh": 3.8,
        },
        headers=csrf_headers(authed_client),
    )
    cid = r.json()["id"]
    # Send the request as the other user via a fresh client with their cookie.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as other_client:
        other_client.cookies.set(
            SESSION_COOKIE_NAME,
            other_user_headers[SESSION_COOKIE_NAME],
        )
        r = await other_client.get(f"/api/cars/{cid}/vin")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# _mask_vin unit tests — privacy boundary regression
# ---------------------------------------------------------------------------


def test_mask_vin_none_returns_none():
    from plugtrack.api.routes.cars import _mask_vin
    assert _mask_vin(None) is None


def test_mask_vin_empty_string_returns_none():
    from plugtrack.api.routes.cars import _mask_vin
    assert _mask_vin("") is None


def test_mask_vin_short_string_fully_masked():
    """A VIN of 3 chars must be returned fully masked — no original chars."""
    from plugtrack.api.routes.cars import _mask_vin
    result = _mask_vin("ABC")
    assert result == "···"
    assert "A" not in result
    assert "B" not in result
    assert "C" not in result


def test_mask_vin_exactly_five_chars_fully_masked():
    """A VIN of exactly 5 chars must be fully masked, not partially revealed."""
    from plugtrack.api.routes.cars import _mask_vin
    result = _mask_vin("ABCDE")
    assert result == "·····"


def test_mask_vin_standard_17_char_vin():
    """A standard 17-char VIN keeps its last 5 and masks the first 12."""
    from plugtrack.api.routes.cars import _mask_vin
    vin = "VSSZZZK1ZNP123456"
    result = _mask_vin(vin)
    assert result is not None
    assert result.endswith("23456")
    assert len(result) == 17
    # First 12 chars must all be the middle dot (·, U+00B7).
    assert result[:12] == "·" * 12


# ---------------------------------------------------------------------------
# Defense-in-depth: reject mask characters in VIN update payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_car_rejects_masked_vin(authed_client, test_sessionmaker):
    """PUT /api/cars/{id} with a mask-character VIN must return 400
    and must NOT overwrite the stored VIN."""
    from plugtrack.models import Car
    from sqlalchemy import select

    # Create a car with a known full VIN.
    plain_vin = "VSSZZZK1ZNP999999"
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "vin": plain_vin,
            "battery_kwh": 77.0,
            "nominal_efficiency_mi_per_kwh": 3.6,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    car_id = r.json()["id"]

    # Attempt to update with a VIN that contains the mask character (·, U+00B7).
    masked_vin = "············99999"
    r = await authed_client.put(
        f"/api/cars/{car_id}",
        json={"vin": masked_vin},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 400, r.text
    assert "mask" in r.json()["detail"].lower()

    # The stored VIN must still be the original plaintext.
    async with test_sessionmaker() as session:
        car = (await session.execute(select(Car).where(Car.id == car_id))).scalar_one()
        assert car.vin == plain_vin


# ---------------------------------------------------------------------------
# Car name + display_name (Task 1 / Task 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_car_with_name_returns_name_and_display_name(authed_client):
    """POST /api/cars with name= returns name and display_name equal to name."""
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 58.0,
            "nominal_efficiency_mi_per_kwh": 3.5,
            "name": "Daily",
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Daily"
    assert body["display_name"] == "Daily"


@pytest.mark.asyncio
async def test_create_car_without_name_display_name_is_make_model(authed_client):
    """POST /api/cars without name → display_name falls back to '{make} {model}'."""
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 58.0,
            "nominal_efficiency_mi_per_kwh": 3.5,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] is None
    assert body["display_name"] == "Cupra Born"


@pytest.mark.asyncio
async def test_update_car_name(authed_client):
    """PUT /api/cars/{id} with name updates it; display_name follows."""
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 58.0,
            "nominal_efficiency_mi_per_kwh": 3.5,
        },
        headers=csrf_headers(authed_client),
    )
    car_id = r.json()["id"]

    r = await authed_client.put(
        f"/api/cars/{car_id}",
        json={"name": "Weekend Warrior"},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Weekend Warrior"
    assert body["display_name"] == "Weekend Warrior"


# ---------------------------------------------------------------------------
# Delete protection (Task 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_car_with_sessions_returns_409(authed_client, test_sessionmaker):
    """DELETE a car that has charging sessions must return 409 with the count."""
    from datetime import date as date_cls
    from plugtrack.models import Car, ChargingSession, User
    from sqlalchemy import select

    # Create a car via the API.
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 58.0,
            "nominal_efficiency_mi_per_kwh": 3.5,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    car_id = r.json()["id"]

    # Retrieve user_id from db so we can insert a ChargingSession directly.
    async with test_sessionmaker() as session:
        car = (await session.execute(select(Car).where(Car.id == car_id))).scalar_one()
        user_id = car.user_id

        session.add(
            ChargingSession(
                user_id=user_id,
                car_id=car_id,
                date=date_cls(2024, 1, 1),
                start_soc=20,
                end_soc=80,
                kwh_added=30.0,
                source="manual",
            )
        )
        await session.commit()

    r = await authed_client.delete(
        f"/api/cars/{car_id}", headers=csrf_headers(authed_client)
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "1" in detail
    assert "charges" in detail.lower()


@pytest.mark.asyncio
async def test_delete_car_without_sessions_removes_mileage_year_rows(
    authed_client, test_sessionmaker
):
    """DELETE a zero-session car deletes its car_mileage_year rows and returns 204."""
    from datetime import date as date_cls
    from plugtrack.models import Car, CarMileageYear
    from sqlalchemy import select

    # Create a car via the API.
    r = await authed_client.post(
        "/api/cars",
        json={
            "make": "Cupra",
            "model": "Born",
            "battery_kwh": 58.0,
            "nominal_efficiency_mi_per_kwh": 3.5,
        },
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    car_id = r.json()["id"]

    # Insert a CarMileageYear row for this car directly.
    async with test_sessionmaker() as session:
        car = (await session.execute(select(Car).where(Car.id == car_id))).scalar_one()
        user_id = car.user_id

        session.add(
            CarMileageYear(
                user_id=user_id,
                car_id=car_id,
                period_start_date=date_cls(2024, 1, 1),
                period_end_date=date_cls(2025, 1, 1),
                opening_odometer_km=10000.0,
            )
        )
        await session.commit()

    # Delete should succeed with 204.
    r = await authed_client.delete(
        f"/api/cars/{car_id}", headers=csrf_headers(authed_client)
    )
    assert r.status_code == 204, r.text

    # Confirm car_mileage_year rows are gone.
    async with test_sessionmaker() as session:
        rows = (
            await session.execute(
                select(CarMileageYear).where(CarMileageYear.car_id == car_id)
            )
        ).scalars().all()
    assert rows == [], f"Expected no car_mileage_year rows, found {len(rows)}"


@pytest.mark.asyncio
async def test_delete_another_users_car_returns_404(app, test_sessionmaker):
    """Attempting to delete a car owned by a different user returns 404."""
    from httpx import ASGITransport, AsyncClient
    from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME, make_serializer
    from plugtrack.security.csrf import CSRF_COOKIE_NAME
    from plugtrack.models import User
    from plugtrack.security.crypto import hash_password
    from plugtrack.services.auth_service import bootstrap_user

    async with app.router.lifespan_context(app):
        async with test_sessionmaker() as session:
            user_a = await bootstrap_user(session, "alice", "test-password-12chars")
            user_b = User(
                username="bob",
                password_hash=hash_password("test-password-12chars"),
            )
            session.add(user_b)
            await session.commit()
            await session.refresh(user_b)

        serializer = make_serializer("test-secret-key-for-tests-only-padding-padding")
        token_a = serializer.dumps({"user_id": user_a.id})
        token_b = serializer.dumps({"user_id": user_b.id})

        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client_a, AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client_b:
            client_a.cookies.set(SESSION_COOKIE_NAME, token_a)
            client_b.cookies.set(SESSION_COOKIE_NAME, token_b)

            # Prime CSRF for both.
            await client_a.get("/api/settings")
            await client_b.get("/api/settings")

            csrf_a = {"X-CSRF-Token": client_a.cookies.get(CSRF_COOKIE_NAME, "")}
            csrf_b = {"X-CSRF-Token": client_b.cookies.get(CSRF_COOKIE_NAME, "")}

            # User A creates a car.
            r = await client_a.post(
                "/api/cars",
                json={
                    "make": "Cupra",
                    "model": "Born",
                    "battery_kwh": 77.0,
                    "nominal_efficiency_mi_per_kwh": 3.6,
                },
                headers=csrf_a,
            )
            assert r.status_code == 201
            car_a_id = r.json()["id"]

            # User B cannot delete User A's car.
            r = await client_b.delete(
                f"/api/cars/{car_a_id}",
                headers=csrf_b,
            )
            assert r.status_code == 404


# ---------------------------------------------------------------------------
# Task 13: GET /{car_id}/lifetime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_car_lifetime_basic(authed_client, test_sessionmaker):
    """GET /api/cars/{id}/lifetime returns lifetime stats for the car."""
    from datetime import date as date_cls
    from plugtrack.models import Car, ChargingSession, User
    from sqlalchemy import select

    # Create car via API
    r = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born",
              "battery_kwh": 58.0, "nominal_efficiency_mi_per_kwh": 3.5},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201, r.text
    car_id = r.json()["id"]

    async with test_sessionmaker() as session:
        car = (await session.execute(
            select(Car).where(Car.id == car_id)
        )).scalar_one()
        user_id = car.user_id
        session.add(ChargingSession(
            user_id=user_id, car_id=car_id,
            date=date_cls(2026, 3, 1), start_soc=20, end_soc=80,
            kwh_added=10.0, charging_type="ac", charging_mode="manual",
            cost_pence=200, cost_basis="home_rate", source="manual",
        ))
        await session.commit()

    r = await authed_client.get(f"/api/cars/{car_id}/lifetime")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "ownership_span" in body
    assert body["ownership_span"]["first"] == "2026-03-01"
    assert body["total_sessions"] == 1
    assert body["total_kwh"] == pytest.approx(10.0)
    assert body["total_cost_pence"] == 200
    assert "home_public" in body


@pytest.mark.asyncio
async def test_car_lifetime_404_for_other_user(app, authed_client, test_sessionmaker):
    """GET /api/cars/{id}/lifetime returns 404 for another user's car."""
    from httpx import ASGITransport, AsyncClient
    from plugtrack.api.auth_middleware import SESSION_COOKIE_NAME, make_serializer
    from plugtrack.models import User
    from plugtrack.security.crypto import hash_password

    # Create a car as authed_client (user A)
    r = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born",
              "battery_kwh": 58.0, "nominal_efficiency_mi_per_kwh": 3.5},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 201
    car_id = r.json()["id"]

    # Create user B and request the lifetime endpoint as them
    async with test_sessionmaker() as session:
        user_b = User(username="other_b", password_hash=hash_password("test-password-12chars"))
        session.add(user_b)
        await session.commit()
        await session.refresh(user_b)
        user_b_id = user_b.id

    serializer = make_serializer("test-secret-key-for-tests-only-padding-padding")
    token_b = serializer.dumps({"user_id": user_b_id})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as other:
        other.cookies.set(SESSION_COOKIE_NAME, token_b)
        r = await other.get(f"/api/cars/{car_id}/lifetime")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_car_lifetime_archived_car(authed_client, test_sessionmaker):
    """GET /api/cars/{id}/lifetime works for archived (active=False) cars."""
    from datetime import date as date_cls
    from plugtrack.models import Car, ChargingSession, User
    from sqlalchemy import select

    # Create car via API, then archive it
    r = await authed_client.post(
        "/api/cars",
        json={"make": "Cupra", "model": "Born",
              "battery_kwh": 58.0, "nominal_efficiency_mi_per_kwh": 3.5},
        headers=csrf_headers(authed_client),
    )
    car_id = r.json()["id"]

    async with test_sessionmaker() as session:
        car = (await session.execute(
            select(Car).where(Car.id == car_id)
        )).scalar_one()
        user_id = car.user_id
        session.add(ChargingSession(
            user_id=user_id, car_id=car_id,
            date=date_cls(2025, 6, 1), start_soc=10, end_soc=90,
            kwh_added=50.0, charging_type="ac", charging_mode="manual",
            cost_pence=1000, cost_basis="home_rate", source="manual",
        ))
        await session.commit()

    # Archive the car
    r = await authed_client.put(
        f"/api/cars/{car_id}",
        json={"active": False},
        headers=csrf_headers(authed_client),
    )
    assert r.status_code == 200
    assert r.json()["active"] is False

    # Lifetime should still work
    r = await authed_client.get(f"/api/cars/{car_id}/lifetime")
    assert r.status_code == 200
    body = r.json()
    assert body["total_sessions"] == 1
    assert body["total_kwh"] == pytest.approx(50.0)
