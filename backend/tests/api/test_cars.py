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
