from __future__ import annotations

import datetime as dt

import pytest
from plugtrack.models import ChargingSession
from plugtrack.services import insights_stats as ins


async def _mk(
    sm,
    *,
    user_id,
    car_id,
    when,
    kwh,
    cost_pence,
    ctype="ac",
    network=None,
    source="manual",
    odometer_km=None,
):
    async with sm() as s:
        s.add(
            ChargingSession(
                user_id=user_id,
                car_id=car_id,
                date=when,
                start_soc=20,
                end_soc=80,
                kwh_added=kwh,
                charging_type=ctype,
                charging_mode="manual",
                cost_pence=cost_pence,
                cost_basis="home_rate" if cost_pence is not None else "unknown",
                charge_network=network,
                source=source,
                odometer_at_session_km=odometer_km,
                charge_end_at=dt.datetime.combine(when, dt.time(12, 0), tzinfo=dt.UTC),
            )
        )
        await s.commit()


def test_resolve_granularity():
    base = dt.date(2026, 1, 1)
    assert ins.resolve_granularity(base, base + dt.timedelta(days=10)) == "daily"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=31)) == "daily"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=60)) == "weekly"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=186)) == "weekly"
    assert ins.resolve_granularity(base, base + dt.timedelta(days=200)) == "monthly"


@pytest.mark.asyncio
async def test_over_time_buckets_daily(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 1),
        kwh=5.0,
        cost_pence=100,
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 3),
        kwh=8.0,
        cost_pence=None,
    )
    async with test_sessionmaker() as s:
        out = await ins.spend_energy_over_time(
            s,
            user_id=uid,
            date_from=dt.date(2026, 6, 1),
            date_to=dt.date(2026, 6, 30),
            granularity="daily",
        )
    assert out == [
        {"period": "2026-06-01", "spend_pence": 300, "kwh": 15.0, "sessions": 2},
        {"period": "2026-06-03", "spend_pence": 0, "kwh": 8.0, "sessions": 1},
    ]


@pytest.mark.asyncio
async def test_over_time_weekly_uses_monday(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    # 2026-06-03 is a Wednesday; its week-Monday is 2026-06-01.
    await _mk(
        test_sessionmaker, user_id=uid, car_id=car, when=dt.date(2026, 6, 3), kwh=4.0, cost_pence=80
    )
    async with test_sessionmaker() as s:
        out = await ins.spend_energy_over_time(
            s,
            user_id=uid,
            date_from=dt.date(2026, 1, 1),
            date_to=dt.date(2026, 6, 30),
            granularity="weekly",
        )
    assert out[0]["period"] == "2026-06-01"


@pytest.mark.asyncio
async def test_home_public_split(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
        ctype="ac",
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 2),
        kwh=30.0,
        cost_pence=1500,
        ctype="dc",
        network="Tesla",
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 3),
        kwh=5.0,
        cost_pence=None,
        ctype="dc",
    )
    async with test_sessionmaker() as s:
        split = await ins.home_public_split(s, user_id=uid, date_from=None, date_to=None)
    assert split["home"] == {"spend_pence": 200, "kwh": 10.0, "sessions": 1, "avg_p_per_kwh": 20.0}
    # public: cost only on the costed DC session; avg over costed kWh only (30.0)
    assert split["public"] == {
        "spend_pence": 1500,
        "kwh": 35.0,
        "sessions": 2,
        "avg_p_per_kwh": 50.0,
    }


@pytest.mark.asyncio
async def test_network_breakdown_ranked_and_unknown(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 1),
        kwh=30.0,
        cost_pence=1500,
        ctype="dc",
        network="Tesla",
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 2),
        kwh=10.0,
        cost_pence=200,
        ctype="ac",
        network=None,
    )
    async with test_sessionmaker() as s:
        rows = await ins.network_breakdown(s, user_id=uid, date_from=None, date_to=None)
    assert [r["network"] for r in rows] == ["Tesla", "Unknown"]
    assert rows[0]["spend_pence"] == 1500
    assert rows[1]["network"] == "Unknown" and rows[1]["spend_pence"] == 200


