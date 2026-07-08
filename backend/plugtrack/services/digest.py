"""Digest content builders for weekly and monthly Telegram messages.

``build_weekly_digest`` → previous Mon–Sun week relative to *now* (Europe/London).
``build_monthly_digest`` → previous calendar month.

Both return ``None`` when the reported window has zero sessions.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Car, Setting
from .formatting import format_currency, format_distance
from .insights_stats import home_public_split, miles_driven_km, window_totals
from .mileage_tracking import get_status as mileage_get_status

LONDON = ZoneInfo("Europe/London")

# ---------------------------------------------------------------------------
# Delta helper
# ---------------------------------------------------------------------------


def _delta_phrase(cur: float, prev: float) -> str:
    """Render a relative change as 'up N%', 'down N%', or 'flat'.

    When *prev* is zero the comparison is undefined; returns '' (empty string)
    so callers can choose to omit the parenthetical.
    """
    if prev == 0:
        return ""
    pct = round((cur - prev) / prev * 100)
    if pct > 0:
        return f"up {pct}%"
    if pct < 0:
        return f"down {-pct}%"
    return "flat"


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


async def _str_setting(session: AsyncSession, key: str, default: str) -> str:
    row = (
        await session.execute(select(Setting.value).where(Setting.key == key))
    ).scalar_one_or_none()
    if row is None or row == "":
        return default
    return row


# ---------------------------------------------------------------------------
# Mileage pace verdict
# ---------------------------------------------------------------------------


def _pace_verdict(
    days_elapsed: int,
    days_total: int,
    used_km: float,
    target_km: float,
) -> str:
    """Return 'on track', 'ahead', or 'behind' the annual target.

    'Ahead' means projected mileage is *less* than the target (under-driving).
    'Behind' means projected mileage is *more* than the target (over-driving).
    Thresholds: ±2% of target.
    """
    if days_elapsed <= 0 or days_total <= 0:
        return "on track"
    projected_used = used_km / days_elapsed * days_total
    if projected_used <= target_km * 0.98:
        return "ahead"
    if projected_used >= target_km * 1.02:
        return "behind"
    return "on track"


async def _pace_lines(
    session: AsyncSession,
    *,
    user_id: int,
    active_cars: list[Car],
    today: dt.date,
    distance_unit: str,
) -> list[str]:
    """Build one pace-verdict line per active car (only when tracking is enabled)."""
    lines: list[str] = []
    for car in active_cars:
        status = await mileage_get_status(session, user_id=user_id, car_id=car.id, today=today)
        if not status.enabled or status.current_period is None:
            continue
        cp = status.current_period
        target_km = cp.annual_mileage_target_km
        if target_km is None or target_km <= 0:
            continue

        opening = cp.opening_odometer_km
        current = cp.current_odometer_km
        used_km = max(0.0, current - opening)

        days_total = (cp.period_end_date - cp.period_start_date).days + 1
        days_elapsed = max(0, min((today - cp.period_start_date).days + 1, days_total))

        verdict = _pace_verdict(days_elapsed, days_total, used_km, target_km)

        used_disp = format_distance(used_km, distance_unit)
        target_disp = format_distance(target_km, distance_unit)

        lines.append(f"{car.display_name} — {verdict}: {used_disp}/{target_disp} this period")
    return lines


# ---------------------------------------------------------------------------
# Week/month boundary helpers
# ---------------------------------------------------------------------------


def _reported_week(now: dt.datetime) -> tuple[dt.date, dt.date]:
    """Return (lo, hi) for the previous Mon–Sun week relative to *now* in London time."""
    local_date = now.astimezone(LONDON).date()
    # Monday of the current week
    this_monday = local_date - dt.timedelta(days=local_date.weekday())
    # Previous week
    rep_monday = this_monday - dt.timedelta(days=7)
    rep_sunday = rep_monday + dt.timedelta(days=6)
    return rep_monday, rep_sunday


def _reported_month(now: dt.datetime) -> tuple[dt.date, dt.date]:
    """Return (lo, hi) for the previous calendar month relative to *now* in London."""
    local_date = now.astimezone(LONDON).date()
    first_this = local_date.replace(day=1)
    last_prev = first_this - dt.timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev, last_prev


# ---------------------------------------------------------------------------
# Core block (shared by both digests)
# ---------------------------------------------------------------------------


async def _core_block(
    session: AsyncSession,
    *,
    user_id: int,
    rep_lo: dt.date,
    rep_hi: dt.date,
    prv_lo: dt.date,
    prv_hi: dt.date,
    currency: str,
    distance_unit: str,
) -> tuple[dict, dict, float | None, float | None]:
    """Fetch window_totals + miles for rep + prev windows.

    Returns (rep_totals, prv_totals, rep_miles_km, prv_miles_km).
    """
    rep = await window_totals(session, user_id=user_id, lo=rep_lo, hi=rep_hi)
    prv = await window_totals(session, user_id=user_id, lo=prv_lo, hi=prv_hi)
    rep_km = await miles_driven_km(session, user_id=user_id, lo=rep_lo, hi=rep_hi)
    prv_km = await miles_driven_km(session, user_id=user_id, lo=prv_lo, hi=prv_hi)
    return rep, prv, rep_km, prv_km


def _metric_line(label: str, value: str, delta: str, vs_label: str) -> str:
    """Format a single metric line, optionally appending delta."""
    if delta:
        return f"{label}: {value}  ({delta} vs {vs_label})"
    return f"{label}: {value}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_weekly_digest(
    session: AsyncSession,
    *,
    user_id: int,
    now: dt.datetime,
) -> str | None:
    """Build a weekly digest string for the previous Mon–Sun week.

    Returns ``None`` when the reported week has zero sessions.
    """
    rep_lo, rep_hi = _reported_week(now)
    prv_lo = rep_lo - dt.timedelta(days=7)
    prv_hi = rep_lo - dt.timedelta(days=1)

    currency = await _str_setting(session, "currency", "GBP")
    distance_unit = await _str_setting(session, "distance_unit", "mi")

    rep, prv, rep_km, prv_km = await _core_block(
        session,
        user_id=user_id,
        rep_lo=rep_lo,
        rep_hi=rep_hi,
        prv_lo=prv_lo,
        prv_hi=prv_hi,
        currency=currency,
        distance_unit=distance_unit,
    )

    if rep["sessions"] == 0:
        return None

    # Header (cross-platform: use %d then lstrip '0')
    def _fmt_day(d: dt.date) -> str:
        return d.strftime("%d %b").lstrip("0")

    header = (
        f"\U0001f4ca Weekly recap  {_fmt_day(rep_lo)} – {rep_hi.strftime('%d %b %Y').lstrip('0')}"
    )

    lines = [header, ""]

    # Spend
    spend_str = format_currency(rep["spend_pence"], currency)
    spend_delta = _delta_phrase(rep["spend_pence"], prv["spend_pence"])
    lines.append(_metric_line("Spend", spend_str, spend_delta, "prev week"))

    # Energy
    kwh_str = f"{round(rep['kwh'])} kWh"
    kwh_delta = _delta_phrase(rep["kwh"], prv["kwh"])
    lines.append(_metric_line("Energy", kwh_str, kwh_delta, "prev week"))

    # Miles driven (if available)
    if rep_km is not None:
        miles_str = format_distance(rep_km, distance_unit)
        miles_delta = _delta_phrase(rep_km, prv_km or 0.0)
        lines.append(_metric_line("Driven", miles_str, miles_delta, "prev week"))

    # Per-car mileage pace
    today = now.astimezone(LONDON).date()
    active_cars = list(
        (await session.execute(select(Car).where(Car.user_id == user_id, Car.active.is_(True))))
        .scalars()
        .all()
    )
    pace_lines = await _pace_lines(
        session,
        user_id=user_id,
        active_cars=active_cars,
        today=today,
        distance_unit=distance_unit,
    )
    lines.extend(pace_lines)

    return "\n".join(lines)


async def build_monthly_digest(
    session: AsyncSession,
    *,
    user_id: int,
    now: dt.datetime,
) -> str | None:
    """Build a monthly digest string for the previous calendar month.

    Returns ``None`` when the reported month has zero sessions.
    """
    rep_lo, rep_hi = _reported_month(now)
    prv_hi = rep_lo - dt.timedelta(days=1)
    prv_lo = prv_hi.replace(day=1)

    currency = await _str_setting(session, "currency", "GBP")
    distance_unit = await _str_setting(session, "distance_unit", "mi")

    rep, prv, rep_km, prv_km = await _core_block(
        session,
        user_id=user_id,
        rep_lo=rep_lo,
        rep_hi=rep_hi,
        prv_lo=prv_lo,
        prv_hi=prv_hi,
        currency=currency,
        distance_unit=distance_unit,
    )

    if rep["sessions"] == 0:
        return None

    # Previous month name for delta label
    prv_month_name = prv_lo.strftime("%B")
    rep_month_name = rep_lo.strftime("%B")

    # Header
    header = f"\U0001f4ca {rep_month_name} review"

    lines = [header, ""]

    # Spend
    spend_str = format_currency(rep["spend_pence"], currency)
    spend_delta = _delta_phrase(rep["spend_pence"], prv["spend_pence"])
    lines.append(_metric_line("Spend", spend_str, spend_delta, prv_month_name))

    # Energy
    kwh_str = f"{round(rep['kwh'])} kWh"
    kwh_delta = _delta_phrase(rep["kwh"], prv["kwh"])
    lines.append(_metric_line("Energy", kwh_str, kwh_delta, prv_month_name))

    # Miles driven
    if rep_km is not None:
        miles_str = format_distance(rep_km, distance_unit)
        miles_delta = _delta_phrase(rep_km, prv_km or 0.0)
        lines.append(_metric_line("Driven", miles_str, miles_delta, prv_month_name))

    # Home/public split
    split = await home_public_split(session, user_id=user_id, date_from=rep_lo, date_to=rep_hi)
    home_p = split["home"]["spend_pence"]
    pub_p = split["public"]["spend_pence"]
    total_split_p = home_p + pub_p
    if total_split_p > 0:
        home_pct = round(home_p / total_split_p * 100)
        pub_pct = 100 - home_pct
        lines.append(f"Home/public: {home_pct}% / {pub_pct}% of spend")

    # Per-car mileage pace
    today = now.astimezone(LONDON).date()
    active_cars = list(
        (await session.execute(select(Car).where(Car.user_id == user_id, Car.active.is_(True))))
        .scalars()
        .all()
    )
    pace_lines = await _pace_lines(
        session,
        user_id=user_id,
        active_cars=active_cars,
        today=today,
        distance_unit=distance_unit,
    )
    lines.extend(pace_lines)

    return "\n".join(lines)
