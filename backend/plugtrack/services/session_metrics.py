"""Per-session derived metrics — petrol-equivalent comparison.

Pure functions + a couple of DB-touching coroutines. The headline output
is a `SessionMetrics` describing miles travelled since the previous
session, the EV cost per mile, and the savings vs an equivalent petrol
trip.

Charging-chain handling: when consecutive sessions for the same car
have the same odometer (or no odometer), they form a "chain" — the car
hasn't moved between them. We attribute the *combined* EV cost of the
chain to the **first session in the chain**, because that is the one
that has the miles span. Subsequent zero-mile sessions in the chain
return their own metrics with `chain_anchor_id` pointing back to the
anchor so the UI can link to it.

Why this shape: the user only ever sees one petrol-vs-EV comparison per
movement cycle, but every session in the chain knows where its
contribution went. Lifetime totals are unaffected — they sum
`cost_pence` directly from the rows.
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
    # How the comparison was derived: "measured" (odometer span),
    # "estimated" (energy × efficiency fallback), or None (no comparison).
    comparison_basis: Optional[str] = None
    # Chain wiring.
    chain_session_ids: list[int] = field(default_factory=list)
    chain_total_cost_pence: Optional[int] = None
    # When this session is itself a zero-mile follow-up, the id of the
    # anchor session that owns the comparison (so the UI can link).
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


def petrol_pence_per_mile(p_per_litre: float, mpg_uk: float) -> Optional[float]:
    """UK petrol cost per mile. Returns None for non-positive inputs."""
    if p_per_litre <= 0 or mpg_uk <= 0:
        return None
    return (p_per_litre * _LITRES_PER_UK_GALLON) / mpg_uk


async def _previous_session(
    session: AsyncSession,
    *,
    car_id: int,
    user_id: int,
    current_session_id: int,
    current_date,
) -> Optional[ChargingSession]:
    """Most recent prior session for this car (any odometer state)."""
    stmt = (
        select(ChargingSession)
        .where(
            ChargingSession.user_id == user_id,
            ChargingSession.car_id == car_id,
            ChargingSession.id != current_session_id,
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


async def _previous_session_with_odometer(
    session: AsyncSession,
    *,
    car_id: int,
    user_id: int,
    current_session_id: int,
    current_date,
) -> Optional[ChargingSession]:
    """Most recent prior session for this car that *has* an odometer
    reading. Used for the miles-span computation; we want the chain to
    span back to whichever older session last logged a reading.
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