@pytest.mark.asyncio
async def test_network_breakdown_null_blank_unknown_string_collapsed(
    test_sessionmaker, seeded_user_car
):
    """NULL, empty-string, 'unknown', 'Unknown', 'none', 'n/a' all become one
    'Unknown' bucket. A real network name like 'Tesla' stays separate."""
    uid, car = seeded_user_car
    # NULL → "Unknown"
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
        ctype="dc",
        network=None,
    )
    # empty string → "Unknown"
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 2),
        kwh=5.0,
        cost_pence=None,
        ctype="dc",
        network="",
    )
    # lowercase "unknown" → should collapse into "Unknown" (not a separate bucket)
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 3),
        kwh=8.0,
        cost_pence=160,
        ctype="dc",
        network="unknown",
    )
    # title-case "Unknown" → already canonical "Unknown"
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 4),
        kwh=3.0,
        cost_pence=60,
        ctype="dc",
        network="Unknown",
    )
    # real network → stays as-is
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 5),
        kwh=30.0,
        cost_pence=1500,
        ctype="dc",
        network="Tesla",
    )

    async with test_sessionmaker() as s:
        rows = await ins.network_breakdown(s, user_id=uid, date_from=None, date_to=None)

    network_names = [r["network"] for r in rows]

    # Exactly two buckets: "Tesla" and "Unknown"
    assert sorted(network_names) == ["Tesla", "Unknown"], (
        f"Expected ['Tesla', 'Unknown'] but got {network_names!r}. "
        "Duplicate 'unknown'/''/None buckets should be collapsed."
    )
    # No lowercase "unknown" bucket
    assert "unknown" not in network_names, "Lowercase 'unknown' must be collapsed into 'Unknown'"

    unknown_row = next(r for r in rows if r["network"] == "Unknown")
    # 4 sessions collapsed: kwh=10+5+8+3=26, spend=200+0+160+60=420
    assert unknown_row["sessions"] == 4
    assert unknown_row["kwh"] == pytest.approx(26.0)
    assert unknown_row["spend_pence"] == 420

    tesla_row = next(r for r in rows if r["network"] == "Tesla")
    assert tesla_row["sessions"] == 1
    assert tesla_row["spend_pence"] == 1500


@pytest.mark.asyncio
async def test_efficiency_null_without_odometer(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 2),
        kwh=10.0,
        cost_pence=200,
    )
    async with test_sessionmaker() as s:
        out = await ins.efficiency_over_time(
            s,
            user_id=uid,
            date_from=dt.date(2026, 6, 1),
            date_to=dt.date(2026, 6, 30),
            granularity="daily",
        )
    assert out == [
        {
            "period": "2026-06-02",
            "observed_mi_per_kwh": None,
            "rolling_mi_per_kwh": None,
            "cost_per_mile_p": None,
        }
    ]


@pytest.mark.asyncio
async def test_efficiency_with_odometer_span(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    # Reference reading before the window, then a reading inside it: 160.9344 km = 100 mi driven.
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 5, 30),
        kwh=1.0,
        cost_pence=10,
        odometer_km=1000.0,
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 6, 2),
        kwh=25.0,
        cost_pence=500,
        odometer_km=1000.0 + 100 * 1.609344,
    )
    async with test_sessionmaker() as s:
        out = await ins.efficiency_over_time(
            s,
            user_id=uid,
            date_from=dt.date(2026, 6, 1),
            date_to=dt.date(2026, 6, 30),
            granularity="daily",
        )
    pt = next(p for p in out if p["period"] == "2026-06-02")
    # Cycle-based: 100 mi driven over the SoC drop consumed (80%→20% = 60% of
    # 58 kWh = 34.8 kWh) → 100 / 34.8 = 2.87 mi/kWh.
    assert pt["observed_mi_per_kwh"] == pytest.approx(2.87, abs=0.01)
    # Only one cycle → rolling lifetime equals the period value.
    assert pt["rolling_mi_per_kwh"] == pytest.approx(2.87, abs=0.01)
    assert pt["cost_per_mile_p"] == pytest.approx(5.0, abs=0.01)  # 500 p / 100 mi


