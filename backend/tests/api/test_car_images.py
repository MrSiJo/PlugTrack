"""GET /api/cars/{id}/image route tests.

The route streams an on-disk PNG written by pycupra to
`<PYCUPRA_IMAGE_DIR>/image_<VIN>_<view>.png`. Tests pin
`PYCUPRA_IMAGE_DIR` to `tmp_path` and write a fixture PNG so the route
has something to serve.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from plugtrack.models import Car


# Smallest valid 1x1 transparent PNG.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63000100000005000100"
    "5d0c2db40000000049454e44ae426082"
)


async def _seed_car(test_sessionmaker, vin: str = "VSSZZZK19SP001843") -> int:
    from plugtrack.models import User
    from sqlalchemy import select

    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="cupra_connect",
            active=True,
        )
        car.vin = vin  # property setter encrypts
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car.id


@pytest.mark.asyncio
async def test_image_requires_auth(seeded_client):
    r = await seeded_client.get("/api/cars/1/image")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_image_streams_when_present(
    authed_client, test_sessionmaker, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PYCUPRA_IMAGE_DIR", str(tmp_path))
    car_id = await _seed_car(test_sessionmaker)
    img = tmp_path / "image_VSSZZZK19SP001843_front_cropped.png"
    img.write_bytes(_PNG_BYTES)

    r = await authed_client.get(f"/api/cars/{car_id}/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _PNG_BYTES


@pytest.mark.asyncio
async def test_image_404_when_missing(
    authed_client, test_sessionmaker, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PYCUPRA_IMAGE_DIR", str(tmp_path))
    car_id = await _seed_car(test_sessionmaker)

    r = await authed_client.get(f"/api/cars/{car_id}/image")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_image_rejects_invalid_view(
    authed_client, test_sessionmaker, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PYCUPRA_IMAGE_DIR", str(tmp_path))
    car_id = await _seed_car(test_sessionmaker)

    r = await authed_client.get(f"/api/cars/{car_id}/image?view=secret")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_image_404_when_no_vin(
    authed_client, test_sessionmaker, tmp_path, monkeypatch,
):
    monkeypatch.setenv("PYCUPRA_IMAGE_DIR", str(tmp_path))
    from plugtrack.models import User
    from sqlalchemy import select

    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
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
        car_id = car.id

    r = await authed_client.get(f"/api/cars/{car_id}/image")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_image_other_user_404(authed_client, test_sessionmaker, tmp_path, monkeypatch):
    monkeypatch.setenv("PYCUPRA_IMAGE_DIR", str(tmp_path))
    from plugtrack.models import User
    from sqlalchemy import select

    # Create a second user + car the active session has no business seeing.
    async with test_sessionmaker() as s:
        other = User(username="bob", password_hash="x")
        s.add(other)
        await s.commit()
        await s.refresh(other)
        car = Car(
            user_id=other.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="cupra_connect",
            active=True,
        )
        car.vin = "OTHERVIN12345"
        s.add(car)
        await s.commit()
        await s.refresh(car)
        bob_car_id = car.id

    img = tmp_path / "image_OTHERVIN12345_front_cropped.png"
    img.write_bytes(_PNG_BYTES)

    r = await authed_client.get(f"/api/cars/{bob_car_id}/image")
    # Active user is alice; bob's car must 404, not leak.
    assert r.status_code == 404
