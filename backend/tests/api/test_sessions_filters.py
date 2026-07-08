"""GET /api/sessions filter param tests."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from plugtrack.models import Car, ChargingSession, Location


async def _set_petrol_settings(s, *, p_per_litre: str, mpg: str) -> None:
    """Upsert the petrol settings. The `authed_client` fixture boots the app
    through its lifespan, which already seeds these keys via `seed_defaults`,
    so we must UPDATE the existing rows (a plain INSERT trips the PK)."""
    from plugtrack.models import Setting
    from sqlalchemy import select

    for key, value in (
        ("petrol_price_p_per_litre", p_per_litre),
        ("petrol_mpg", mpg),
    ):
        row = (await s.execute(select(Setting).where(Setting.key == key))).scalar_one_or_none()
        if row is None:
            s.add(
                Setting(
                    key=key,
                    value=value,
                    value_type="float",
                    group_name="cost",
                    label="x",
                    description=None,
                    default_value=value,
                )
            )
        else:
            row.value = value


async def _bootstrap(authed_client, test_sessionmaker):
    """Seed two cars and a varied set of sessions for the active user.

    Returns: (user_id, car_a_id, car_b_id, location_id, today)
    """
    from plugtrack.models import User
    from sqlalchemy import select

    today = date.today()

    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
        car_a = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        car_b = Car(
            user_id=user.id,
            make="VW",
            model="ID.4",
            battery_kwh=77.0,
            nominal_efficiency_mi_per_kwh=3.8,
            provider="manual",
            active=True,
        )
        loc = Location(
            user_id=user.id,
            name="Home",
            centroid_lat=51.5,
            centroid_lng=-0.1,
            visit_count=0,
        )
        s.add_all([car_a, car_b, loc])
        await s.commit()
        await s.refresh(car_a)
        await s.refresh(car_b)
        await s.refresh(loc)

        rows = [
            (today, car_a.id, "manual", loc.id),
            (today - timedelta(days=10), car_a.id, "synthesis", None),
            (today - timedelta(days=40), car_a.id, "cariad", loc.id),
            (today - timedelta(days=2), car_b.id, "manual", None),
        ]
        for d, cid, src, lid in rows:
            s.add(
                ChargingSession(
                    user_id=user.id,
                    car_id=cid,
                    date=d,
                    start_soc=20,
                    end_soc=80,
                    kwh_added=10.0,
                    cost_pence=100,
                    cost_basis="home_rate",
                    location_id=lid,
                    source=src,
                ),
            )
        await s.commit()

        return user.id, car_a.id, car_b.id, loc.id, today


@pytest.mark.asyncio
async def test_list_no_filters_returns_all(authed_client, test_sessionmaker):
    await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get("/api/sessions")
    assert r.status_code == 200
    assert len(r.json()) == 4


@pytest.mark.asyncio
async def test_filter_by_car_id(authed_client, test_sessionmaker):
    _, car_a, car_b, _, _ = await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?car_id={car_a}")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3
    assert all(row["car_id"] == car_a for row in rows)


@pytest.mark.asyncio
async def test_filter_by_source(authed_client, test_sessionmaker):
    await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get("/api/sessions?source=manual")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert {row["source"] for row in rows} == {"manual"}


@pytest.mark.asyncio
async def test_filter_by_invalid_source_400(authed_client):
    r = await authed_client.get("/api/sessions?source=bogus")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_filter_by_telegram_and_import_accepted(authed_client, test_sessionmaker):
    # Regression: telegram + import are real sources (the standalone pivot), but
    # the filter allow-list was stale, 400-ing the Sessions page when you
    # clicked the "Telegram" or "Import" source tab.
    await _bootstrap(authed_client, test_sessionmaker)
    for src in ("telegram", "import"):
        r = await authed_client.get(f"/api/sessions?source={src}")
        assert r.status_code == 200, (src, r.text)


@pytest.mark.asyncio
async def test_filter_by_date_range(authed_client, test_sessionmaker):
    _, _, _, _, today = await _bootstrap(authed_client, test_sessionmaker)
    df = (today - timedelta(days=15)).isoformat()
    dt = today.isoformat()
    r = await authed_client.get(
        f"/api/sessions?date_from={df}&date_to={dt}",
    )
    assert r.status_code == 200
    # Excludes the 40-day-old session.
    assert len(r.json()) == 3


@pytest.mark.asyncio
async def test_filter_by_location_id(authed_client, test_sessionmaker):
    _, _, _, loc_id, _ = await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?location_id={loc_id}")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert all(row["location_id"] == loc_id for row in rows)


@pytest.mark.asyncio
async def test_combined_filters(authed_client, test_sessionmaker):
    _, car_a, _, _, today = await _bootstrap(authed_client, test_sessionmaker)
    r = await authed_client.get(
        f"/api/sessions?car_id={car_a}&source=synthesis"
        f"&date_from={(today - timedelta(days=20)).isoformat()}"
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["source"] == "synthesis"


# ---------------------------------------------------------------------------
# Sort params (sort ∈ {date, cost, energy, saved}; dir ∈ {asc, desc}).
# ---------------------------------------------------------------------------


async def _bootstrap_sortable(authed_client, test_sessionmaker):
    """Seed one car with rows carrying distinct date / cost / energy values so
    each sort axis produces an unambiguous order.

    Returns (car_id, today, [session_ids in seeded order]).
    """
    from plugtrack.models import User
    from sqlalchemy import select

    today = date.today()
    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)

        # (days_ago, kwh_added, cost_pence)
        specs = [
            (0, 10.0, 300),  # newest date, mid energy, high cost
            (5, 30.0, 100),  # mid date, high energy, low cost
            (10, 20.0, 200),  # oldest date, low energy, mid cost
        ]
        ids = []
        for days_ago, kwh, cost in specs:
            cs = ChargingSession(
                user_id=user.id,
                car_id=car.id,
                date=today - timedelta(days=days_ago),
                start_soc=20,
                end_soc=80,
                kwh_added=kwh,
                cost_pence=cost,
                cost_basis="home_rate",
                source="manual",
            )
            s.add(cs)
            await s.commit()
            await s.refresh(cs)
            ids.append(cs.id)
        return car.id, today, ids


@pytest.mark.asyncio
async def test_sort_default_is_date_desc(authed_client, test_sessionmaker):
    car_id, today, _ = await _bootstrap_sortable(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?car_id={car_id}")
    assert r.status_code == 200
    dates = [row["date"] for row in r.json()]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == today.isoformat()


@pytest.mark.asyncio
async def test_sort_date_asc(authed_client, test_sessionmaker):
    car_id, _, _ = await _bootstrap_sortable(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?car_id={car_id}&sort=date&dir=asc")
    assert r.status_code == 200
    dates = [row["date"] for row in r.json()]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_sort_cost_desc_and_asc(authed_client, test_sessionmaker):
    car_id, _, _ = await _bootstrap_sortable(authed_client, test_sessionmaker)

    r = await authed_client.get(f"/api/sessions?car_id={car_id}&sort=cost&dir=desc")
    assert r.status_code == 200
    costs = [row["cost_pence"] for row in r.json()]
    assert costs == [300, 200, 100]

    r = await authed_client.get(f"/api/sessions?car_id={car_id}&sort=cost&dir=asc")
    assert r.status_code == 200
    costs = [row["cost_pence"] for row in r.json()]
    assert costs == [100, 200, 300]


@pytest.mark.asyncio
async def test_sort_energy_desc_and_asc(authed_client, test_sessionmaker):
    car_id, _, _ = await _bootstrap_sortable(authed_client, test_sessionmaker)

    r = await authed_client.get(f"/api/sessions?car_id={car_id}&sort=energy&dir=desc")
    assert r.status_code == 200
    energies = [row["kwh_added"] for row in r.json()]
    assert energies == [30.0, 20.0, 10.0]

    r = await authed_client.get(f"/api/sessions?car_id={car_id}&sort=energy&dir=asc")
    assert r.status_code == 200
    energies = [row["kwh_added"] for row in r.json()]
    assert energies == [10.0, 20.0, 30.0]


async def _bootstrap_saved(authed_client, test_sessionmaker):
    """Seed one car with petrol settings + a measured anchor (has a saved
    value) and two rows whose saved is None (zero-energy → no comparison).

    Returns (car_id, anchor_id).
    """
    from plugtrack.models import User
    from sqlalchemy import select

    today = date.today()
    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
        await _set_petrol_settings(s, p_per_litre="150.0", mpg="50.0")
        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=58.0,
            nominal_efficiency_mi_per_kwh=4.2,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)

        # Prior-with-odometer + measured anchor → anchor gets a saved value.
        prior = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=today - timedelta(days=8),
            start_soc=40,
            end_soc=80,
            kwh_added=10.0,
            odometer_at_session_km=1000.0,
            cost_pence=200,
            cost_basis="home_rate",
            source="manual",
        )
        anchor = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=today - timedelta(days=6),
            start_soc=40,
            end_soc=80,
            kwh_added=10.0,
            odometer_at_session_km=1100.0,
            cost_pence=500,
            cost_basis="home_rate",
            source="manual",
        )
        # Two zero-energy rows → no comparison → saved None.
        none_a = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=today - timedelta(days=2),
            start_soc=80,
            end_soc=80,
            kwh_added=0.0,
            kwh_calculated=0.0,
            cost_pence=100,
            cost_basis="home_rate",
            source="manual",
        )
        none_b = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=today,
            start_soc=80,
            end_soc=80,
            kwh_added=0.0,
            kwh_calculated=0.0,
            cost_pence=150,
            cost_basis="home_rate",
            source="manual",
        )
        s.add_all([prior, anchor, none_a, none_b])
        await s.commit()
        await s.refresh(anchor)
        return car.id, anchor.id


@pytest.mark.asyncio
async def test_sort_saved_puts_none_last_desc(authed_client, test_sessionmaker):
    car_id, anchor_id = await _bootstrap_saved(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?car_id={car_id}&sort=saved&dir=desc")
    assert r.status_code == 200
    rows = r.json()
    saved = [row["saved_vs_petrol_p"] for row in rows]
    # Non-None values come first; None sorts last in both directions.
    non_none = [v for v in saved if v is not None]
    assert non_none, "expected at least one row with a saved value"
    assert saved[: len(non_none)] == non_none
    assert all(v is None for v in saved[len(non_none) :])
    # Descending order among the present values.
    assert non_none == sorted(non_none, reverse=True)
    # The measured anchor carries a value and so sorts ahead of the
    # zero-energy (None) rows.
    valued_ids = {row["id"] for row in rows if row["saved_vs_petrol_p"] is not None}
    assert anchor_id in valued_ids


@pytest.mark.asyncio
async def test_sort_saved_puts_none_last_asc(authed_client, test_sessionmaker):
    car_id, _ = await _bootstrap_saved(authed_client, test_sessionmaker)
    r = await authed_client.get(f"/api/sessions?car_id={car_id}&sort=saved&dir=asc")
    assert r.status_code == 200
    saved = [row["saved_vs_petrol_p"] for row in r.json()]
    non_none = [v for v in saved if v is not None]
    assert saved[: len(non_none)] == non_none
    assert all(v is None for v in saved[len(non_none) :])
    # Ascending order among the present values.
    assert non_none == sorted(non_none)


@pytest.mark.asyncio
async def test_sort_invalid_sort_400(authed_client):
    r = await authed_client.get("/api/sessions?sort=bogus")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_sort_invalid_dir_400(authed_client):
    r = await authed_client.get("/api/sessions?dir=sideways")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_filter_then_compute_uses_full_history_for_efficiency(
    authed_client, test_sessionmaker
):
    """A date filter narrows the returned rows, but observed efficiency still
    reflects the car's FULL history — a filtered-out earlier leg drives the
    efficiency used for an in-range estimated row.

    Construct three measured legs (implying observed 3.0 mi/kWh) all OLDER
    than the filter window, plus one estimated row INSIDE the window. The
    estimated row's savings must match what it would be with observed=3.0,
    not the nominal (5.0).
    """
    from plugtrack.models import User
    from sqlalchemy import select

    today = date.today()
    async with test_sessionmaker() as s:
        user = (await s.execute(select(User))).scalar_one()
        await _set_petrol_settings(s, p_per_litre="151.9", mpg="54.1")
        # Nominal 5.0 deliberately far from observed 3.0.
        car = Car(
            user_id=user.id,
            make="Cupra",
            model="Born",
            battery_kwh=50.0,
            nominal_efficiency_mi_per_kwh=5.0,
            provider="manual",
            active=True,
        )
        s.add(car)
        await s.commit()
        await s.refresh(car)
        car_id = car.id

        # Three measured legs WAY in the past (outside the filter window).
        for i, days_ago in enumerate((90, 86, 82)):
            s.add(
                ChargingSession(
                    user_id=user.id,
                    car_id=car.id,
                    date=today - timedelta(days=days_ago),
                    start_soc=30,
                    end_soc=80,
                    kwh_added=25.0,
                    odometer_at_session_km=1000.0 + i * 120.7008,
                    cost_basis="home_rate",
                    source="manual",
                )
            )
        # Estimated row INSIDE the window (no odometer).
        in_range = ChargingSession(
            user_id=user.id,
            car_id=car.id,
            date=today - timedelta(days=3),
            start_soc=60,
            end_soc=90,
            kwh_added=18.0,
            kwh_calculated=15.0,
            cost_pence=300,
            cost_basis="home_rate",
            source="manual",
        )
        s.add(in_range)
        await s.commit()
        await s.refresh(in_range)
        in_range_id = in_range.id

    df = (today - timedelta(days=30)).isoformat()
    r = await authed_client.get(
        f"/api/sessions?car_id={car_id}&date_from={df}&date_to={today.isoformat()}"
    )
    assert r.status_code == 200
    rows = r.json()
    # The filter excluded the three old measured legs.
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == in_range_id
    assert row["comparison_basis"] == "estimated"

    # Expected savings using the OBSERVED efficiency (3.0), not nominal (5.0).
    KM_PER_MILE = 1.609344
    LITRES_PER_GALLON = 4.54609
    ppm = (151.9 * LITRES_PER_GALLON) / 54.1
    est_miles_observed = 15.0 * 3.0
    expected_saved = round(est_miles_observed * ppm) - 300
    nominal_saved = round(15.0 * 5.0 * ppm) - 300
    assert row["saved_vs_petrol_p"] == expected_saved
    assert row["saved_vs_petrol_p"] != nominal_saved