async def _forward_zero_mile_chain(
    session: AsyncSession,
    *,
    anchor: ChargingSession,
) -> list[ChargingSession]:
    """Walk *forward* in time from `anchor` collecting every subsequent
    session for the same car whose odometer matches the anchor (or is
    NULL). Stops at the first session where the odometer has advanced.
    """
    stmt = (
        select(ChargingSession)
        .where(
            ChargingSession.user_id == anchor.user_id,
            ChargingSession.car_id == anchor.car_id,
            ChargingSession.id != anchor.id,
        )
        .where(
            (ChargingSession.date > anchor.date)
            | (
                (ChargingSession.date == anchor.date)
                & (ChargingSession.id > anchor.id)
            )
        )
        .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[ChargingSession] = []
    for r in rows:
        if r.odometer_at_session_km is None:
            out.append(r)
            continue
        # Stop at the first session that has actually moved past anchor.
        if (
            anchor.odometer_at_session_km is not None
            and float(r.odometer_at_session_km)
            > float(anchor.odometer_at_session_km)
        ):
            break
        out.append(r)
    return out


async def _walk_back_to_anchor(
    session: AsyncSession,
    *,
    cs: ChargingSession,
) -> Optional[ChargingSession]:
    """Walk *backwards* through prior sessions for this car until we
    find one whose odometer is strictly less than `cs.odometer_at_session_km`
    (meaning the car had moved between that session and this one).
    Returns the anchor session — i.e. the first one *after* the gap.

    Used when `cs` itself has zero-mile span, so we can point the UI at
    whichever earlier session is the chain anchor.
    """
    if cs.odometer_at_session_km is None:
        return None
    cur = cs
    while True:
        prev = await _previous_session(
            session,
            car_id=cur.car_id,
            user_id=cur.user_id,
            current_session_id=cur.id,
            current_date=cur.date,
        )
        if prev is None:
            return None
        if prev.odometer_at_session_km is None:
            cur = prev
            continue
        if float(prev.odometer_at_session_km) < float(cs.odometer_at_session_km):
            # `cur` is the first session at the current odometer reading
            # — that's our anchor (the one with miles since *its*
            # predecessor).
            return cur
        cur = prev


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


def _previous_in_memory(
    history: list[ChargingSession], cs: ChargingSession
) -> Optional[ChargingSession]:
    """In-memory equivalent of `_previous_session`: the most recent prior
    session (by date, id) for the same car, any odometer state."""
    found: Optional[ChargingSession] = None
    for s in history:
        if s.id == cs.id:
            continue
        if _is_before(s, cs):
            found = s
        else:
            break
    return found


def _forward_zero_mile_chain_in_memory(
    history: list[ChargingSession], anchor: ChargingSession
) -> list[ChargingSession]:
    """In-memory equivalent of `_forward_zero_mile_chain`: walk forward in
    time from `anchor` collecting every subsequent session whose odometer
    matches the anchor (or is NULL), stopping at the first that advanced.
    """
    out: list[ChargingSession] = []
    for r in history:
        if r.id == anchor.id:
            continue
        if not _is_before(anchor, r):
            continue
        if r.odometer_at_session_km is None:
            out.append(r)
            continue
        if (
            anchor.odometer_at_session_km is not None
            and float(r.odometer_at_session_km)
            > float(anchor.odometer_at_session_km)
        ):
            break
        out.append(r)
    return out


def _walk_back_to_anchor_in_memory(
    history: list[ChargingSession], cs: ChargingSession
) -> Optional[ChargingSession]:
    """In-memory equivalent of `_walk_back_to_anchor`: walk backwards until
    a prior session has an odometer strictly less than `cs`'s, returning
    the first session after that gap (the chain anchor)."""
    if cs.odometer_at_session_km is None:
        return None
    cur = cs
    while True:
        prev = _previous_in_memory(history, cur)
        if prev is None:
            return None
        if prev.odometer_at_session_km is None:
            cur = prev
            continue
        if float(prev.odometer_at_session_km) < float(cs.odometer_at_session_km):
            return cur
        cur = prev


def _measured_savings(
    cs: ChargingSession,
    prev: ChargingSession,
    chain: list[ChargingSession],
    *,
    ppm: Optional[float],
) -> tuple[Optional[float], Optional[int], Optional[float], Optional[int], int, bool]:
    """Pure measured-span computation shared by the detail and batch paths.

    Given the anchor `cs`, its previous-with-odometer `prev`, and the
    forward zero-mile `chain` (which includes `cs` as its first element),
    return:
        (miles, cost_per_mile_p, petrol_equiv_p, savings_p,
         chain_total, chain_has_cost)
    """
    span_km = (
        float(cs.odometer_at_session_km) - float(prev.odometer_at_session_km)
    )
    miles = span_km / _KM_PER_MILE

    chain_total = 0
    chain_has_cost = False
    for row in chain:
        if row.cost_pence is not None:
            chain_total += int(row.cost_pence)
            chain_has_cost = True

    cost_per_mile_p: Optional[float] = None
    petrol_equiv_p: Optional[int] = None
    savings_p: Optional[int] = None
    if chain_has_cost and miles > 0:
        cost_per_mile_p = chain_total / miles
    if ppm is not None:
        petrol_equiv_p = int(round(miles * ppm))
        if chain_has_cost:
            savings_p = petrol_equiv_p - chain_total

    return miles, cost_per_mile_p, petrol_equiv_p, savings_p, chain_total, chain_has_cost


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
    """Energy-based fallback comparison: estimate the distance this charge
    buys from `energy × efficiency`, where efficiency is the car's observed
    real-world mi/kWh (Method B) or the static nominal when no clean
    measured leg exists.

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
    return base


async def compute_session_metrics(
    session: AsyncSession, cs: ChargingSession
) -> SessionMetrics:
    """Compute petrol-comparison metrics for a single session.

    Three cases:

    1. **Anchor session** — `cs` has an odometer that's ahead of the
       previous-with-odometer session. Miles span is computed; the
       petrol comparison uses the *combined* cost of `cs` + every
       subsequent zero-mile session as the EV-side number.
    2. **Zero-mile follow-up** — `cs` has no movement since the most
       recent session. Walk back to the anchor and return a metrics
       record with `chain_anchor_id` set so the UI can render
       "part of an ongoing chain — see #N".
    3. **Insufficient data** — no prior odometer at all, or settings
       missing. Everything is None.
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

    if cs.odometer_at_session_km is None:
        # No odometer on this session — fall back to an energy estimate.
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
        return await _estimate_from_energy(
            cs, car, base, ppm=ppm, observed_eff=observed_eff
        )

    prev = await _previous_session_with_odometer(
        session,
        car_id=cs.car_id,
        user_id=cs.user_id,
        current_session_id=cs.id,
        current_date=cs.date,
    )
    if prev is None:
        # Odometer present but no prior-with-odometer — energy estimate.
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
        return await _estimate_from_energy(
            cs, car, base, ppm=ppm, observed_eff=observed_eff
        )

    span_km = float(cs.odometer_at_session_km) - float(prev.odometer_at_session_km)
    # Treat sub-mile odometer drift as zero — the car telemetry rounds to
    # 1 km and manual entries are typically integers, so a 1 km gap can
    # mean "didn't move, just rounded differently". Below 1 mi rounds to
    # zero anyway; clamping here keeps the chain logic consistent.
    if span_km < _KM_PER_MILE:
        anchor = await _walk_back_to_anchor(session, cs=cs)
        base.chain_anchor_id = anchor.id if anchor is not None else None
        return base

    # `cs` is the anchor of its own chain. Sum its cost with every
    # subsequent zero-mile session for the same car.
    chain = [cs] + await _forward_zero_mile_chain(session, anchor=cs)
    (
        miles,
        cost_per_mile_p,
        petrol_equiv_p,
        savings_p,
        chain_total,
        chain_has_cost,
    ) = _measured_savings(cs, prev, chain, ppm=ppm)

    out = SessionMetrics(
        miles_since_previous=float(round(miles)),
        cost_per_mile_p=round(cost_per_mile_p, 2) if cost_per_mile_p is not None else None,
        petrol_ppm=round(ppm, 2) if ppm is not None else None,
        petrol_equivalent_cost_p=petrol_equiv_p,
        savings_vs_petrol_p=savings_p,
        petrol_price_p_per_litre=petrol_p_per_litre,
        petrol_mpg=petrol_mpg,
        comparison_basis="measured",
        chain_session_ids=[row.id for row in chain],
        chain_total_cost_pence=chain_total if chain_has_cost else None,
        chain_anchor_id=None,
    )
    await _attach_charge_mechanics(out, session, cs)
    return out


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

    # Duration + average power — both need start + end timestamps.
    if cs.charge_start_at is not None and cs.charge_end_at is not None:
        seconds = (cs.charge_end_at - cs.charge_start_at).total_seconds()
        if seconds > 0:
            metrics.duration_minutes = int(round(seconds / 60.0))
            if cs.kwh_added and cs.kwh_added > 0:
                hours = seconds / 3600.0
                metrics.average_power_kw = round(cs.kwh_added / hours, 1)

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
) -> tuple[Optional[int], Optional[str]]:
    """Pure energy-estimate equivalent of `_estimate_from_energy`, returning
    only `(saved_vs_petrol_p, comparison_basis)`. Mirrors that function's
    branches exactly so the batch list and the detail page agree.

    Basis is "estimated" whenever the distance estimate is computable
    (energy > 0 and an efficiency is available); savings is None within an
    estimated row when settings or cost are missing — matching the detail
    path, which sets basis "estimated" but leaves `savings_vs_petrol_p`
    None in those cases.
    """
    if car is None:
        return None, None
    eff = observed_eff if observed_eff is not None else car.nominal_efficiency_mi_per_kwh
    energy_kwh = (
        cs.kwh_calculated if cs.kwh_calculated is not None else cs.kwh_added
    )
    if not energy_kwh or energy_kwh <= 0:
        return None, None
    if eff is None:
        return None, None

    est_miles = float(energy_kwh) * float(eff)

    savings_p: Optional[int] = None
    if ppm is not None:
        petrol_equiv_p = int(round(est_miles * ppm))
        if cs.cost_pence is not None:
            savings_p = petrol_equiv_p - int(cs.cost_pence)
    return savings_p, "estimated"


