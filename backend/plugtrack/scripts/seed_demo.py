# backend/plugtrack/scripts/seed_demo.py
"""Populate a throwaway demo SQLite database with fully-fictional, realistic
data so that every PlugTrack UI chart and page renders with meaningful content.

Safety
------
- Target is resolved from ``--db`` / ``PLUGTRACK_DEMO_DB`` (default
  ``./data/demo.db``).
- The script REFUSES to run unless the resolved path **basename** contains the
  word "demo".  This prevents any accidental write to ``plugtrack.db`` or any
  production file.
- The demo file is deleted and recreated on every run (idempotent; schema is
  always fresh).
- No import of any production DB — a dedicated engine is built from the demo
  path.

Usage
-----
    python -m plugtrack.scripts.seed_demo                    # default ./data/demo.db
    python -m plugtrack.scripts.seed_demo --db /tmp/demo.db
    PLUGTRACK_DEMO_DB=/tmp/demo.db python -m plugtrack.scripts.seed_demo
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the backend package root is importable when run as __main__
# ---------------------------------------------------------------------------
_BACKEND_ROOT = Path(__file__).resolve().parents[3]  # …/backend
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# We need APP_SECRET_KEY for the VIN encryption path — set a demo one if
# not already in the environment.
_DEMO_SECRET = "demo-seed-secret-key-for-demo-only-not-production-use"
os.environ.setdefault("APP_SECRET_KEY", _DEMO_SECRET)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from plugtrack.models import (
    Base,
    Car,
    CarMileageYear,
    ChargingSession,
    Location,
    User,
)
from plugtrack.security.crypto import hash_password
from plugtrack.settings.catalogue import CATALOGUE

# ---------------------------------------------------------------------------
# Demo credentials (printed at end)
# ---------------------------------------------------------------------------
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-plugtrack"

# ---------------------------------------------------------------------------
# Fictional data constants
# ---------------------------------------------------------------------------
# All coords centred around a fictional city "Voltston" (~52.5°N, 1.0°W —
# plausible UK cluster so Leaflet renders sensible tiles)
_BASE_LAT = 52.4862
_BASE_LNG = -1.8904

LOCATIONS_SPEC = [
    # name, is_home, is_free, rate_p, network, lat_off, lng_off
    ("Home", True, False, 28.0, None, 0.000, 0.000),
    ("Voltway Riverside", False, False, 55.0, "Voltway", 0.012, 0.018),
    ("Sparkr Market Square", False, False, 65.0, "Sparkr", -0.008, 0.031),
    ("Hedron Services", False, False, 79.0, "Hedron", 0.023, -0.025),
    ("Pulse Retail Park", False, True, None, "Pulse", -0.015, -0.012),
    ("Ampr Maple Street", False, False, 45.0, "Ampr", 0.007, 0.041),
]


# ---------------------------------------------------------------------------
# Helper: build a realistic DC charge curve
# Power peaks early then tapers as SoC climbs.  Returns [[t_s, soc, kw], …]
# ---------------------------------------------------------------------------
def _make_dc_curve(start_soc: int, end_soc: int, peak_kw: float = 120.0) -> list:
    points = []
    soc_range = end_soc - start_soc
    steps = max(10, soc_range)
    for i in range(steps + 1):
        frac = i / steps
        soc = start_soc + round(frac * soc_range)
        # Gaussian-like taper: peak ~30% into charge, falls to ~35 kW at 80%
        taper_frac = math.exp(-3.5 * (frac - 0.2) ** 2)
        # At high SoC (>80%) additional hard taper
        high_soc_penalty = max(0.0, (soc - 75) / 25) ** 1.5
        power = max(10.0, peak_kw * taper_frac * (1 - 0.85 * high_soc_penalty))
        t_seconds = round(i * (soc_range / steps) * 3600 / (power / 1000 * 1000 / 60))  # rough
        # Simple: assume energy at peak_kw/2 average for time estimate
        t_seconds = round(frac * (soc_range / 100 * 58 / (peak_kw * 0.5)) * 3600)
        points.append([t_seconds, soc, round(power, 1)])
    return points


# ---------------------------------------------------------------------------
# Main seeding coroutine
# ---------------------------------------------------------------------------
async def seed(demo_db_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{demo_db_path.as_posix()}"
    engine = create_async_engine(url, future=True)

    # Create schema fresh
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as s:
        # ----------------------------------------------------------------
        # 1. Settings — seed catalogue defaults then override key ones
        # ----------------------------------------------------------------
        from plugtrack.models import Setting

        for entry in CATALOGUE:
            s.add(
                Setting(
                    key=entry.key,
                    value=entry.default_value,
                    value_type=entry.value_type,
                    group_name=entry.group_name,
                    label=entry.label,
                    description=entry.description,
                    default_value=entry.default_value,
                    is_secret=entry.is_secret,
                )
            )
        await s.flush()

        # Override key settings so the UI renders fully
        overrides = {
            "distance_unit": "mi",
            "currency": "GBP",
            "default_home_rate_p_per_kwh": "28.0",
            "petrol_price_p_per_litre": "154.9",
            "petrol_mpg": "48.0",
            "home_charge_fallback_kw": "2.3",
        }
        for key, value in overrides.items():
            stmt_result = await s.get(Setting, key)
            if stmt_result:
                stmt_result.value = value
        await s.flush()

        # ----------------------------------------------------------------
        # 2. Admin / demo user
        # ----------------------------------------------------------------
        user = User(
            username=DEMO_USERNAME,
            password_hash=hash_password(DEMO_PASSWORD),
        )
        s.add(user)
        await s.flush()
        uid = user.id

        # ----------------------------------------------------------------
        # 3. Cars
        # ----------------------------------------------------------------
        # Active car
        active_car = Car(
            user_id=uid,
            make="Volterra",
            model="Arc",
            name="Demo EV",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=3.8,
            max_ac_kw=11.0,
            max_dc_kw=150.0,
            provider="manual",
            active=True,
        )
        # Set VIN via property (handles encryption)
        active_car.vin = "WVOLT00DEMO00001"
        s.add(active_car)

        # Archived car
        archived_car = Car(
            user_id=uid,
            make="Volterra",
            model="Mini",
            name="Old Runabout",
            battery_kwh=38.0,
            nominal_efficiency_mi_per_kwh=4.2,
            max_ac_kw=7.4,
            max_dc_kw=50.0,
            provider="manual",
            active=False,
        )
        archived_car.vin = "WVOLT00DEMO00002"
        s.add(archived_car)

        await s.flush()
        car1_id = active_car.id
        car2_id = archived_car.id

        # ----------------------------------------------------------------
        # 4. Locations
        # ----------------------------------------------------------------
        loc_ids: dict[str, int] = {}
        for name, is_home, is_free, rate_p, network, lat_off, lng_off in LOCATIONS_SPEC:
            loc = Location(
                user_id=uid,
                name=name,
                centroid_lat=_BASE_LAT + lat_off,
                centroid_lng=_BASE_LNG + lng_off,
                radius_m=100,
                address=f"{name}, Voltston, VS1 {abs(hash(name)) % 9 + 1}AA",
                is_home=is_home,
                is_free=is_free,
                default_cost_per_kwh_p=rate_p,
                default_charge_network=network,
                visit_count=0,
            )
            s.add(loc)
            await s.flush()
            loc_ids[name] = loc.id

        # ----------------------------------------------------------------
        # 5. Charging sessions (~35 rows across ~4 months)
        # ----------------------------------------------------------------
        # We keep a running odometer in km, advancing it realistically.
        # Active car starts at 5,000 km, archived at 12,000 km (older).
        # ~3.8 mi/kWh efficiency → ~6.1 km/kWh consumption
        KM_PER_KWH = 3.8 * 1.60934  # ≈ 6.12

        def _odo_advance(odo: float, kwh: float) -> float:
            return round(odo + kwh * KM_PER_KWH, 1)

        def _utc(d: date, hour: int = 12, minute: int = 0) -> datetime:
            return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=UTC)

        # ---- Helper to add a session ----
        def _session(
            car_id: int,
            session_date: date,
            start_soc: int,
            end_soc: int,
            kwh: float,
            odo: float,
            location_name: str,
            charging_type: str,
            charge_start: datetime,
            charge_end: datetime,
            source: str = "telegram",
            charging_mode: str = "manual",
            power_curve: list | None = None,
            actual_charge_seconds: int | None = None,
            network: str | None = None,
        ) -> ChargingSession:
            loc_id = loc_ids[location_name]
            net = (
                network
                or LOCATIONS_SPEC[
                    next(i for i, s in enumerate(LOCATIONS_SPEC) if s[0] == location_name)
                ][4]
            )
            is_free = LOCATIONS_SPEC[
                next(i for i, s in enumerate(LOCATIONS_SPEC) if s[0] == location_name)
            ][2]
            rate_p = LOCATIONS_SPEC[
                next(i for i, s in enumerate(LOCATIONS_SPEC) if s[0] == location_name)
            ][3]
            is_home = LOCATIONS_SPEC[
                next(i for i, s in enumerate(LOCATIONS_SPEC) if s[0] == location_name)
            ][1]

            if is_free:
                cost_p = 0
                cost_basis = "location_free"
                tariff = None
            elif rate_p is not None:
                if is_home:
                    cost_basis = "home_rate"
                else:
                    cost_basis = "location_rate"
                tariff = rate_p
                cost_p = round(kwh * rate_p)
            else:
                cost_p = None
                cost_basis = "unknown"
                tariff = None

            kwh_calc = (
                round((end_soc - start_soc) / 100 * 58.0, 2)
                if car_id == car1_id
                else round((end_soc - start_soc) / 100 * 38.0, 2)
            )

            return ChargingSession(
                user_id=uid,
                car_id=car_id,
                date=session_date,
                charge_start_at=charge_start,
                charge_end_at=charge_end,
                start_soc=start_soc,
                end_soc=end_soc,
                kwh_added=kwh,
                kwh_calculated=kwh_calc,
                odometer_at_session_km=odo,
                charging_type=charging_type,
                charging_mode=charging_mode,
                actual_charge_seconds=actual_charge_seconds,
                interrupted=False,
                cost_pence=cost_p,
                cost_basis=cost_basis,
                tariff_p_per_kwh=tariff,
                location_id=loc_id,
                charge_network=net,
                source=source,
                power_curve=power_curve,
            )

        sessions_to_add: list[ChargingSession] = []

        # --- Archived car sessions (4 sessions, Jan-Feb 2026) ---
        arch_odo = 12000.0
        arch_sessions = [
            # (date, s_soc, e_soc, kwh, type, loc, hour_start, duration_h, source)
            (date(2026, 1, 8), 20, 80, 22.8, "ac", "Home", 22, 8, "import"),
            (date(2026, 1, 22), 15, 75, 22.8, "ac", "Home", 23, 8, "import"),
            (date(2026, 2, 5), 25, 70, 17.1, "dc", "Voltway Riverside", 11, 1, "telegram"),
            (date(2026, 2, 19), 18, 82, 24.3, "ac", "Home", 22, 9, "import"),
        ]
        for d, ss, es, kwh, ctype, loc, h_start, dur_h, src in arch_sessions:
            cs = _session(
                car_id=car2_id,
                session_date=d,
                start_soc=ss,
                end_soc=es,
                kwh=kwh,
                odo=arch_odo,
                location_name=loc,
                charging_type=ctype,
                charge_start=_utc(d, h_start),
                charge_end=_utc(d, h_start) + timedelta(hours=dur_h),
                source=src,
                actual_charge_seconds=round(kwh / 2.3 * 3600)
                if ctype == "ac"
                else round(dur_h * 3600),
            )
            sessions_to_add.append(cs)
            arch_odo = _odo_advance(arch_odo, kwh)

        # --- Active car sessions (~31 sessions, Mar-Jun 2026) ---
        odo = 5000.0

        # Session plan: (date, s_soc, e_soc, kwh, type, loc, hour_start, dur_h, src, curve?)
        # Realistic mix: mostly home AC overnight, some public DC
        # actual_charge_seconds for AC = kwh/2.3*3600 (granny ~2.3 kW)
        # Wall-clock duration for AC is much longer (overnight plug-in)
        active_sessions_plan = [
            # March
            (date(2026, 3, 1), 22, 80, 18.8, "ac", "Home", 22, 10, "telegram", False),
            (date(2026, 3, 5), 18, 90, 22.6, "dc", "Voltway Riverside", 10, 1, "telegram", True),
            (date(2026, 3, 9), 30, 85, 17.9, "ac", "Home", 23, 10, "import", False),
            (
                date(2026, 3, 14),
                15,
                80,
                23.8,
                "dc",
                "Sparkr Market Square",
                13,
                1,
                "telegram",
                True,
            ),
            (date(2026, 3, 18), 25, 88, 18.2, "ac", "Home", 22, 9, "telegram", False),
            (date(2026, 3, 22), 20, 75, 16.0, "dc", "Hedron Services", 9, 1, "telegram", False),
            (date(2026, 3, 26), 28, 85, 16.6, "ac", "Home", 22, 8, "import", False),
            (date(2026, 3, 30), 32, 80, 14.0, "dc", "Pulse Retail Park", 15, 1, "telegram", False),
            # April
            (date(2026, 4, 3), 20, 82, 18.0, "ac", "Home", 23, 9, "telegram", False),
            (date(2026, 4, 8), 15, 80, 19.0, "dc", "Ampr Maple Street", 12, 1, "telegram", True),
            (date(2026, 4, 11), 28, 88, 17.4, "ac", "Home", 22, 8, "manual", False),
            (date(2026, 4, 15), 22, 78, 16.2, "dc", "Voltway Riverside", 11, 1, "telegram", False),
            (date(2026, 4, 18), 30, 85, 15.9, "ac", "Home", 23, 8, "telegram", False),
            (date(2026, 4, 22), 18, 80, 18.0, "dc", "Hedron Services", 14, 1, "telegram", False),
            (date(2026, 4, 26), 25, 87, 18.0, "ac", "Home", 22, 9, "import", False),
            (date(2026, 4, 30), 20, 75, 16.0, "dc", "Pulse Retail Park", 16, 1, "telegram", False),
            # May
            (date(2026, 5, 3), 22, 82, 17.4, "ac", "Home", 23, 9, "telegram", False),
            (
                date(2026, 5, 7),
                10,
                80,
                21.6,
                "dc",
                "Sparkr Market Square",
                10,
                1,
                "telegram",
                False,
            ),
            (date(2026, 5, 11), 28, 85, 16.6, "ac", "Home", 22, 8, "telegram", False),
            (date(2026, 5, 15), 20, 82, 18.0, "dc", "Voltway Riverside", 9, 1, "telegram", False),
            (date(2026, 5, 18), 30, 88, 16.8, "ac", "Home", 22, 8, "import", False),
            (date(2026, 5, 22), 18, 79, 17.7, "dc", "Ampr Maple Street", 13, 1, "telegram", False),
            (date(2026, 5, 26), 25, 85, 17.4, "ac", "Home", 23, 9, "telegram", False),
            (date(2026, 5, 30), 22, 72, 14.5, "dc", "Pulse Retail Park", 15, 1, "telegram", False),
            # June
            (date(2026, 6, 2), 20, 82, 18.0, "ac", "Home", 22, 9, "telegram", False),
            (date(2026, 6, 5), 15, 80, 19.0, "dc", "Voltway Riverside", 11, 1, "telegram", False),
            (date(2026, 6, 8), 28, 86, 16.8, "ac", "Home", 22, 8, "telegram", False),
            (date(2026, 6, 11), 20, 78, 16.8, "dc", "Hedron Services", 10, 1, "manual", False),
            (date(2026, 6, 14), 25, 85, 17.4, "ac", "Home", 23, 9, "telegram", False),
            (
                date(2026, 6, 17),
                18,
                80,
                18.0,
                "dc",
                "Sparkr Market Square",
                12,
                1,
                "telegram",
                False,
            ),
            (date(2026, 6, 20), 30, 88, 16.8, "ac", "Home", 22, 8, "telegram", False),
        ]

        dc_curve_slots = {0, 1, 3, 7}  # indices of DC sessions that get a power_curve
        dc_session_idx = 0

        for (
            d,
            ss,
            es,
            kwh,
            ctype,
            loc,
            h_start,
            dur_h,
            src,
            _has_curve_flag,
        ) in active_sessions_plan:
            has_curve = False
            if ctype == "dc":
                has_curve = dc_session_idx in dc_curve_slots
                dc_session_idx += 1

            curve = _make_dc_curve(ss, es, peak_kw=120.0) if has_curve else None

            if ctype == "ac":
                # AC: actual_charge_seconds = real energy-draw time (~2.3 kW granny)
                actual_secs = round(kwh / 2.3 * 3600)
                # Wall-clock spans the overnight window (longer)
                charge_start = _utc(d, h_start)
                charge_end = _utc(d, h_start) + timedelta(hours=dur_h)
            else:
                actual_secs = round(dur_h * 3600)
                charge_start = _utc(d, h_start)
                charge_end = charge_start + timedelta(hours=dur_h)

            cs = _session(
                car_id=car1_id,
                session_date=d,
                start_soc=ss,
                end_soc=es,
                kwh=kwh,
                odo=odo,
                location_name=loc,
                charging_type=ctype,
                charge_start=charge_start,
                charge_end=charge_end,
                source=src,
                charging_mode="timer" if ctype == "ac" else "manual",
                power_curve=curve,
                actual_charge_seconds=actual_secs,
            )
            sessions_to_add.append(cs)
            odo = _odo_advance(odo, kwh)

        for sess in sessions_to_add:
            s.add(sess)
        await s.flush()

        # Update location visit counts (rough)
        loc_visit_counts: dict[str, int] = {}
        for sess in sessions_to_add:
            for loc_name, loc_id in loc_ids.items():
                if sess.location_id == loc_id:
                    loc_visit_counts[loc_name] = loc_visit_counts.get(loc_name, 0) + 1

        for loc_name, count in loc_visit_counts.items():
            loc_id = loc_ids[loc_name]
            result = await s.get(Location, loc_id)
            if result:
                result.visit_count = count

        # ----------------------------------------------------------------
        # 6. CarMileageYear for active car
        # ----------------------------------------------------------------
        first_session_odo = 5000.0  # opening odometer
        mileage_year = CarMileageYear(
            user_id=uid,
            car_id=car1_id,
            period_start_date=date(2026, 1, 1),
            period_end_date=date(2026, 12, 31),
            opening_odometer_km=first_session_odo,
            closing_odometer_km=None,  # active — still open
            # 10,000 miles ≈ 16,093 km
            annual_mileage_target_km=16093.0,
        )
        s.add(mileage_year)

        await s.commit()

    await engine.dispose()


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------
def _resolve_db_path(raw: str | None) -> Path:
    if raw:
        p = Path(raw).resolve()
    else:
        env_val = os.environ.get("PLUGTRACK_DEMO_DB")
        if env_val:
            p = Path(env_val).resolve()
        else:
            # Default: ./data/demo.db relative to cwd
            p = Path("./data/demo.db").resolve()
    return p


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed a demo SQLite DB with fictional PlugTrack data."
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help="Path to the demo SQLite file (default: ./data/demo.db or $PLUGTRACK_DEMO_DB)",
    )
    args = parser.parse_args()

    db_path = _resolve_db_path(args.db)

    # Safety guard: basename must contain "demo"
    if "demo" not in db_path.name.lower():
        print(
            f"ERROR: Refusing to run — target path basename does not contain 'demo'.\n"
            f"  Resolved path: {db_path}\n"
            f"  Provide a path whose filename contains 'demo', e.g. ./data/demo.db",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"WARNING: This will WIPE and recreate {db_path}")
    print("         (demo seed — no production data is touched)")
    print()

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing demo file so schema is always fresh
    if db_path.exists():
        db_path.unlink()
        print(f"  Removed existing file: {db_path}")

    asyncio.run(seed(db_path))

    print()
    print("Demo DB seeded successfully.")
    print(f"  Path:     {db_path}")
    print(f"  Login:    username={DEMO_USERNAME!r}  password={DEMO_PASSWORD!r}")
    print()
    print("Run the backend against it:")
    print(f"  DATABASE_URL=sqlite+aiosqlite:///{db_path.as_posix()} \\")
    print("  COOKIE_SECURE=false \\")
    print("  uvicorn plugtrack.main:create_app --factory --port 9278")


if __name__ == "__main__":
    main()