@pytest.mark.asyncio
async def test_aggregators_user_isolation(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    from plugtrack.models import User

    async with test_sessionmaker() as s:
        other = User(username="bob", password_hash="x")
        s.add(other)
        await s.commit()
        await s.refresh(other)
        other_id = other.id
    await _mk(
        test_sessionmaker,
        user_id=other_id,
        car_id=car,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
    )
    async with test_sessionmaker() as s:
        out = await ins.spend_energy_over_time(
            s, user_id=uid, date_from=None, date_to=None, granularity="daily"
        )
    assert out == []


@pytest.mark.asyncio
async def test_mileage_view_not_enabled(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    async with test_sessionmaker() as s:
        view = await ins.mileage_allowance_view(
            s, user_id=uid, car_id=car, today=dt.date(2026, 6, 19)
        )
    assert view == {
        "enabled": False,
        "car_id": car,
        "period_start": None,
        "period_end": None,
        "opening_km": None,
        "current_km": None,
        "target_km": None,
        "used_km": None,
        "remaining_km": None,
        "days_elapsed": None,
        "days_total": None,
        "projected_year_end_km": None,
        "pace": None,
    }


@pytest.mark.asyncio
async def test_mileage_view_projection_and_pace(test_sessionmaker, seeded_user_car):
    uid, car = seeded_user_car
    from plugtrack.services import mileage_tracking

    # Tracking opens 2026-01-01 at 10000 mi with a 10000 mi/yr target.
    async with test_sessionmaker() as s:
        await mileage_tracking.set_tracking(
            s,
            user_id=uid,
            car_id=car,
            start_date=dt.date(2026, 1, 1),
            opening_miles=10000.0,
            annual_mileage_target_miles=10000.0,
            today=dt.date(2026, 1, 1),
        )
        await s.commit()
    # A session 100 days in with +2000 mi on the odometer (10000+2000 mi → km).
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car,
        when=dt.date(2026, 4, 10),
        kwh=10.0,
        cost_pence=100,
        odometer_km=12000.0 * 1.609344,
    )
    async with test_sessionmaker() as s:
        view = await ins.mileage_allowance_view(
            s, user_id=uid, car_id=car, today=dt.date(2026, 4, 10)
        )
    assert view["enabled"] is True
    assert view["days_total"] == 365
    assert view["days_elapsed"] == 100
    assert view["used_km"] == pytest.approx(2000.0 * 1.609344, abs=1.0)
    # projected = used/elapsed*total = 2000/100*365 = 7300 mi → under the 10000 target
    assert view["projected_year_end_km"] == pytest.approx((10000 + 7300) * 1.609344, abs=5.0)
    assert view["pace"] == "under"


# ---------------------------------------------------------------------------
# car_id filter tests (Task 11)
# ---------------------------------------------------------------------------


async def _seed_second_car(test_sessionmaker, user_id: int) -> int:
    """Insert a second Car for the given user; return its id."""
    from plugtrack.models import Car

    async with test_sessionmaker() as s:
        car = Car(
            user_id=user_id,
            make="Cupra",
            model="Formentor",
            battery_kwh=45.0,
            nominal_efficiency_mi_per_kwh=3.8,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        return car.id


@pytest.mark.asyncio
async def test_window_totals_car_id_filter(test_sessionmaker, seeded_user_car):
    """window_totals with car_id=car1 returns only that car's sessions."""
    uid, car1 = seeded_user_car
    car2 = await _seed_second_car(test_sessionmaker, uid)

    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car1,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car2,
        when=dt.date(2026, 6, 2),
        kwh=20.0,
        cost_pence=500,
    )

    async with test_sessionmaker() as s:
        car1_only = await ins.window_totals(s, user_id=uid, lo=None, hi=None, car_id=car1)
        both = await ins.window_totals(s, user_id=uid, lo=None, hi=None)

    assert car1_only["sessions"] == 1
    assert car1_only["kwh"] == pytest.approx(10.0)
    assert car1_only["spend_pence"] == 200

    assert both["sessions"] == 2
    assert both["kwh"] == pytest.approx(30.0)
    assert both["spend_pence"] == 700


@pytest.mark.asyncio
async def test_spend_energy_over_time_car_id_filter(test_sessionmaker, seeded_user_car):
    """spend_energy_over_time with car_id only counts that car."""
    uid, car1 = seeded_user_car
    car2 = await _seed_second_car(test_sessionmaker, uid)

    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car1,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car2,
        when=dt.date(2026, 6, 1),
        kwh=40.0,
        cost_pence=800,
    )

    async with test_sessionmaker() as s:
        car1_only = await ins.spend_energy_over_time(
            s, user_id=uid, date_from=None, date_to=None, granularity="daily", car_id=car1
        )
        both = await ins.spend_energy_over_time(
            s, user_id=uid, date_from=None, date_to=None, granularity="daily"
        )

    assert len(car1_only) == 1
    assert car1_only[0]["kwh"] == pytest.approx(10.0)
    assert car1_only[0]["sessions"] == 1

    assert len(both) == 1
    assert both[0]["kwh"] == pytest.approx(50.0)
    assert both[0]["sessions"] == 2


