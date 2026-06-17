# backend/plugtrack/services/screenshot_correlation.py
"""Group per-screenshot extractions into merged charging sessions.

Two extractions belong to the same session when their time windows overlap
within TIME_TOLERANCE_MIN. Merge rule (source priority):
  - cost / energy / per-kWh / location / network  <- the `has_cost` extraction
  - state-of-charge / power curve                 <- the SoC-bearing extraction
  - start/end times                               <- earliest start, latest end
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from .screenshot_extraction import Extraction

TIME_TOLERANCE_MIN = 20


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass
class MergedSession:
    start_at: datetime
    end_at: Optional[datetime]
    energy_kwh: Optional[float]
    cost_total_pence: Optional[int]
    cost_per_kwh_pence: Optional[float]
    soc_start: Optional[int]
    soc_end: Optional[int]
    location_name: Optional[str]
    location_address: Optional[str]
    network: Optional[str]
    peak_kw: Optional[float]
    confidence: float
    odometer: Optional[float] = None
    odometer_unit: Optional[str] = None
    source_kinds: list[str] = field(default_factory=list)


def _windows_overlap(a: Extraction, b: Extraction) -> bool:
    a_start, b_start = _parse_dt(a.start_at), _parse_dt(b.start_at)
    if a_start is None or b_start is None:
        return False
    a_end = _parse_dt(a.end_at) or a_start
    b_end = _parse_dt(b.end_at) or b_start
    tol = timedelta(minutes=TIME_TOLERANCE_MIN)
    return a_start - tol <= b_end and b_start - tol <= a_end


def _merge(group: list[Extraction]) -> MergedSession:
    cost_src = next((e for e in group if e.has_cost), None)
    soc_src = next((e for e in group if e.soc_start is not None or e.soc_end is not None), None)
    starts = [d for d in (_parse_dt(e.start_at) for e in group) if d is not None]
    ends = [d for d in (_parse_dt(e.end_at) for e in group) if d is not None]
    start_at = min(starts)
    end_at = max(ends) if ends else None
    pick = cost_src or group[0]
    odo_src = next((e for e in group if e.odometer is not None), None)
    return MergedSession(
        start_at=start_at,
        end_at=end_at,
        energy_kwh=(cost_src.energy_kwh if cost_src else next((e.energy_kwh for e in group if e.energy_kwh is not None), None)),
        cost_total_pence=cost_src.cost_total_pence if cost_src else None,
        cost_per_kwh_pence=cost_src.cost_per_kwh_pence if cost_src else None,
        soc_start=soc_src.soc_start if soc_src else None,
        soc_end=soc_src.soc_end if soc_src else None,
        location_name=pick.location_name or next((e.location_name for e in group if e.location_name), None),
        location_address=pick.location_address or next((e.location_address for e in group if e.location_address), None),
        network=pick.network or next((e.network for e in group if e.network), None),
        peak_kw=next((e.peak_kw for e in group if e.peak_kw is not None), None),
        confidence=min(e.confidence for e in group),
        odometer=odo_src.odometer if odo_src else None,
        odometer_unit=odo_src.odometer_unit if odo_src else None,
        source_kinds=sorted({e.source for e in group}),
    )


def _cluster_timed(timed: list[Extraction]) -> list[list[Extraction]]:
    """Cluster extractions that HAVE a parseable start_at by overlapping window."""
    remaining = list(timed)
    groups: list[list[Extraction]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        i = 0
        while i < len(remaining):
            if any(_windows_overlap(member, remaining[i]) for member in group):
                group.append(remaining.pop(i))
            else:
                i += 1
        groups.append(group)
    return groups


def correlate_batch(
    extractions: list[Extraction],
) -> tuple[list[MergedSession], list[Extraction]]:
    """Correlate a Save-batch (one charge per Save) into sessions.

    Timed extractions (app screenshots) cluster by overlapping charge window.
    Untimed readings (a granny/AC meter display has kWh + duration but no clock
    time) can't be placed on the timeline on their own, so:
      - exactly ONE timed charge in the batch -> attach all untimed to it
        (the batch is one charge, so the target is unambiguous);
      - otherwise (0 timed, or 2+ timed) -> the untimed are `unplaceable` and
        returned to the caller to prompt the user for a date / app screenshot.

    Returns (sessions, unplaceable_untimed_extractions).
    """
    timed = [e for e in extractions if _parse_dt(e.start_at) is not None]
    untimed = [e for e in extractions if _parse_dt(e.start_at) is None]
    groups = _cluster_timed(timed)
    unplaceable: list[Extraction] = []
    if untimed:
        if len(groups) == 1:
            groups[0].extend(untimed)
        else:
            unplaceable = list(untimed)
    sessions = sorted((_merge(g) for g in groups), key=lambda m: m.start_at)
    return sessions, unplaceable


def correlate(extractions: list[Extraction]) -> list[MergedSession]:
    """Back-compat: placeable sessions only (see `correlate_batch`)."""
    sessions, _ = correlate_batch(extractions)
    return sessions
