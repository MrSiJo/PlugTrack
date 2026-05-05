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

from ..models import ChargingSession, Setting


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
    # Chain wiring.
    chain_session_ids: list[int] = field(default_factory=list)
    chain_total_cost_pence: Optional[int] = None
    # When this session is itself a zero-mile follow-up, the id of the
    # anchor session that owns the comparison (so the UI can link).
    chain_anchor_id: Optional[int] = None


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

    if cs.odometer_at_session_km is None:
        return base

    prev = await _previous_session_with_odometer(
        session,
        car_id=cs.car_id,
        user_id=cs.user_id,
        current_session_id=cs.id,
        current_date=cs.date,
    )
    if prev is None:
        return base

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
    chain_total = 0
    chain_has_cost = False
    for row in chain:
        if row.cost_pence is not None:
            chain_total += int(row.cost_pence)
            chain_has_cost = True

    miles = span_km / _KM_PER_MILE
    cost_per_mile_p: Optional[float] = None
    petrol_equiv_p: Optional[int] = None
    savings_p: Optional[int] = None

    if chain_has_cost and miles > 0:
        cost_per_mile_p = chain_total / miles
    if ppm is not None:
        petrol_equiv_p = int(round(miles * ppm))
        if chain_has_cost:
            savings_p = petrol_equiv_p - chain_total

    return SessionMetrics(
        miles_since_previous=float(round(miles)),
        cost_per_mile_p=round(cost_per_mile_p, 2) if cost_per_mile_p is not None else None,
        petrol_ppm=round(ppm, 2) if ppm is not None else None,
        petrol_equivalent_cost_p=petrol_equiv_p,
        savings_vs_petrol_p=savings_p,
        petrol_price_p_per_litre=petrol_p_per_litre,
        petrol_mpg=petrol_mpg,
        chain_session_ids=[row.id for row in chain],
        chain_total_cost_pence=chain_total if chain_has_cost else None,
        chain_anchor_id=None,
    )
