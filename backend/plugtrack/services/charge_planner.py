"""Home charge planner — pure computation + DB-backed inputs helper.

The module is split in two:

1. `compute_charge_plan` — a **pure, DB-free** function that takes all the
   resolved inputs and returns a `ChargePlan` dataclass.  This is the only
   piece that contains multi-night scheduling math, so it is easy to unit
   test in isolation.

2. `resolve_plan_inputs` — an **async** helper that reads the DB (settings,
   home location, recent home AC sessions) and produces the arguments that
   `compute_charge_plan` needs.

The route module (`api/routes/charge_plan.py`) calls both in sequence.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car, ChargingSession, Location, Setting


# ---------------------------------------------------------------------------
# Pure computation
# ---------------------------------------------------------------------------


@dataclass
class NightEntry:
    index: int
    minutes: int
    end_soc: int
    finish_at: str  # "HH:MM"


@dataclass
class ChargePlan:
    kwh_needed: float
    total_minutes: int
    nights: list[NightEntry]
    nights_needed: int
    finish_at: str  # "HH:MM"
    fits_one_window: bool
    cost_pence: int


def _hhmm(total_minutes: int) -> str:
    """Convert an absolute minutes-since-midnight value to 'HH:MM' string.

    The value may exceed 1440 (crosses midnight); we take mod 1440 to
    always land within the 24-hour clock.
    """
    total_minutes = total_minutes % 1440
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}"


def _parse_hhmm(s: str) -> int:
    """Parse 'HH:MM' → minutes since midnight."""
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def compute_charge_plan(
    *,
    start_soc: int,
    target_soc: int,
    battery_kwh: float,
    power_kw: float,
    window_minutes: int,
    window_start_str: str,
    home_rate_p_per_kwh: float,
    is_free: bool,
) -> ChargePlan:
    """Compute the multi-night home charge plan.

    Parameters
    ----------
    start_soc, target_soc:
        Integer SoC percentages (0-100). Caller must ensure target > start.
    battery_kwh:
        Usable battery capacity in kWh.
    power_kw:
        Charging power in kW (> 0).
    window_minutes:
        Length of one nightly charge window in minutes (already corrected
        for the midnight crossing by the caller).
    window_start_str:
        Window start time as "HH:MM"; used to compute per-night finish_at.
    home_rate_p_per_kwh:
        Cost rate in pence per kWh; 0.0 when is_free.
    is_free:
        When True, cost_pence is 0 regardless of rate.
    """
    kwh_needed = round((target_soc - start_soc) / 100.0 * battery_kwh, 2)
    total_minutes = round(kwh_needed / power_kw * 60)

    window_start_abs = _parse_hhmm(window_start_str)

    # Build per-night entries.
    nights: list[NightEntry] = []
    remaining_minutes = total_minutes
    cumulative_kwh = 0.0
    night_index = 1

    while remaining_minutes > 0:
        night_minutes = min(remaining_minutes, window_minutes)
        cumulative_kwh += power_kw * (night_minutes / 60.0)
        # end_soc: SoC gained so far, capped at target_soc.
        raw_end_soc = start_soc + int(round(cumulative_kwh / battery_kwh * 100))
        end_soc = min(raw_end_soc, target_soc)
        # finish_at: window_start + night_minutes (mod 24h).
        finish_abs = (window_start_abs + night_minutes) % 1440
        finish_at = _hhmm(finish_abs)

        nights.append(
            NightEntry(
                index=night_index,
                minutes=night_minutes,
                end_soc=end_soc,
                finish_at=finish_at,
            )
        )
        remaining_minutes -= night_minutes
        night_index += 1

    nights_needed = len(nights)
    final_finish_at = nights[-1].finish_at if nights else window_start_str
    fits_one_window = total_minutes <= window_minutes

    if is_free:
        cost_pence = 0
    else:
        cost_pence = round(kwh_needed * home_rate_p_per_kwh)

    return ChargePlan(
        kwh_needed=kwh_needed,
        total_minutes=total_minutes,
        nights=nights,
        nights_needed=nights_needed,
        finish_at=final_finish_at,
        fits_one_window=fits_one_window,
        cost_pence=cost_pence,
    )


# ---------------------------------------------------------------------------
# DB-backed inputs resolver
# ---------------------------------------------------------------------------


@dataclass
class PlanInputs:
    battery_kwh: float
    power_kw: float
    power_basis: str          # "history" | "fallback"
    sample_size: int
    window_start_str: str
    window_end_str: str
    window_minutes: int
    home_rate_p_per_kwh: float
    is_free: bool


async def _get_setting(session: AsyncSession, key: str, default: str) -> str:
    row = await session.get(Setting, key)
    if row is None or row.value is None:
        return default
    return row.value


async def resolve_plan_inputs(
    session: AsyncSession,
    car: Car,
    user_id: int,
) -> PlanInputs:
    """Read settings, home location, and recent home AC sessions from the DB.

    Returns a `PlanInputs` with everything `compute_charge_plan` needs.
    Raises `ValueError` with a human-readable message when required inputs
    are missing or invalid (the route maps these to 400 HTTPExceptions).
    """
    battery_kwh = float(car.battery_kwh)
    if battery_kwh <= 0:
        raise ValueError("car has no usable battery capacity (battery_kwh <= 0)")

    # ---- Window settings ----
    window_start_str = await _get_setting(
        session, "home_charge_window_start", "23:45"
    )
    window_end_str = await _get_setting(
        session, "home_charge_window_end", "07:15"
    )
    fallback_kw_str = await _get_setting(
        session, "home_charge_fallback_kw", "7.4"
    )
    try:
        fallback_kw = float(fallback_kw_str)
    except (TypeError, ValueError):
        fallback_kw = 7.4

    # window_minutes — crosses midnight so end < start; add 1440 to normalise.
    def _parse(s: str) -> int:
        h, m = s.split(":")
        return int(h) * 60 + int(m)

    ws = _parse(window_start_str)
    we = _parse(window_end_str)
    window_minutes = (we - ws) % 1440  # always positive; crosses midnight → add 1440
    if window_minutes == 0:
        window_minutes = 1440  # degenerate: full-day window

    # ---- Home location (for rate resolution) ----
    home_loc_result = await session.execute(
        select(Location).where(
            Location.user_id == user_id,
            Location.is_home.is_(True),
        )
    )
    home_loc: Optional[Location] = home_loc_result.scalars().first()

    # Resolve home rate / is_free.
    if home_loc is not None and home_loc.is_free:
        is_free = True
        home_rate_p_per_kwh = 0.0
    elif home_loc is not None and home_loc.default_cost_per_kwh_p is not None:
        is_free = False
        home_rate_p_per_kwh = float(home_loc.default_cost_per_kwh_p)
    else:
        is_free = False
        rate_str = await _get_setting(session, "default_home_rate_p_per_kwh", "7.5")
        try:
            home_rate_p_per_kwh = float(rate_str)
        except (TypeError, ValueError):
            home_rate_p_per_kwh = 7.5

    # ---- Recent home AC sessions for power derivation ----
    # We need sessions where:
    #   - linked Location has is_home=True
    #   - charging_type == 'ac'
    #   - both charge_start_at and charge_end_at are set
    #   - kwh_added > 0
    #   - duration > 0 (i.e., end > start)
    # Take the most recent 10 ordered by date desc.
    if home_loc is not None:
        recent_stmt = (
            select(ChargingSession)
            .join(Location, ChargingSession.location_id == Location.id)
            .where(
                ChargingSession.user_id == user_id,
                Location.is_home.is_(True),
                ChargingSession.charging_type == "ac",
                ChargingSession.charge_start_at.is_not(None),
                ChargingSession.charge_end_at.is_not(None),
                ChargingSession.kwh_added > 0,
            )
            .order_by(desc(ChargingSession.date), desc(ChargingSession.id))
            .limit(10)
        )
        result = await session.execute(recent_stmt)
        candidates = result.scalars().all()
    else:
        candidates = []

    # Compute effective_kw per session; filter out zero-duration rows.
    effective_kws: list[float] = []
    for cs in candidates:
        duration_hours = (
            cs.charge_end_at - cs.charge_start_at
        ).total_seconds() / 3600.0
        if duration_hours <= 0:
            continue
        effective_kws.append(cs.kwh_added / duration_hours)

    if len(effective_kws) >= 3:
        power_kw = statistics.median(effective_kws)
        power_basis = "history"
        sample_size = len(effective_kws)
    else:
        power_kw = fallback_kw
        power_basis = "fallback"
        sample_size = 0

    if power_kw <= 0:
        raise ValueError("resolved charging power is 0 or negative")

    return PlanInputs(
        battery_kwh=battery_kwh,
        power_kw=round(power_kw, 2),
        power_basis=power_basis,
        sample_size=sample_size,
        window_start_str=window_start_str,
        window_end_str=window_end_str,
        window_minutes=window_minutes,
        home_rate_p_per_kwh=home_rate_p_per_kwh,
        is_free=is_free,
    )