async def compute_savings_for_sessions(
    session: AsyncSession, rows: list[ChargingSession]
) -> dict[int, tuple[Optional[int], Optional[str]]]:
    """Batch petrol-savings for a set of sessions, keyed by session id.

    Returns `{ session_id: (saved_vs_petrol_p, comparison_basis) }` where
    `comparison_basis` is "measured" | "estimated" | None and
    `saved_vs_petrol_p` is Optional[int].

    The numbers are byte-for-byte the same as `compute_session_metrics`
    would return for each row's `savings_vs_petrol_p` / `comparison_basis`,
    because both paths share `_measured_savings` /
    `_estimate_savings_in_memory` and the same precedence
    (measured → estimated → none). The batch version avoids per-session
    queries by loading each car's FULL history once and deriving the
    previous-with-odometer / forward-chain in memory.
    """
    out: dict[int, tuple[Optional[int], Optional[str]]] = {}
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

        stmt = (
            select(ChargingSession)
            .where(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == car_id,
            )
            .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
        )
        history = list((await session.execute(stmt)).scalars().all())

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
                history=history,
                ppm=ppm,
                observed_eff=observed_eff,
            )

    return out


def _savings_for_row(
    cs: ChargingSession,
    *,
    car: Optional[Car],
    history: list[ChargingSession],
    ppm: Optional[float],
    observed_eff: Optional[float],
) -> tuple[Optional[int], Optional[str]]:
    """Derive `(saved_vs_petrol_p, comparison_basis)` for one row using the
    in-memory per-car history. Same precedence as
    `compute_session_metrics`: measured → estimated → none.
    """
    # No odometer at all → energy estimate.
    if cs.odometer_at_session_km is None:
        return _estimate_savings_in_memory(
            cs, car, ppm=ppm, observed_eff=observed_eff
        )

    prev = _previous_with_odometer_in_memory(history, cs)
    if prev is None:
        # Odometer present but no prior-with-odometer → energy estimate.
        return _estimate_savings_in_memory(
            cs, car, ppm=ppm, observed_eff=observed_eff
        )

    span_km = (
        float(cs.odometer_at_session_km) - float(prev.odometer_at_session_km)
    )
    if span_km < _KM_PER_MILE:
        # Zero-mile follow-up — the comparison belongs to the anchor.
        # Detail path returns base (savings None, basis None) here.
        return None, None

    chain = [cs] + _forward_zero_mile_chain_in_memory(history, cs)
    _, _, _, savings_p, _, _ = _measured_savings(cs, prev, chain, ppm=ppm)
    return savings_p, "measured"
