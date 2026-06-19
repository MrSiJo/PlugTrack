"""Car CRUD routes.

All routes require auth (handled by AuthMiddleware) and mutating verbs
require CSRF (handled by CsrfMiddleware). Multi-user isolation: every
query filters by `user_id = request.state.user_id`. Hard delete is used
on DELETE — sessions/plug-ins cascade in Phase 4 onward; this fits the
single-user app shape better than soft-deleting.
"""
from __future__ import annotations

import logging
import os
from datetime import date as date_cls
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import Car
from ...services import mileage_tracking


logger = logging.getLogger(__name__)


# pycupra hard-codes images at `<base>/pycupra/image_<vin>_<view>.png`
# where `<base>` is `./www` relative to the worker's CWD when not running
# inside Home Assistant. We resolve the same directory here. Override
# with `PYCUPRA_IMAGE_DIR` for non-default deployments (e.g. compose
# mounts /app/www to a host volume).
_VALID_VIEWS = frozenset(
    {"front", "front_cropped", "rear", "side", "top", "rbcCable", "rbcFront"}
)


def _image_dir() -> Path:
    override = os.environ.get("PYCUPRA_IMAGE_DIR")
    if override:
        return Path(override)
    return Path("www") / "pycupra"


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


def _mask_vin(vin: str | None) -> str | None:
    """Return VIN with all but the last 5 characters replaced by · (U+00B7).

    The masked form is shown in list/get payloads. The full VIN is only
    returned by the owner-gated ``GET /api/cars/{id}/vin`` endpoint.

    Short VINs (5 chars or fewer) are fully masked so no characters are
    ever returned in the clear via the list/get endpoints.
    """
    if not vin:
        return None
    if len(vin) <= 5:
        return "·" * len(vin)
    return "·" * (len(vin) - 5) + vin[-5:]


