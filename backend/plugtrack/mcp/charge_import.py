"""Validated, two-phase imports of extraction records supplied by Aster.

No images, model calls or Telegram staging are involved. Proposals and successful
receipts share the MCP core's process-local ten-minute token lifetime.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car
from ..services.screenshot_commit import (
    PreviewChangedError,
    commit_merged_session,
    preview_merged_session,
    preview_values,
)
from ..services.screenshot_correlation import correlate_batch
from ..services.screenshot_extraction import Extraction

Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Percentage = Annotated[int, Field(ge=0, le=100)]
Fraction = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ChargeExtraction(BaseModel):
    """One screenshot reading. Times require an explicit UTC offset; money is pence."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source: str = Field(default="unknown", max_length=64)
    has_cost: bool = False
    energy_kwh: Nonnegative | None = None
    cost_total_pence: Annotated[int, Field(ge=0)] | None = None
    cost_per_kwh_pence: Nonnegative | None = None
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    soc_start: Percentage | None = None
    soc_end: Percentage | None = None
    location_name: str | None = Field(default=None, max_length=128)
    location_address: str | None = Field(default=None, max_length=512)
    network: str | None = Field(default=None, max_length=128)
    peak_kw: Nonnegative | None = None
    confidence: Fraction = 0.0
    odometer: Nonnegative | None = None
    odometer_unit: Literal["mi", "km"] | None = None
    location_short_name: str | None = Field(default=None, max_length=128)
    actual_charge_seconds: Annotated[int, Field(gt=0)] | None = None
    power_curve: list[tuple[Fraction, Nonnegative]] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def coherent_reading(self):
        if self.start_at and self.end_at and self.end_at < self.start_at:
            raise ValueError("end_at must not precede start_at")
        if (
            self.soc_start is not None
            and self.soc_end is not None
            and self.soc_end < self.soc_start
        ):
            raise ValueError("soc_end must not be lower than soc_start")
        if self.odometer is not None and self.odometer_unit is None:
            raise ValueError("odometer_unit is required with odometer")
        if self.cost_total_pence is not None or self.cost_per_kwh_pence is not None:
            self.has_cost = True
        return self


async def owned_active_car(session: AsyncSession, user_id: int, car_id: int) -> Car | None:
    return (
        await session.execute(
            select(Car).where(Car.id == car_id, Car.user_id == user_id, Car.active.is_(True))
        )
    ).scalar_one_or_none()


async def list_cars(session: AsyncSession, user_id: int) -> list[dict]:
    cars = (
        await session.execute(select(Car).where(Car.user_id == user_id).order_by(Car.id))
    ).scalars()
    return [
        dict(
            id=c.id,
            name=c.display_name,
            make=c.make,
            model=c.model,
            battery_kwh=c.battery_kwh,
            active=c.active,
        )
        for c in cars
    ]


