# backend/plugtrack/services/mycupra_import.py
"""Backfill historical sessions from a MyCupra "charging statistics" CSV export.

The CSV's value is the **Actual charging time** column (real energy-transfer
time), which PlugTrack has no other way to learn for past sessions, plus the
handful of charges that never made it into the DB at all.

Matching policy (see spec 2026-06-17):
  1. Idempotent: a session already linked by `telematics_session_id` is left
     alone (only its `actual_charge_seconds` is filled if still missing).
  2. Heuristic (first run; legacy rows have no telematics id): among the car's
     sessions within ±1 day of the row's *local* start, pick the closest by
     SoC endpoints (tiebreak: start-time proximity) and accept it if within
     tolerance. A matched session gets ONLY `actual_charge_seconds` +
     `telematics_session_id` — kWh / SoC / cost / source stay untouched
     (user overrides are sacred).
  3. No match -> insert a new session, `source="import"`.

CSV timestamps are UTC; the DB stores Europe/London local-naive datetimes
(matching the screenshot-ingest convention), so we convert on the way in.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession

LONDON = ZoneInfo("Europe/London")

# Tier 1: a candidate matches if |Δsoc_start| + |Δsoc_end| <= SOC_TOL and the
# local start times are within START_TOL_MIN minutes.
SOC_TOL = 8
START_TOL_MIN = 120
# Tier 2 (fallback for mis-entered start SoC or plug-in-vs-actual-charge start
# times): same local calendar day, end SoC within END_SOC_TOL, energy within
# ENERGY_TOL kWh. No time window — a scheduled AC charge can log its plug-in
# time hours before the actual transfer the DB recorded.
END_SOC_TOL = 2
ENERGY_TOL = 2.0
# Implied power (kWh / actual hours) at/above this is treated as DC rapid.
DC_POWER_KW = 11.0


@dataclass
class CsvRow:
    session_id: str
    start_local: datetime          # naive, Europe/London
    end_local: Optional[datetime]
    actual_s: Optional[int]
    energy_kwh: Optional[float]
    soc_start: Optional[int]
    soc_end: Optional[int]


@dataclass
class RowAction:
    session_id: str
    action: str                    # "insert" | "update" | "skip"
    reason: str
    start_local: Optional[datetime] = None
    soc_start: Optional[int] = None
    soc_end: Optional[int] = None
    actual_s: Optional[int] = None
    energy_kwh: Optional[float] = None
    db_session_id: Optional[int] = None
    charging_type: Optional[str] = None


@dataclass
class ImportReport:
    actions: list[RowAction] = field(default_factory=list)

    @property
    def inserted(self) -> list[RowAction]:
        return [a for a in self.actions if a.action == "insert"]

    @property
    def updated(self) -> list[RowAction]:
        return [a for a in self.actions if a.action == "update"]

    @property
    def skipped(self) -> list[RowAction]:
        return [a for a in self.actions if a.action == "skip"]


def _fmt_dur(seconds: Optional[int]) -> str:
    if not seconds:
        return "—"
    mins = seconds // 60
    h, m = divmod(mins, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def format_report(report: ImportReport) -> str:
    """Human-readable what-if / result summary, one line per CSV row."""
    lines = [
        f"Plan: {len(report.inserted)} insert, {len(report.updated)} update, "
        f"{len(report.skipped)} skip ({len(report.actions)} rows total).",
        "",
    ]
    for a in report.actions:
        when = a.start_local.strftime("%Y-%m-%d %H:%M") if a.start_local else "??"
        soc = f"{a.soc_start}->{a.soc_end}%" if a.soc_start is not None else "?"
        energy = f"{a.energy_kwh:.0f}kWh" if a.energy_kwh is not None else "?"
        actual = _fmt_dur(a.actual_s)
        tag = a.action.upper()
        target = f" #{a.db_session_id}" if a.db_session_id else ""
        ctype = f" {a.charging_type}" if a.charging_type else ""
        lines.append(
            f"  {tag:6}{target:>5}  {when}  {soc:>10} {energy:>6}  actual {actual:>6}{ctype}"
            f"   — {a.reason}")
    return "\n".join(lines)


def _utc(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _to_local_naive(dt_utc: datetime) -> datetime:
    return dt_utc.astimezone(LONDON).replace(tzinfo=None)


def _int(value: str) -> Optional[int]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(round(float(value)))
    except ValueError:
        return None


def _float(value: str) -> Optional[float]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_csv_rows(dict_rows: Iterable[dict]) -> list[CsvRow]:
    """Parse MyCupra CSV `DictReader` rows into `CsvRow`s (UTC -> local)."""
    out: list[CsvRow] = []
    for r in dict_rows:
        started = r.get("Session started")
        if not started:
            continue
        start_local = _to_local_naive(_utc(started))
        ended = r.get("Session ended")
        end_local = _to_local_naive(_utc(ended)) if ended else None
        out.append(CsvRow(
            session_id=(r.get("Session ID") or "").strip(),
            start_local=start_local,
            end_local=end_local,
            actual_s=_int(r.get("Actual charging time (s)")),
            energy_kwh=_float(r.get("Total energy (kWh)")),
            soc_start=_int(r.get("Initial state of charge (%)")),
            soc_end=_int(r.get("Final state of charge (%)")),
        ))
    return out


def load_csv(path: str) -> list[CsvRow]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return parse_csv_rows(csv.DictReader(f))


def parse_location_map(spec: Optional[str]) -> dict[date_cls, int]:
    """Parse a `YYYY-MM-DD=location_id,...` spec into a date->location_id map.

    Used to assign a location to *inserted* (missing) sessions by their local
    date — e.g. away days at a holiday cottage vs days back home."""
    out: dict[date_cls, int] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        day, _, loc = part.partition("=")
        out[date_cls.fromisoformat(day.strip())] = int(loc.strip())
    return out


def _classify_type(row: CsvRow) -> str:
    """AC home vs DC rapid. The CSV carries no network/cost, so infer from
    implied power (energy / actual time); fall back to AC when SoC is present."""
    if row.energy_kwh and row.actual_s and row.actual_s > 0:
        kw = row.energy_kwh / (row.actual_s / 3600.0)
        if kw >= DC_POWER_KW:
            return "dc"
    if row.soc_start is not None or row.soc_end is not None:
        return "ac"
    return "unknown"


def _soc_distance(row: CsvRow, cs: ChargingSession) -> Optional[int]:
    if row.soc_start is None or row.soc_end is None:
        return None
    return abs(cs.start_soc - row.soc_start) + abs(cs.end_soc - row.soc_end)


def _start_diff_min(row: CsvRow, cs: ChargingSession) -> Optional[float]:
    if cs.charge_start_at is None:
        return None
    db_start = cs.charge_start_at.replace(tzinfo=None)
    return abs((db_start - row.start_local).total_seconds()) / 60.0


def _available(cs: ChargingSession, used: set[int]) -> bool:
    return cs.id not in used and cs.telematics_session_id is None


def _best_match(row: CsvRow, candidates: list[ChargingSession], used: set[int]) -> Optional[ChargingSession]:
    """Tier 1: close SoC endpoints AND close start time."""
    best: Optional[ChargingSession] = None
    best_key: Optional[tuple[int, float]] = None
    for cs in candidates:
        if not _available(cs, used):
            continue
        score = _soc_distance(row, cs)
        diff = _start_diff_min(row, cs)
        if score is None or diff is None:
            continue
        if score > SOC_TOL or diff > START_TOL_MIN:
            continue
        key = (score, diff)
        if best_key is None or key < best_key:
            best_key, best = key, cs
    return best


def _fallback_match(row: CsvRow, candidates: list[ChargingSession], used: set[int]) -> Optional[ChargingSession]:
    """Tier 2: same local calendar day + matching end-SoC + close energy.

    Catches rows whose start SoC was mis-entered, or whose CSV plug-in time is
    hours off the DB's actual-charge start. End-SoC keeps same-day multiples
    (which differ on final SoC) from cross-matching."""
    if row.soc_end is None or row.energy_kwh is None:
        return None
    best: Optional[ChargingSession] = None
    best_key: Optional[tuple[int, float]] = None
    for cs in candidates:
        if not _available(cs, used) or cs.charge_start_at is None:
            continue
        if cs.charge_start_at.replace(tzinfo=None).date() != row.start_local.date():
            continue
        end_d = abs(cs.end_soc - row.soc_end)
        energy_d = abs((cs.kwh_added or 0.0) - row.energy_kwh)
        if end_d > END_SOC_TOL or energy_d > ENERGY_TOL:
            continue
        key = (end_d, energy_d)
        if best_key is None or key < best_key:
            best_key, best = key, cs
    return best


async def _build_insert(
    session: AsyncSession, *, user_id: int, car_id: int, row: CsvRow,
    location_id: Optional[int] = None,
) -> ChargingSession:
    from ..api.routes.sessions import _derive_kwh_calculated
    from .cost_apply import apply_cost

    cs = ChargingSession(
        user_id=user_id,
        car_id=car_id,
        date=row.start_local.date(),
        charge_start_at=row.start_local,
        charge_end_at=row.end_local,
        start_soc=row.soc_start if row.soc_start is not None else 0,
        end_soc=row.soc_end if row.soc_end is not None else 0,
        kwh_added=row.energy_kwh if row.energy_kwh is not None else 0.0,
        charging_type=_classify_type(row),
        charging_mode="unknown",
        actual_charge_seconds=row.actual_s,
        location_id=location_id,
        source="import",
        telematics_session_id=row.session_id or None,
    )
    await _derive_kwh_calculated(session, cs)
    if (cs.kwh_added is None or cs.kwh_added == 0.0) and cs.kwh_calculated:
        cs.kwh_added = cs.kwh_calculated
    await apply_cost(session, cs)
    return cs


async def run_import(
    session: AsyncSession, *, user_id: int, car_id: int,
    rows: list[CsvRow], apply: bool,
    location_by_date: Optional[dict[date_cls, int]] = None,
) -> ImportReport:
    """Plan (and, when `apply`, perform) the backfill. Caller commits.

    `location_by_date` assigns a location to *inserted* rows by local date (the
    cost then follows location precedence — free location -> £0)."""
    report = ImportReport()
    if not rows:
        return report

    lo = min(r.start_local for r in rows).date() - timedelta(days=1)
    hi = max(r.start_local for r in rows).date() + timedelta(days=1)
    existing = list((await session.execute(
        select(ChargingSession).where(
            ChargingSession.user_id == user_id,
            ChargingSession.car_id == car_id,
            ChargingSession.date >= lo,
            ChargingSession.date <= hi,
        )
    )).scalars().all())
    by_sid = {cs.telematics_session_id: cs for cs in existing if cs.telematics_session_id}
    used: set[int] = set()

    for row in rows:
        base = dict(
            session_id=row.session_id, start_local=row.start_local,
            soc_start=row.soc_start, soc_end=row.soc_end,
            actual_s=row.actual_s, energy_kwh=row.energy_kwh,
        )
        linked = by_sid.get(row.session_id) if row.session_id else None
        if linked is not None:
            used.add(linked.id)
            if linked.actual_charge_seconds is None and row.actual_s is not None:
                if apply:
                    linked.actual_charge_seconds = row.actual_s
                report.actions.append(RowAction(
                    action="update", reason="linked; filled actual charge time",
                    db_session_id=linked.id, **base))
            else:
                report.actions.append(RowAction(
                    action="skip", reason="already imported", db_session_id=linked.id, **base))
            continue

        match = _best_match(row, existing, used) or _fallback_match(row, existing, used)
        if match is not None:
            used.add(match.id)
            if apply:
                if match.actual_charge_seconds is None:
                    match.actual_charge_seconds = row.actual_s
                match.telematics_session_id = row.session_id or None
            report.actions.append(RowAction(
                action="update",
                reason=f"matched #{match.id} ({match.start_soc}->{match.end_soc}%)",
                db_session_id=match.id, charging_type=match.charging_type, **base))
        else:
            ctype = _classify_type(row)
            loc_id = (location_by_date or {}).get(row.start_local.date())
            if apply:
                cs = await _build_insert(
                    session, user_id=user_id, car_id=car_id, row=row, location_id=loc_id)
                session.add(cs)
            reason = "no match — new session"
            if loc_id is not None:
                reason += f" @ location {loc_id}"
            report.actions.append(RowAction(
                action="insert", reason=reason, charging_type=ctype, **base))

    if apply:
        await session.flush()
    return report
