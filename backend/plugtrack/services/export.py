"""User-scoped sessions and locations export service.

Provides three helpers that Task 4 (maintenance routes) will call:

  export_sessions_rows  — async; returns list[dict] filtered by user_id.
  export_locations_rows — async; returns list[dict] filtered by user_id.
  rows_to_csv           — sync; serialises to CSV string (header + rows).
  rows_to_json          — sync; serialises to JSON string (list of dicts).

Multi-user isolation contract: every query MUST filter by user_id.  These
functions must never leak another user's rows.

Distance columns are exported as-is with the `_km` suffix — no unit
conversion happens here; that is the UI's responsibility.

SESSION_EXPORT_COLUMNS is stable — the Task 4 routes reference it when
building Content-Disposition filenames and writing headers.  Never reorder
or remove a column without updating the constant and bumping the backup
format version.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChargingSession, Location

# ---------------------------------------------------------------------------
# Column manifest
# ---------------------------------------------------------------------------

SESSION_EXPORT_COLUMNS: list[str] = [
    "id",
    "date",
    "car_id",
    "charge_start_at",
    "charge_end_at",
    "start_soc",
    "end_soc",
    "kwh_added",
    "kwh_calculated",
    "odometer_at_session_km",
    "charging_type",
    "charging_mode",
    "actual_charge_seconds",
    "interrupted",
    "cost_pence",
    "cost_basis",
    "tariff_p_per_kwh",
    "cost_per_kwh_override_p",
    "total_cost_pence_override",
    "location_id",
    "location_name",
    "user_label",
    "charge_network",
    "notes",
    "source",
]

# Columns sourced directly from ChargingSession (no join needed).
_SESSION_MODEL_COLUMNS: list[str] = [c for c in SESSION_EXPORT_COLUMNS if c != "location_name"]

# Columns to export from Location.
_LOCATION_EXPORT_COLUMNS: list[str] = [
    "id",
    "name",
    "address",
    "latitude",
    "longitude",
    "is_free",
    "default_cost_per_kwh_p",
    "radius_m",
]


# ---------------------------------------------------------------------------
# Sessions export
# ---------------------------------------------------------------------------


async def export_sessions_rows(session: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    """Return all charging sessions for *user_id* as a list of dicts.

    Each dict has exactly the keys in SESSION_EXPORT_COLUMNS.  The
    ``location_name`` value is pulled from the LEFT JOIN on Location; it is
    ``None`` when the session has no ``location_id``.

    Rows are ordered by ``date`` ascending, then ``id`` ascending so the
    export is deterministic and chronological.
    """
    stmt = (
        select(ChargingSession, Location.name)
        .join(Location, ChargingSession.location_id == Location.id, isouter=True)
        .where(ChargingSession.user_id == user_id)
        .order_by(ChargingSession.date.asc(), ChargingSession.id.asc())
    )
    result = await session.execute(stmt)

    rows: list[dict[str, Any]] = []
    for cs, loc_name in result.all():
        row: dict[str, Any] = {col: getattr(cs, col) for col in _SESSION_MODEL_COLUMNS}
        row["location_name"] = loc_name
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Locations export
# ---------------------------------------------------------------------------


async def export_locations_rows(session: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    """Return all locations for *user_id* as a list of dicts.

    Exported columns: id, name, address, latitude, longitude, is_free,
    default_cost_per_kwh_p, radius_m.

    Note: the Location model stores the centroid as ``centroid_lat`` /
    ``centroid_lng``.  We export them under the friendlier names ``latitude``
    / ``longitude`` for consumer readability.
    """
    stmt = select(Location).where(Location.user_id == user_id).order_by(Location.id.asc())
    result = await session.execute(stmt)

    rows: list[dict[str, Any]] = []
    for (loc,) in result.all():
        rows.append(
            {
                "id": loc.id,
                "name": loc.name,
                "address": loc.address,
                "latitude": loc.centroid_lat,
                "longitude": loc.centroid_lng,
                "is_free": loc.is_free,
                "default_cost_per_kwh_p": loc.default_cost_per_kwh_p,
                "radius_m": loc.radius_m,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------

# Spreadsheet apps (Excel, LibreOffice, Sheets) interpret a cell whose text
# begins with one of these characters as a formula. An exported free-text
# value such as ``=cmd|'/c calc'!A0`` would then execute when the file is
# opened — CSV injection. See OWASP "CSV Injection".
_CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe_cell(value: Any) -> Any:
    """Neutralise CSV/formula injection by quoting risky string cells.

    A string starting with a formula trigger is prefixed with a single quote
    so the spreadsheet renders it as literal text. Non-string cells (numbers,
    dates, ``None``) are returned unchanged.
    """
    if isinstance(value, str) and value and value[0] in _CSV_FORMULA_TRIGGERS:
        return "'" + value
    return value


def rows_to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """Serialise *rows* to a CSV string with *columns* as the header.

    Uses ``csv.DictWriter`` with ``extrasaction="ignore"`` so callers can
    pass a full dict even when *columns* is a subset.  All values are
    converted to strings by the CSV writer; ``None`` becomes an empty cell.
    String cells are passed through :func:`_csv_safe_cell` first to defuse
    spreadsheet formula injection.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=columns,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows({k: _csv_safe_cell(v) for k, v in row.items()} for row in rows)
    return buf.getvalue()


def rows_to_json(rows: list[dict[str, Any]]) -> str:
    """Serialise *rows* to a JSON string.

    ``default=str`` converts non-serialisable types (``date``, ``datetime``,
    ``Decimal``) to their string representations so no explicit per-column
    conversion is needed.
    """
    return json.dumps(rows, default=str)