@pytest.mark.asyncio
async def test_home_public_split_car_id_filter(test_sessionmaker, seeded_user_car):
    """home_public_split with car_id excludes the other car's sessions."""
    uid, car1 = seeded_user_car
    car2 = await _seed_second_car(test_sessionmaker, uid)

    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car1,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
        ctype="ac",
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car2,
        when=dt.date(2026, 6, 2),
        kwh=30.0,
        cost_pence=900,
        ctype="ac",
    )

    async with test_sessionmaker() as s:
        car1_only = await ins.home_public_split(
            s, user_id=uid, date_from=None, date_to=None, car_id=car1
        )
        both = await ins.home_public_split(s, user_id=uid, date_from=None, date_to=None)

    assert car1_only["home"]["sessions"] == 1
    assert car1_only["home"]["kwh"] == pytest.approx(10.0)
    assert both["home"]["sessions"] == 2


@pytest.mark.asyncio
async def test_network_breakdown_car_id_filter(test_sessionmaker, seeded_user_car):
    """network_breakdown with car_id excludes the other car's sessions."""
    uid, car1 = seeded_user_car
    car2 = await _seed_second_car(test_sessionmaker, uid)

    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car1,
        when=dt.date(2026, 6, 1),
        kwh=10.0,
        cost_pence=200,
        ctype="dc",
        network="Osprey",
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car2,
        when=dt.date(2026, 6, 2),
        kwh=20.0,
        cost_pence=400,
        ctype="dc",
        network="Tesla",
    )

    async with test_sessionmaker() as s:
        car1_only = await ins.network_breakdown(
            s, user_id=uid, date_from=None, date_to=None, car_id=car1
        )
        both = await ins.network_breakdown(s, user_id=uid, date_from=None, date_to=None)

    assert [r["network"] for r in car1_only] == ["Osprey"]
    assert {r["network"] for r in both} == {"Osprey", "Tesla"}


@pytest.mark.asyncio
async def test_efficiency_over_time_car_id_filter(test_sessionmaker, seeded_user_car):
    """efficiency_over_time(car_id=car1) must use ONLY car1's odometer mileage,
    not a blended figure across both cars.

    Setup:
      car1: odo 1000 → 1160.9344 km  (+100 mi), 25 kWh → 4.0 mi/kWh
      car2: odo 5000 → 5482.8032 km  (+300 mi), 60 kWh  (blended would dilute car1)

    Without the fix, miles_driven_km sums both cars' deltas (400 mi total)
    and the ratio is 400/25 = 16 mi/kWh — clearly wrong for car1 alone.
    With the fix the ratio is 100/25 = 4.0 mi/kWh.
    """
    uid, car1 = seeded_user_car
    car2 = await _seed_second_car(test_sessionmaker, uid)

    KM_PER_MILE = 1.609344

    # car1: anchor reading before window, then reading inside window (+100 mi)
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car1,
        when=dt.date(2026, 5, 30),
        kwh=1.0,
        cost_pence=10,
        odometer_km=1000.0,
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car1,
        when=dt.date(2026, 6, 2),
        kwh=25.0,
        cost_pence=500,
        odometer_km=1000.0 + 100 * KM_PER_MILE,
    )

    # car2: anchor + reading inside same window (+300 mi) — should be invisible
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car2,
        when=dt.date(2026, 5, 30),
        kwh=1.0,
        cost_pence=10,
        odometer_km=5000.0,
    )
    await _mk(
        test_sessionmaker,
        user_id=uid,
        car_id=car2,
        when=dt.date(2026, 6, 2),
        kwh=60.0,
        cost_pence=1200,
        odometer_km=5000.0 + 300 * KM_PER_MILE,
    )

    async with test_sessionmaker() as s:
        out = await ins.efficiency_over_time(
            s,
            user_id=uid,
            date_from=dt.date(2026, 6, 1),
            date_to=dt.date(2026, 6, 30),
            granularity="daily",
            car_id=car1,
        )

    pt = next(p for p in out if p["period"] == "2026-06-02")
    # car1 only, cycle-based: 100 mi over 60% of 58 kWh (34.8 kWh) = 2.87 mi/kWh.
    # car2's +300 mi must NOT leak in (would blend the figure).
    assert pt["observed_mi_per_kwh"] == pytest.approx(2.87, abs=0.01), (
        f"Expected 2.87 mi/kWh (car1 only) but got {pt['observed_mi_per_kwh']!r}; "
        "drive cycles are likely not filtered by car_id"
    )
