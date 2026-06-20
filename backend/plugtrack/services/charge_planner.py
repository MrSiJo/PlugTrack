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

DC Capability model (3 tiers)
------------------------------
`build_dc_capability` returns a `DcCapability` object whose `power_at(soc)`
method resolves charging power in kW for a given SoC using three tiers:

  Tier 1 (curve):    Pool all power_curve points into 10% SoC bands.
                     Band capability = median of pooled points, capped at ceiling.
  Tier 2 (average):  For bands with no curve points, average the effective
                     power across all DC sessions whose [start_soc, end_soc]
                     range overlaps the band.  Effective power =
                     kwh_added / (actual_charge_seconds / 3600), falling
                     back to wall_seconds when actual is None.
  Tier 3 (modelled): For bands with no data at all, apply a fixed
                     ramp-then-taper shape scaled to ceiling.

Generic taper shape (fraction of ceiling per band):
  Band 0-10:  0.60   # warming up
  Band 10-20: 0.80   # approaching peak
  Band 20-30: 0.95   # near peak
  Band 30-40: 1.00   # peak region
  Band 40-50: 0.98
  Band 50-60: 0.90   # gentle taper begins
  Band 60-70: 0.75
  Band 70-80: 0.55
  Band 80-90: 0.35
  Band 90-100: 0.18  # thermal / BMS protection

These fractions are a plausible CCS DC curve based on published Born/ID.4 data;
they are intentionally conservative.  Loss factor is NOT applied here — callers
(estimate_scenario) apply loss.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car, ChargingSession, Location, Setting


# ---------------------------------------------------------------------------
# DC Capability model (pure, no DB)
# ---------------------------------------------------------------------------

# Generic DC ramp-then-taper fractions of ceiling, keyed by band lower bound.
# Band 0 → [0,10), band 10 → [10,20), ..., band 90 → [90,100].
_DC_TAPER_FRACTIONS: dict[int, float] = {
    0:  0.60,
    10: 0.80,
    20: 0.95,
    30: 1.00,
    40: 0.98,
    50: 0.90,
    60: 0.75,
    70: 0.55,
    80: 0.35,
    90: 0.18,
}


def _soc_band(soc: int) -> int:
    """Return the lower bound of the 10%-wide SoC band containing *soc*.

    Examples: 0→0, 9→0, 10→10, 59→50, 95→90, 100→90 (capped).
    """
    # SoC 100 belongs to the 90-100 band.
    return min((soc // 10) * 10, 90)


@dataclass
class DcSession:
    """Pure input struct for a single DC charging session."""

    start_soc: int
    end_soc: int
    kwh_added: float
    actual_charge_seconds: Optional[int]
    wall_seconds: Optional[int]
    power_curve: Optional[list]  # [[t_seconds, soc, power_kw], ...] or None


class DcCapability:
    """3-tier DC charging capability lookup.

    Created by `build_dc_capability`.  Call ``power_at(soc)`` to get
    ``(capability_kw, source_tag)`` where source_tag is one of
    "curve" | "average" | "modelled".
    """

    def __init__(
        self,
        ceiling: float,
        band_curve: dict[int, float],      # band → median curve power (pre-capped)
        band_average: dict[int, float],    # band → mean effective power (pre-capped)
    ) -> None:
        self.ceiling = ceiling
        self._band_curve = band_curve
        self._band_average = band_average

    def power_at(self, soc: int) -> tuple[float, str]:
        """Return ``(capability_kw, source_tag)`` for the band containing *soc*."""
        band = _soc_band(soc)

        # Tier 1: curve
        if band in self._band_curve:
            return min(self._band_curve[band], self.ceiling), "curve"

        # Tier 2: average
        if band in self._band_average:
            return min(self._band_average[band], self.ceiling), "average"

        # Tier 3: modelled
        fraction = _DC_TAPER_FRACTIONS.get(band, 0.18)
        return min(fraction * self.ceiling, self.ceiling), "modelled"


def build_dc_capability(
    *,
    battery_kwh: float,  # noqa: ARG001 — reserved for future net-energy normalization
    dc_sessions: list[DcSession],
    max_dc_kw: Optional[float],
) -> DcCapability:
    """Build a 3-tier DC capability model from historical DC sessions.

    Parameters
    ----------
    battery_kwh:
        Usable battery capacity (reserved; not currently used in the pure
        capability model but required by the spec interface for future
        normalization).
    dc_sessions:
        List of past DC charging sessions to learn from.
    max_dc_kw:
        Hardware ceiling from car.max_dc_kw.  When None, derived from
        observed data (max of curve points and effective averages).
    """
    # --- Pool curve points per SoC band (Tier 1 data) ---
    band_points: dict[int, list[float]] = {}
    for sess in dc_sessions:
        if not sess.power_curve:
            continue
        for triplet in sess.power_curve:
            if len(triplet) < 3:
                continue
            _t, soc_val, power_kw = triplet[0], triplet[1], triplet[2]
            band = _soc_band(int(soc_val))
            band_points.setdefault(band, []).append(float(power_kw))

    # Tier 1: median curve power per band (uncapped — ceiling applied in power_at).
    band_curve: dict[int, float] = {
        b: statistics.median(pts) for b, pts in band_points.items()
    }

    # --- Per-session effective power (used for Tier 2 and ceiling derivation) ---
    # Aligned 1-to-1 with dc_sessions; None when no valid time source.
    per_session_eff: list[Optional[float]] = []
    for sess in dc_sessions:
        if sess.actual_charge_seconds is not None and sess.actual_charge_seconds > 0:
            hours = sess.actual_charge_seconds / 3600.0
        elif sess.wall_seconds is not None and sess.wall_seconds > 0:
            hours = sess.wall_seconds / 3600.0
        else:
            per_session_eff.append(None)
            continue
        per_session_eff.append(sess.kwh_added / hours)

    # --- Tier 2: SoC-overlapping average per band ---
    band_average: dict[int, float] = {}
    for band in range(0, 100, 10):
        band_lo = band
        band_hi = band + 10
        overlapping_effs: list[float] = []
        for idx, sess in enumerate(dc_sessions):
            if sess.start_soc >= band_hi or sess.end_soc <= band_lo:
                continue  # no overlap with this band
            eff = per_session_eff[idx]
            if eff is not None:
                overlapping_effs.append(eff)
        if overlapping_effs:
            band_average[band] = statistics.mean(overlapping_effs)

    # --- Derive ceiling ---
    if max_dc_kw is not None:
        ceiling = float(max_dc_kw)
    else:
        # Observed ceiling: use band medians (already computed) and per-session
        # effective averages.  This is robust to transient single-point spikes
        # because medians smooth out outliers within each band.
        observed: list[float] = []
        observed.extend(band_curve.values())           # per-band curve medians
        observed.extend(v for v in per_session_eff if v is not None)
        ceiling = max(observed) if observed else 50.0  # bare minimum fallback

    return DcCapability(
        ceiling=ceiling,
        band_curve=band_curve,
        band_average=band_average,
    )


# ---------------------------------------------------------------------------
# Home charge plan — pure computation
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