async def propose_import_charge(
    session: AsyncSession, user_id: int, *, car_id: int, extractions: list[dict]
) -> dict:
    from . import tools

    if not isinstance(extractions, list) or not 1 <= len(extractions) <= 10:
        return {"error": "provide between 1 and 10 extraction records"}
    if await owned_active_car(session, user_id, car_id) is None:
        return {"error": "car not found, inactive, or not owned by this user"}
    try:
        records = [ChargeExtraction.model_validate(e) for e in extractions]
    except ValidationError as exc:
        # Report field paths/reasons, never echo input payloads or internal exceptions.
        return {
            "error": "invalid extraction",
            "details": [
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                for e in exc.errors(include_input=False, include_url=False)
            ],
        }
    # SQLite stores wall-clock timestamps without offsets. Canonicalize new
    # Aster records to the application's London convention before correlation.
    # Historical Telegram timestamps retain their original representation.
    london = ZoneInfo("Europe/London")
    for record in records:
        if record.start_at is not None:
            record.start_at = record.start_at.astimezone(london)
        if record.end_at is not None:
            record.end_at = record.end_at.astimezone(london)
    merged, unplaced = correlate_batch([Extraction(**r.model_dump(mode="json")) for r in records])
    if unplaced or not merged:
        return {
            "error": "each charge needs a timestamp; untimed readings must match one timed charge"
        }
    if len(merged) != 1:
        return {"error": "provide screenshots for exactly one charge per proposal"}
    previews = []
    reviewed_values = []
    warnings = []
    for item in merged:
        if item.end_at is not None and item.end_at < item.start_at:
            return {"error": "merged charge end_at must not precede start_at"}
        if item.energy_kwh is None and (item.soc_start is None or item.soc_end is None):
            return {"error": "charge needs energy_kwh or both soc_start and soc_end"}
        cs = await preview_merged_session(
            session, user_id=user_id, car_id=car_id, merged=item, source="aster"
        )
        reviewed_values.append(preview_values(cs))
        row = tools._session_to_dict(cs)
        row.update(
            car_id=car_id,
            charge_start_at=item.start_at.isoformat(),
            charge_end_at=item.end_at.isoformat() if item.end_at else None,
            location_name=item.location_name,
            confidence=item.confidence,
            actual_charge_seconds=cs.actual_charge_seconds,
            power_curve=cs.power_curve,
        )
        previews.append(row)
        if item.confidence < 0.8:
            warnings.append(
                "Extraction confidence is low or unspecified; check the screenshot details."
            )
        if cs.location_id is None and (item.location_name or item.location_address):
            warnings.append("Unmatched location will be saved as text; no geocoding will run.")
        if cs.cost_pence is None:
            warnings.append("Cost is unknown.")
    summary = (
        f"Import 1 charge for car #{car_id}: {merged[0].start_at.isoformat()}, "
        f"{previews[0]['kwh']} kWh, {previews[0]['cost'] or 'cost unknown'}. Confirm before saving."
    )
    token = tools._mint_token(
        user_id,
        "import_charge",
        {"car_id": car_id, "merged": merged, "reviewed_values": reviewed_values},
    )
    return dict(
        summary=summary,
        change_token=token,
        expires_in_seconds=tools._TOKEN_TTL_SECONDS,
        preview=previews,
        warnings=list(dict.fromkeys(warnings)),
    )


# Single-worker invariant allows a process-local lock. Serialize different
# proposals too: overlapping duplicate checks must not race between MCP calls.
_import_lock = asyncio.Lock()


async def commit_import(session: AsyncSession, user_id: int, token: str) -> dict:
    from . import tools

    async with _import_lock:
        entry = tools._CHANGE_STORE.get(token)
        error = tools._validate_token(token, user_id)
        if error is not None:
            # A receipt is only returned to its owner, inside the original TTL.
            if (
                entry
                and entry["user_id"] == user_id
                and entry.get("result")
                and error["error"] == "change token has already been used"
            ):
                return entry["result"].copy()
            return error
        data = entry["data"]
        if await owned_active_car(session, user_id, data["car_id"]) is None:
            return {"error": "car not found, inactive, or not owned by this user"}
        charge_ids = []
        duplicates = 0
        try:
            for merged, reviewed in zip(data["merged"], data["reviewed_values"], strict=True):
                cs = await commit_merged_session(
                    session,
                    user_id=user_id,
                    car_id=data["car_id"],
                    merged=merged,
                    source="aster",
                    geocode=False,
                    expected_values=reviewed,
                )
                if cs is None:
                    duplicates += 1
                else:
                    charge_ids.append(cs.id)
            await session.commit()
        except PreviewChangedError:
            await session.rollback()
            return {"error": "charge details changed since preview; propose and confirm again"}
        except Exception:
            await session.rollback()
            return {"error": "charge import failed; retry the confirmation"}
        result = dict(ok=True, charge_ids=charge_ids, duplicates_skipped=duplicates)
        entry["used"] = True
        entry["result"] = result
        return result.copy()