def _to_payload(car: Car) -> CarPayload:
    return CarPayload(
        id=car.id,
        make=car.make,
        model=car.model,
        vin=_mask_vin(car.vin),  # masked — full VIN via GET /{id}/vin
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


class DiscoveredVehicle(BaseModel):
    vin: str
    model: Optional[str] = None
    year: Optional[str] = None


@router.post("/discover", response_model=list[DiscoveredVehicle])
async def discover_vehicles(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> list[DiscoveredVehicle]:
    """Authenticate against Cupra Connect with saved creds and list VINs.

    Reads `cupra_username` / `cupra_password` / `cupra_spin` from the
    settings catalogue, authenticates via the pycupra adapter, and
    returns each vehicle's VIN + model. Use this to populate the
    "Provider vehicle ID" picker on the Cars page so users don't need
    to look up the VIN manually.

    POST (not GET) because it performs a side-effecting upstream login
    against Cupra Connect, so it must be CSRF-protected like every other
    state-changing call. Auth + CSRF are enforced by the middleware.
    """
    _user_id(request)

    from pathlib import Path
    from sqlalchemy import select as _select
    from ...bootstrap import get_settings as _get_settings
    from ...models import Setting
    from ...plugins.pycupra.adapter import authenticate
    from ...plugins.pycupra.models import Credentials
    from ...security.crypto import decrypt_secret

    async def _read(key: str) -> Optional[str]:
        row = (await session.execute(
            _select(Setting).where(Setting.key == key)
        )).scalar_one_or_none()
        return row.value if row else None

    u_raw = await _read("cupra_username")
    p_raw = await _read("cupra_password")
    s_raw = await _read("cupra_spin")
    if not u_raw or not p_raw:
        raise HTTPException(
            status_code=400,
            detail="Save Cupra credentials in Settings before discovering vehicles.",
        )

    try:
        secret = _get_settings().app_secret_key
        username = decrypt_secret(u_raw, secret)
        password = decrypt_secret(p_raw, secret)
        spin = decrypt_secret(s_raw, secret) if s_raw else None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to decrypt Cupra credentials during discovery")
        raise HTTPException(
            status_code=500, detail="failed to decrypt stored credentials"
        ) from exc

    token_dir = Path(_get_settings().data_dir) / "pycupra"
    try:
        connection = await authenticate(
            Credentials(username=username, password=password, spin=spin),
            token_dir=token_dir,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cupra authentication failed during discovery")
        raise HTTPException(status_code=502, detail="vehicle discovery failed") from exc

    if not getattr(connection, "_user_id", None):
        raise HTTPException(
            status_code=502,
            detail="Cupra login returned no user_id — credentials likely invalid.",
        )

    try:
        await connection.get_vehicles()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Cupra get_vehicles failed during discovery")
        raise HTTPException(status_code=502, detail="vehicle discovery failed") from exc

    out: list[DiscoveredVehicle] = []
    raw = getattr(connection, "_vehicles", None)
    iterable = raw if isinstance(raw, list) else (list(raw.values()) if isinstance(raw, dict) else [])
    for v in iterable:
        vin = getattr(v, "vin", None) or getattr(v, "_vin", None)
        if not vin:
            continue
        out.append(DiscoveredVehicle(
            vin=str(vin),
            model=getattr(v, "model", None),
            year=str(getattr(v, "modelYear", "") or "") or None,
        ))
    return out


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


@router.get("/{car_id}/vin")
async def reveal_vin(
    car_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Return the full plaintext VIN for a car the caller owns.

    Only the authenticated owner can retrieve the full VIN; cross-user
    requests return 404 (via ``_get_owned``).
    """
    user_id = _user_id(request)
    car = await _get_owned(session, car_id, user_id)
    return {"vin": car.vin}


@router.get("/{car_id}/image")
async def get_car_image(
    car_id: int,
    request: Request,
    view: str = Query(default="front_cropped"),
    session: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Stream the locally-cached pycupra image for this car.

    pycupra writes images on every model-image refresh to
    `./www/pycupra/image_<VIN>_<view>.png` relative to the worker's CWD
    (overridable via `PYCUPRA_IMAGE_DIR`). 404 when the file isn't on
    disk yet — the frontend falls back to a placeholder.
    """
    user_id = _user_id(request)
    if view not in _VALID_VIEWS:
        raise HTTPException(
            status_code=400,
            detail=f"view must be one of {sorted(_VALID_VIEWS)}",
        )
    car = await _get_owned(session, car_id, user_id)
    vin = car.vin  # decrypts on the fly
    if not vin:
        raise HTTPException(status_code=404, detail="car has no VIN")
    file_path = _image_dir() / f"image_{vin}_{view}.png"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="image not cached yet")
    return FileResponse(
        path=file_path,
        media_type="image/png",
        # Browsers cache aggressively across a deploy if VIN+view is the
        # only key, so add a weak validator from mtime.
        headers={"Cache-Control": "private, max-age=300"},
    )


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


# ---------------------------------------------------------------------------
# Mileage tracking
#
# A user enables tracking by submitting a start date + opening odometer in
# miles (and optionally an annual cap). Closing odometers are derived from
# the latest `ChargingSession.odometer_at_session_km` at-or-before each
# anniversary, so re-syncs and edits to existing sessions naturally feed
# back into the historical totals.
# ---------------------------------------------------------------------------


class MileagePeriodPayload(BaseModel):
    period_start_date: date_cls
    period_end_date: date_cls
    opening_odometer_km: float
    closing_odometer_km: Optional[float] = None
    annual_mileage_target_km: Optional[float] = None


class CurrentMileagePeriodPayload(BaseModel):
    period_start_date: date_cls
    period_end_date: date_cls
    opening_odometer_km: float
    current_odometer_km: float
    annual_mileage_target_km: Optional[float] = None


class MileageStatusPayload(BaseModel):
    enabled: bool
    current_period: Optional[CurrentMileagePeriodPayload] = None
    history: list[MileagePeriodPayload]


class MileageConfigRequest(BaseModel):
    start_date: date_cls
    opening_miles: float = Field(ge=0, lt=1_000_000)
    annual_mileage_target_miles: Optional[float] = Field(
        default=None, gt=0, lt=1_000_000
    )


def _serialise_status(
    status: mileage_tracking.MileageStatus,
) -> MileageStatusPayload:
    current = (
        CurrentMileagePeriodPayload(
            period_start_date=status.current_period.period_start_date,
            period_end_date=status.current_period.period_end_date,
            opening_odometer_km=status.current_period.opening_odometer_km,
            current_odometer_km=status.current_period.current_odometer_km,
            annual_mileage_target_km=status.current_period.annual_mileage_target_km,
        )
        if status.current_period is not None
        else None
    )
    return MileageStatusPayload(
        enabled=status.enabled,
        current_period=current,
        history=[
            MileagePeriodPayload(
                period_start_date=h.period_start_date,
                period_end_date=h.period_end_date,
                opening_odometer_km=h.opening_odometer_km,
                closing_odometer_km=h.closing_odometer_km,
                annual_mileage_target_km=h.annual_mileage_target_km,
            )
            for h in status.history
        ],
    )


@router.get("/{car_id}/mileage", response_model=MileageStatusPayload)
async def get_mileage(
    car_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> MileageStatusPayload:
    user_id = _user_id(request)
    await _get_owned(session, car_id, user_id)
    status = await mileage_tracking.get_status(
        session, user_id=user_id, car_id=car_id
    )
    # `get_status` may have materialised a rollover, which writes new rows.
    await session.commit()
    return _serialise_status(status)


@router.put("/{car_id}/mileage", response_model=MileageStatusPayload)
async def put_mileage(
    car_id: int,
    request: Request,
    body: MileageConfigRequest,
    session: AsyncSession = Depends(get_db),
) -> MileageStatusPayload:
    user_id = _user_id(request)
    await _get_owned(session, car_id, user_id)
    status = await mileage_tracking.set_tracking(
        session,
        user_id=user_id,
        car_id=car_id,
        start_date=body.start_date,
        opening_miles=body.opening_miles,
        annual_mileage_target_miles=body.annual_mileage_target_miles,
    )
    await session.commit()
    return _serialise_status(status)


@router.delete("/{car_id}/mileage", status_code=204)
async def delete_mileage(
    car_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Response:
    user_id = _user_id(request)
    await _get_owned(session, car_id, user_id)
    await mileage_tracking.clear_tracking(
        session, user_id=user_id, car_id=car_id
    )
    await session.commit()
    return Response(status_code=204)
