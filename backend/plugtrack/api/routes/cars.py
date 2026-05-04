"""Car CRUD routes.

All routes require auth (handled by AuthMiddleware) and mutating verbs
require CSRF (handled by CsrfMiddleware). Multi-user isolation: every
query filters by `user_id = request.state.user_id`. Hard delete is used
on DELETE — sessions/plug-ins cascade in Phase 4 onward; this fits the
single-user app shape better than soft-deleting.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Car


router = APIRouter(prefix="/api/cars", tags=["cars"])


class CarPayload(BaseModel):
    id: int
    make: str
    model: str
    vin: Optional[str] = None
    battery_kwh: float
    nominal_efficiency_mi_per_kwh: float
    provider: str
    provider_vehicle_id: Optional[str] = None
    active: bool


class CarCreateRequest(BaseModel):
    make: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)
    vin: Optional[str] = Field(default=None, max_length=32)
    battery_kwh: float = Field(gt=0, lt=1000)
    nominal_efficiency_mi_per_kwh: float = Field(gt=0, lt=20)
    provider: str = Field(default="cupra_connect", max_length=32)
    provider_vehicle_id: Optional[str] = Field(default=None, max_length=64)
    active: bool = True


class CarUpdateRequest(BaseModel):
    make: Optional[str] = Field(default=None, min_length=1, max_length=64)
    model: Optional[str] = Field(default=None, min_length=1, max_length=64)
    vin: Optional[str] = Field(default=None, max_length=32)
    battery_kwh: Optional[float] = Field(default=None, gt=0, lt=1000)
    nominal_efficiency_mi_per_kwh: Optional[float] = Field(default=None, gt=0, lt=20)
    provider: Optional[str] = Field(default=None, max_length=32)
    provider_vehicle_id: Optional[str] = Field(default=None, max_length=64)
    active: Optional[bool] = None


def _to_payload(car: Car) -> CarPayload:
    return CarPayload(
        id=car.id,
        make=car.make,
        model=car.model,
        vin=car.vin,  # property — decrypts on the fly
        battery_kwh=car.battery_kwh,
        nominal_efficiency_mi_per_kwh=car.nominal_efficiency_mi_per_kwh,
        provider=car.provider,
        provider_vehicle_id=car.provider_vehicle_id,
        active=car.active,
    )


def _user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@router.get("", response_model=list[CarPayload])
async def list_cars(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[CarPayload]:
    user_id = _user_id(request)
    result = await session.execute(
        select(Car).where(Car.user_id == user_id).order_by(Car.id)
    )
    return [_to_payload(c) for c in result.scalars().all()]


@router.post("", response_model=CarPayload, status_code=201)
async def create_car(
    request: Request,
    body: CarCreateRequest,
    session: AsyncSession = Depends(get_db),
) -> CarPayload:
    user_id = _user_id(request)
    car = Car(
        user_id=user_id,
        make=body.make,
        model=body.model,
        battery_kwh=body.battery_kwh,
        nominal_efficiency_mi_per_kwh=body.nominal_efficiency_mi_per_kwh,
        provider=body.provider,
        provider_vehicle_id=body.provider_vehicle_id,
        active=body.active,
    )
    car.vin = body.vin  # property setter encrypts
    session.add(car)
    await session.commit()
    await session.refresh(car)
    return _to_payload(car)


async def _get_owned(session: AsyncSession, car_id: int, user_id: int) -> Car:
    result = await session.execute(
        select(Car).where(Car.id == car_id, Car.user_id == user_id)
    )
    car = result.scalar_one_or_none()
    if car is None:
        raise HTTPException(status_code=404, detail="car not found")
    return car


@router.get("/{car_id}", response_model=CarPayload)
async def get_car(
    car_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> CarPayload:
    user_id = _user_id(request)
    car = await _get_owned(session, car_id, user_id)
    return _to_payload(car)


@router.put("/{car_id}", response_model=CarPayload)
async def update_car(
    car_id: int,
    request: Request,
    body: CarUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> CarPayload:
    user_id = _user_id(request)
    car = await _get_owned(session, car_id, user_id)

    data = body.model_dump(exclude_unset=True)
    if "vin" in data:
        car.vin = data.pop("vin")  # property setter encrypts
    for k, v in data.items():
        setattr(car, k, v)

    await session.commit()
    await session.refresh(car)
    return _to_payload(car)


@router.delete("/{car_id}", status_code=204)
async def delete_car(
    car_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Response:
    user_id = _user_id(request)
    car = await _get_owned(session, car_id, user_id)
    await session.delete(car)
    await session.commit()
    return Response(status_code=204)
