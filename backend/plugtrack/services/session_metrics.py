"""Per-session derived metrics — petrol-equivalent comparison.

Pure functions + a couple of DB-touching coroutines. The headline output
is a `SessionMetrics` describing miles travelled since the previous
session, the EV cost per mile, and the savings vs an equivalent petrol
trip.

Per-charge energy-based model: every session is judged on its own energy
alone. The formula is:

    eff   = observed_mi_per_kwh (calibrated from the car's odometer
            history via Method B) or car.nominal_efficiency_mi_per_kwh
    energy = kwh_calculated if not None else kwh_added
    miles  = energy * eff
    petrol_equivalent_p = round(miles * ppm)
    saved_vs_petrol_p   = petrol_equivalent_p - cost_pence
    comparison_basis    = "estimated"

This means each charge is self-contained — no double-counting across
interleaved charges, and list + detail always agree.

The odometer reading is still used to calibrate `eff` via
`_observed_mi_per_kwh`. It is also surfaced as an informational
`measured_miles_since_previous` field on the detail page (the genuine
odometer span vs the previous odometer-bearing session) but it does NOT
feed savings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car, ChargingSession, Setting


_LITRES_PER_UK_GALLON = 4.54609
_KM_PER_MILE = 1.609344


@dataclass
class SessionMetrics:
    miles_since_previous: Optional[float]
    cost_per_mile_p: Optional[float]
    petrol_ppm: Optional[float]
    petrol_equivalent_cost_p: Optional[int]
    savings_vs_petrol_p: Optional[int]
    petrol_price_p_per_litre: Optional[float]
    petrol_mpg: Optional[float]
    # How the comparison was derived: "estimated" (energy × efficiency) or
    # None (no comparison — missing energy, efficiency, or petrol settings).
    comparison_basis: Optional[str] = None
    # Chain wiring — kept for API consumers that read these fields; the
    # savings logic no longer populates them (all savings are per-charge
    # energy-based now), so chain_session_ids defaults to [session_id] and
    # chain_total_cost_pence / chain_anchor_id are always None.
    chain_session_ids: list[int] = field(default_factory=list)
    chain_total_cost_pence: Optional[int] = None
    chain_anchor_id: Optional[int] = None
    # Charge-mechanics metrics (derived; NULL when inputs are missing).
    # range_added_miles = (Δsoc/100) × battery_kwh × nominal_mi_per_kwh.
    # duration_minutes = (charge_end_at - charge_start_at), only when both set.
    # average_power_kw = kwh_added / hours, only when duration is known.
    # peak_power_kw = max kW from power_curve samples (synthesis-only).
    # efficiency_percent = kwh_calculated / kwh_added * 100 when both present.
    range_added_miles: Optional[float] = None
    duration_minutes: Optional[int] = None
    average_power_kw: Optional[float] = None
    peak_power_kw: Optional[float] = None
    efficiency_percent: Optional[float] = None
    # Genuine odometer-measured span to the previous odometer-bearing
    # session — informational only, does not feed savings.
    measured_miles_since_previous: Optional[float] = None
    # The real-world efficiency (mi/kWh) used to derive this session's range
    # and savings estimates: the car's observed efficiency (Method B, from
    # odometer history) when available, else its configured nominal. The
    # `efficiency_basis` flags which one ("observed" | "nominal" | None).
    efficiency_mi_per_kwh: Optional[float] = None
    efficiency_basis: Optional[str] = None
    # The charge rate (p/kWh) above which this charge costs more than an
    # equivalent petrol trip. None when ppm or efficiency is unavailable.
    breakeven_p_per_kwh: Optional[float] = None


def petrol_pence_per_mile(p_per_litre: float, mpg_uk: float) -> Optional[float]:
    """UK petrol cost per mile. Returns None for non-positive inputs."""
    if p_per_litre <= 0 or mpg_uk <= 0:
        return None
    return (p_per_litre * _LITRES_PER_UK_GALLON) / mpg_uk


async def _previous_session_with_odometer(
    session: AsyncSession,
    *,
    car_id: int,
    user_id: int,
    current_session_id: int,
    current_date,
) -> Optional[ChargingSession]:
    """Most recent prior session for this car that *has* an odometer
    reading. Used for the measured-span computation (informational).
    """
    stmt = (
        select(ChargingSession)
        .where(
            ChargingSession.user_id == user_id,
            ChargingSession.car_id == car_id,
            ChargingSession.id != current_session_id,
            ChargingSession.odometer_at_session_km.isnot(None),
        )
        .where(
            (ChargingSession.date < current_date)
            | (
                (ChargingSession.date == current_date)
                & (ChargingSession.id < current_session_id)
            )
        )
        .order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _is_before(a: ChargingSession, b: ChargingSession) -> bool:
    """True when session `a` sorts strictly before `b` by (date, id) —
    the same ordering the per-session queries use."""
    return (a.date, a.id) < (b.date, b.id)


def _previous_with_odometer_in_memory(
    history: list[ChargingSession], cs: ChargingSession
) -> Optional[ChargingSession]:
    """In-memory equivalent of `_previous_session_with_odometer`: the most
    recent prior session (by date, id) for the same car that has an
    odometer reading. `history` must be the car's full session list sorted
    ascending by (date, id).
    """
    found: Optional[ChargingSession] = None
    for s in history:
        if s.id == cs.id:
            continue
        if s.odometer_at_session_km is None:
            continue
        if _is_before(s, cs):
            found = s  # ascending order → last match is the most recent prior
        else:
            break
    return found


async def _float_setting(session: AsyncSession, key: str) -> Optional[float]:
    row = (
        await session.execute(select(Setting.value).where(Setting.key == key))
    ).scalar_one_or_none()
    if row is None or row == "":
        return None
    try:
        return float(row)
    except (TypeError, ValueError):
        return None


async def _observed_mi_per_kwh(
    session: AsyncSession,
    *,
    car_id: int,
    user_id: int,
    battery_kwh: float,
) -> Optional[float]:
    """The car's real-world mi/kWh from its measured (odometer-having)
    history. Energy is the energy *consumed while driving*, derived from
    SoC drops between consecutive charges — not energy added, which would
    fold in charging losses.

    Aggregates miles ÷ SoC-consumed-kWh across the car's advancing
    odometer legs. Returns None when there's no clean measured leg or the
    result is outside the plausible [1.0, 8.0] band (→ nominal fallback).
    """
    stmt = (
        select(ChargingSession)
        .where(
            ChargingSession.user_id == user_id,
            ChargingSession.car_id == car_id,
        )
        .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
    )
    sessions = list((await session.execute(stmt)).scalars().all())
    odo = [s for s in sessions if s.odometer_at_session_km is not None]

    total_miles = 0.0
    total_consumed_kwh = 0.0
    for i in range(len(odo) - 1):
        a = odo[i]
        b = odo[i + 1]
        if float(b.odometer_at_session_km) <= float(a.odometer_at_session_km):
            # No advance (chain/dup) — skip this leg.
            continue
        leg_miles = (
            float(b.odometer_at_session_km) - float(a.odometer_at_session_km)
        ) / _KM_PER_MILE
        # Chronological span of sessions from A..B inclusive.
        start = sessions.index(a)
        end = sessions.index(b)
        seg = sessions[start : end + 1]
        leg_consumed = 0.0
        for x, y in zip(seg, seg[1:]):
            # SoC dropped between charges. Per-pair max(0, drop) guards the
            # SoC-rise anomaly (unlogged charging): a noisy pair contributes
            # 0 rather than corrupting the leg.
            drop = x.end_soc - y.start_soc
            leg_consumed += max(0.0, drop) / 100.0 * battery_kwh
        if leg_consumed <= 0:
            # Can't attribute consumption — skip the leg.
            continue
        total_miles += leg_miles
        total_consumed_kwh += leg_consumed

    if total_consumed_kwh <= 0 or total_miles <= 0:
        return None
    observed = total_miles / total_consumed_kwh
    if not (1.0 <= observed <= 8.0):
        # Implausible — fall back to the static nominal.
        return None
    return observed


async def _estimate_from_energy(
    cs: ChargingSession,
    car: Optional[Car],
    base: SessionMetrics,
    *,
    ppm: Optional[float],
    observed_eff: Optional[float],
) -> SessionMetrics:
    """Per-charge energy-based comparison: estimate the distance this charge
    buys from `energy × efficiency`, where efficiency is the car's observed
    real-world mi/kWh (Method B) or the static nominal when no clean
    measured leg exists.

    Sets `miles_since_previous` (energy-estimated miles), `comparison_basis`
    ("estimated" when computable), and breakeven_p_per_kwh.

    Returns `base` unchanged (basis stays None) when the estimate isn't
    computable — zero/None energy or no efficiency.
    """
    if car is None:
        return base
    eff = observed_eff if observed_eff is not None else car.nominal_efficiency_mi_per_kwh
    energy_kwh = (
        cs.kwh_calculated if cs.kwh_calculated is not None else cs.kwh_added
    )
    if not energy_kwh or energy_kwh <= 0:
        return base
    if eff is None:
        # Defensive — nominal_efficiency_mi_per_kwh is NOT NULL.
        return base

    est_miles = float(energy_kwh) * float(eff)

    cost_per_mile_p: Optional[float] = None
    petrol_equiv_p: Optional[int] = None
    savings_p: Optional[int] = None

    if cs.cost_pence is not None and est_miles > 0:
        cost_per_mile_p = int(cs.cost_pence) / est_miles
    if ppm is not None:
        petrol_equiv_p = int(round(est_miles * ppm))
        if cs.cost_pence is not None:
            savings_p = petrol_equiv_p - int(cs.cost_pence)

    base.miles_since_previous = float(round(est_miles))
    base.cost_per_mile_p = (
        round(cost_per_mile_p, 2) if cost_per_mile_p is not None else None
    )
    base.petrol_equivalent_cost_p = petrol_equiv_p
    base.savings_vs_petrol_p = savings_p
    base.comparison_basis = "estimated"
    # Break-even rate: the charge rate above which EV costs more than petrol.
    if ppm is not None:
        base.breakeven_p_per_kwh = round(ppm * float(eff), 2)
    return base


async def compute_session_metrics(
    session: AsyncSession, cs: ChargingSession
) -> SessionMetrics:
    """Compute petrol-comparison metrics for a single session.

    All savings are per-charge energy-based:
      eff   = observed_mi_per_kwh (calibrated from odometer history) or nominal
      energy = kwh_calculated if not None else kwh_added
      miles  = energy × eff
      petrol_equivalent_p = round(miles × ppm)
      saved_vs_petrol_p   = petrol_equivalent_p - cost_pence
      comparison_basis    = "estimated"

    `comparison_basis` is None only when energy is missing/zero, no
    efficiency is available, or petrol settings are unset.

    `measured_miles_since_previous` is set as an informational field when a
    previous odometer-bearing session exists — it is the genuine span and does
    NOT feed savings.
    """
    petrol_p_per_litre = await _float_setting(session, "petrol_price_p_per_litre")
    petrol_mpg = await _float_setting(session, "petrol_mpg")
    ppm = (
        petrol_pence_per_mile(petrol_p_per_litre, petrol_mpg)
        if petrol_p_per_litre is not None and petrol_mpg is not None
        else None
    )

    base = SessionMetrics(
        miles_since_previous=None,
        cost_per_mile_p=None,
        petrol_ppm=round(ppm, 2) if ppm is not None else None,
        petrol_equivalent_cost_p=None,
        savings_vs_petrol_p=None,
        petrol_price_p_per_litre=petrol_p_per_litre,
        petrol_mpg=petrol_mpg,
    )

    # Charge-mechanics fields. Each is independently derived — a session
    # missing one piece (e.g. no power_curve on a manual entry) still
    # gets the others. Attach to `base` so it's surfaced even when the
    # petrol-comparison branch returns early below.
    await _attach_charge_mechanics(base, session, cs)

    # Load car once — needed for observed efficiency and estimate.
    car = await session.get(Car, cs.car_id)
    observed_eff = (
        await _observed_mi_per_kwh(
            session,
            car_id=cs.car_id,
            user_id=cs.user_id,
            battery_kwh=float(car.battery_kwh),
        )
        if car is not None
        else None
    )

    # Informational: genuine odometer span to the previous odometer-bearing
    # session — does NOT feed savings.
    if cs.odometer_at_session_km is not None:
        prev_with_odo = await _previous_session_with_odometer(
            session,
            car_id=cs.car_id,
            user_id=cs.user_id,
            current_session_id=cs.id,
            current_date=cs.date,
        )
        if prev_with_odo is not None:
            span_km = float(cs.odometer_at_session_km) - float(prev_with_odo.odometer_at_session_km)
            if span_km > 0:
                base.measured_miles_since_previous = round(span_km / _KM_PER_MILE, 2)

    # Per-session real-world efficiency for the detail page. When a genuine
    # odometer span to the previous reading exists, this is the actual miles
    # driven on that cycle divided by the energy added this charge — a real,
    # per-session "miles per kWh" that varies charge-to-charge. With no trip
    # span we fall back to the car's nominal spec figure (clearly flagged), so
    # we never present the car-level average as if it were this charge's.
    if (
        base.measured_miles_since_previous is not None
        and cs.kwh_added
        and cs.kwh_added > 0
    ):
        base.efficiency_mi_per_kwh = round(
            base.measured_miles_since_previous / float(cs.kwh_added), 2
        )
        base.efficiency_basis = "measured"
    elif car is not None and car.nominal_efficiency_mi_per_kwh:
        base.efficiency_mi_per_kwh = round(float(car.nominal_efficiency_mi_per_kwh), 2)
        base.efficiency_basis = "nominal"

    # Per-charge energy-based savings — uniform for every row.
    return await _estimate_from_energy(
        cs, car, base, ppm=ppm, observed_eff=observed_eff
    )


async def _attach_charge_mechanics(
    metrics: SessionMetrics,
    session: AsyncSession,
    cs: ChargingSession,
) -> None:
    """Populate the charge-mechanics fields on `metrics` (in-place).

    Each metric is derived independently; missing inputs leave that
    metric None rather than skipping the rest.
    """
    # Range added — needs the car for battery_kwh + nominal efficiency.
    if cs.end_soc is not None and cs.start_soc is not None:
        delta_soc = cs.end_soc - cs.start_soc
        if delta_soc > 0:
            car = await session.get(Car, cs.car_id)
            if car is not None:
                kwh = (delta_soc / 100.0) * float(car.battery_kwh)
                metrics.range_added_miles = round(
                    kwh * float(car.nominal_efficiency_mi_per_kwh), 2
                )

    # Duration is the plug-in window (start -> end timestamps).
    window_seconds: Optional[float] = None
    if cs.charge_start_at is not None and cs.charge_end_at is not None:
        window_seconds = (cs.charge_end_at - cs.charge_start_at).total_seconds()
        if window_seconds > 0:
            metrics.duration_minutes = int(round(window_seconds / 60.0))

    # Average power must reflect the time actually drawing power. Home charges
    # plug in for hours but only charge for a fraction of that (scheduled /
    # battery-care), so dividing by the plug-in window understates the rate
    # (3.47 kWh / 14h30m reads as 0.2 kW). Prefer actual_charge_seconds; fall
    # back to the plug-in window when actual time is unknown (e.g. synthesis).
    power_seconds = cs.actual_charge_seconds or window_seconds
    if power_seconds and power_seconds > 0 and cs.kwh_added and cs.kwh_added > 0:
        metrics.average_power_kw = round(cs.kwh_added / (power_seconds / 3600.0), 1)

    # Peak power — only present on synthesis sessions where the worker
    # accumulated a power_curve.
    if cs.power_curve:
        try:
            metrics.peak_power_kw = round(
                max(float(sample[2]) for sample in cs.power_curve), 2
            )
        except (TypeError, ValueError, IndexError):
            metrics.peak_power_kw = None

    # Efficiency = energy banked in the pack / energy delivered by the
    # charger. Surfaces cold-weather losses or sketchy meters.
    if (
        cs.kwh_calculated is not None
        and cs.kwh_added is not None
        and cs.kwh_added > 0
    ):
        metrics.efficiency_percent = round(
            float(cs.kwh_calculated) / float(cs.kwh_added) * 100.0, 1
        )


def _estimate_savings_in_memory(
    cs: ChargingSession,
    car: Optional[Car],
    *,
    ppm: Optional[float],
    observed_eff: Optional[float],
) -> tuple[Optional[int], Optional[str], Optional[float]]:
    """Pure energy-estimate computation returning
    `(saved_vs_petrol_p, comparison_basis, breakeven_p_per_kwh)`.

    Mirrors `_estimate_from_energy`'s branches exactly so the batch list
    and the detail page agree.

    `comparison_basis` is "estimated" whenever the distance estimate is
    computable (energy > 0 and an efficiency is available); savings is
    None within an estimated row when settings or cost are missing —
    matching the detail path. `breakeven_p_per_kwh` = ppm × eff, or None
    when either is unavailable.
    """
    if car is None:
        return None, None, None
    eff = observed_eff if observed_eff is not None else car.nominal_efficiency_mi_per_kwh
    energy_kwh = (
        cs.kwh_calculated if cs.kwh_calculated is not None else cs.kwh_added
    )
    if not energy_kwh or energy_kwh <= 0:
        return None, None, None
    if eff is None:
        return None, None, None

    est_miles = float(energy_kwh) * float(eff)

    savings_p: Optional[int] = None
    breakeven: Optional[float] = None
    if ppm is not None:
        petrol_equiv_p = int(round(est_miles * ppm))
        if cs.cost_pence is not None:
            savings_p = petrol_equiv_p - int(cs.cost_pence)
        breakeven = round(ppm * float(eff), 2)
    return savings_p, "estimated", breakeven


async def compute_savings_for_sessions(
    session: AsyncSession, rows: list[ChargingSession]
) -> dict[int, tuple[Optional[int], Optional[str], Optional[float]]]:
    """Batch per-charge energy-based savings for a set of sessions, keyed
    by session id.

    Returns `{ session_id: (saved_vs_petrol_p, comparison_basis,
    breakeven_p_per_kwh) }` where:
      - `comparison_basis` is "estimated" | None
      - `saved_vs_petrol_p` is Optional[int]
      - `breakeven_p_per_kwh` is Optional[float]

    Every row uses the per-charge energy estimate (no measured-span branch).
    The batch version avoids per-session queries by loading each car's FULL
    history once and deriving observed efficiency in memory.

    The numbers for `(saved_vs_petrol_p, comparison_basis)` are consistent
    with what `compute_session_metrics` returns for each row.
    """
    out: dict[int, tuple[Optional[int], Optional[str], Optional[float]]] = {}
    if not rows:
        return out

    petrol_p_per_litre = await _float_setting(session, "petrol_price_p_per_litre")
    petrol_mpg = await _float_setting(session, "petrol_mpg")
    ppm = (
        petrol_pence_per_mile(petrol_p_per_litre, petrol_mpg)
        if petrol_p_per_litre is not None and petrol_mpg is not None
        else None
    )

    # Group the input rows by car so each car's history loads once.
    by_car: dict[int, list[ChargingSession]] = {}
    for r in rows:
        by_car.setdefault(r.car_id, []).append(r)

    for car_id, car_rows in by_car.items():
        # Observed efficiency (Method B) uses the car's FULL history, not
        # just the filtered/input window — matching the detail page.
        user_id = car_rows[0].user_id
        car = await session.get(Car, car_id)

        observed_eff = (
            await _observed_mi_per_kwh(
                session,
                car_id=car_id,
                user_id=user_id,
                battery_kwh=float(car.battery_kwh),
            )
            if car is not None
            else None
        )

        for cs in car_rows:
            out[cs.id] = _savings_for_row(
                cs,
                car=car,
                ppm=ppm,
                observed_eff=observed_eff,
            )

    return out


def _savings_for_row(
    cs: ChargingSession,
    *,
    car: Optional[Car],
    ppm: Optional[float],
    observed_eff: Optional[float],
) -> tuple[Optional[int], Optional[str], Optional[float]]:
    """Derive `(saved_vs_petrol_p, comparison_basis, breakeven_p_per_kwh)`
    for one row using the per-charge energy estimate.
    """
    return _estimate_savings_in_memory(
        cs, car, ppm=ppm, observed_eff=observed_eff
    )
