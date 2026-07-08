"""Build + publish a PlugTrack summary to MQTT for Home Assistant.

The payload is derived from the existing aggregators and converted to the
user-facing units (pence -> GBP, km -> miles) at the source, so the HA
`mqtt:` sensors can carry proper device/state classes.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

import aiomqtt
from sqlalchemy import select

from plugtrack.bootstrap import get_settings
from plugtrack.models.charging_session import ChargingSession
from plugtrack.models.location import Location
from plugtrack.models.setting import Setting
from plugtrack.models.user import User
from plugtrack.security.crypto import decrypt_secret
from plugtrack.services import insights_stats
from plugtrack.services.dashboard_service import dashboard_summary
from plugtrack.services.formatting import km_to_mi

log = logging.getLogger(__name__)


def _gbp(pence: int | None) -> float | None:
    return None if pence is None else round(pence / 100.0, 2)


def _mi(km: float | None) -> float | None:
    return None if km is None else round(km_to_mi(km), 1)


async def _latest_session(session, user_id: int, car_id: int):
    """Return (ChargingSession, resolved_location_name) for the latest charge.

    `ChargingSession` has no `location_name` column — it carries `location_id`
    (FK to `location`) plus a free-text `user_label`. The name is resolved via
    a LEFT JOIN to `location.name`, falling back to `user_label`.
    """
    res = (
        await session.execute(
            select(ChargingSession, Location.name)
            .join(Location, Location.id == ChargingSession.location_id, isouter=True)
            .where(
                ChargingSession.user_id == user_id,
                ChargingSession.car_id == car_id,
            )
            .order_by(ChargingSession.date.desc(), ChargingSession.id.desc())
            .limit(1)
        )
    ).first()
    if res is None:
        return None, None
    row, loc_name = res
    return row, loc_name


async def build_ha_payload(session, *, user_id: int, today: dt.date | None = None) -> dict | None:
    if today is None:
        today = dt.datetime.now(dt.UTC).date()

    summary = await dashboard_summary(session, user_id, today=today)
    if not summary.cars:
        return None
    car = summary.cars[0]
    car_id = car.id

    lo = today.replace(day=1)
    hi = today

    wt = await insights_stats.window_totals(session, user_id=user_id, lo=lo, hi=hi, car_id=car_id)
    split = await insights_stats.home_public_split(
        session, user_id=user_id, date_from=lo, date_to=hi, car_id=car_id
    )
    month_miles_km = await insights_stats.miles_driven_km(
        session, user_id=user_id, lo=lo, hi=hi, car_id=car_id
    )
    allowance = await insights_stats.mileage_allowance_view(
        session, user_id=user_id, car_id=car_id, today=today
    )

    home_kwh = float(split.get("home", {}).get("kwh") or 0.0)
    public_kwh = float(split.get("public", {}).get("kwh") or 0.0)
    total_kwh = home_kwh + public_kwh
    home_pct = round(100 * home_kwh / total_kwh) if total_kwh else None
    public_pct = (100 - home_pct) if home_pct is not None else None

    last, last_loc = await _latest_session(session, user_id, car_id)
    last_charge = None
    if last is not None:
        ts = last.charge_end_at
        last_charge = {
            "kwh": round(float(last.kwh_added or 0.0), 2),
            "cost_gbp": _gbp(last.cost_pence),
            "network": last.charge_network,
            "location": last_loc or last.user_label,
            "end_soc_pct": last.end_soc,
            "ts": ts.isoformat() if ts is not None else None,
        }

    # Prefer the tracked mileage-year odometer; fall back to the latest
    # session's reading so the value survives mileage tracking being off.
    odo_km = car.mileage_year.current_odometer_km if car.mileage_year else None
    if odo_km is None and last is not None:
        odo_km = last.odometer_at_session_km

    return {
        "car": f"{car.make} {car.model}".strip(),
        "last_charge": last_charge,
        "cost_per_mile_gbp": _gbp(
            round(summary.cost_per_mile.rolling_30d_pence)
            if summary.cost_per_mile.rolling_30d_pence is not None
            else None
        ),
        "battery_soc_pct": car.battery_level,
        "odometer_mi": _mi(odo_km),
        "annual_mileage": {
            "target_mi": _mi(allowance.get("target_km")),
            "projected_mi": _mi(allowance.get("projected_year_end_km")),
            "pace": allowance.get("pace"),
        },
        "month": {
            "spend_gbp": _gbp(wt.get("spend_pence")),
            "energy_kwh": round(float(wt.get("kwh") or 0.0), 2),
            "miles": _mi(month_miles_km),
            "home_pct": home_pct,
            "public_pct": public_pct,
        },
        "lifetime": {
            "energy_kwh": round(float(summary.lifetime_totals.kwh or 0.0), 2),
            "cost_gbp": _gbp(summary.lifetime_totals.cost_pence),
        },
    }


async def publish_summary(
    payload: dict,
    *,
    host: str,
    port: int = 1883,
    username: str | None = None,
    password: str | None = None,
    base_topic: str = "plugtrack",
) -> None:
    async with aiomqtt.Client(
        hostname=host,
        port=port,
        username=username or None,
        password=password or None,
    ) as client:
        await client.publish(
            f"{base_topic}/summary",
            payload=json.dumps(payload),
            qos=0,
            retain=True,
        )


def _decrypt_or_plain(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return decrypt_secret(value, get_settings().app_secret_key)
    except Exception:  # noqa: BLE001 — plaintext fallback (mirrors main.py digest tick)
        return value


async def _read_mqtt_settings(session) -> dict:
    keys = {
        "mqtt_enabled",
        "mqtt_host",
        "mqtt_port",
        "mqtt_username",
        "mqtt_password",
        "mqtt_base_topic",
    }
    rows = (await session.execute(select(Setting).where(Setting.key.in_(keys)))).scalars().all()
    return {r.key: r.value for r in rows}


async def run_ha_publish_tick(sessionmaker, *, publisher=publish_summary, today=None) -> None:
    """Best-effort: build + publish the summary. Never raises."""
    try:
        async with sessionmaker() as session:
            cfg = await _read_mqtt_settings(session)
            if (cfg.get("mqtt_enabled") or "").lower() != "true":
                return
            host = cfg.get("mqtt_host")
            if not host:
                return
            user = (await session.execute(select(User))).scalars().first()
            if user is None:
                return
            payload = await build_ha_payload(session, user_id=user.id, today=today)
            if payload is None:
                return
        await publisher(
            payload,
            host=host,
            port=int(cfg.get("mqtt_port") or 1883),
            username=cfg.get("mqtt_username"),
            password=_decrypt_or_plain(cfg.get("mqtt_password")),
            base_topic=cfg.get("mqtt_base_topic") or "plugtrack",
        )
    except Exception:  # noqa: BLE001 — a publish failure must never crash the caller
        log.exception("ha_publisher: publish tick failed")
