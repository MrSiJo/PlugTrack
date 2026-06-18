# backend/tests/services/test_screenshot_commit_home.py
import datetime as dt
import pytest

from plugtrack.services.screenshot_correlation import MergedSession
from plugtrack.services.screenshot_commit import commit_merged_session


def _merged(**over):
    base = dict(
        start_at=dt.datetime(2026, 6, 15, 19, 27, tzinfo=dt.timezone.utc),
        end_at=dt.datetime(2026, 6, 16, 6, 59, tzinfo=dt.timezone.utc),
        energy_kwh=None, cost_total_pence=None, cost_per_kwh_pence=None,
        soc_start=67, soc_end=80, location_name=None, location_address=None,
        network=None, peak_kw=2.0, confidence=0.95, source_kinds=["mycupra"],
        location_short_name=None,
    )
    base.update(over)
    return MergedSession(**base)


async def _set_home_rate(test_sessionmaker, pence="19.26"):
    from sqlalchemy import select
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults
    async with test_sessionmaker() as s:
        await seed_defaults(s)
        row = (await s.execute(select(Setting).where(
            Setting.key == "default_home_rate_p_per_kwh"))).scalar_one()
        row.value = pence
        await s.commit()


@pytest.mark.asyncio
async def test_home_mycupra_only_derives_kwh_and_costs_home_rate(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car  # car battery_kwh from the fixture
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=_merged())
        await s.commit(); await s.refresh(cs)
    assert cs.charging_type == "ac"
    assert cs.kwh_added > 0          # promoted from SoC delta
    assert cs.kwh_calculated > 0
    assert cs.cost_basis == "home_rate"
    assert cs.cost_pence is not None and cs.cost_pence > 0


@pytest.mark.asyncio
async def test_commit_sets_actual_charge_seconds(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(actual_charge_seconds=13783))
        await s.commit(); await s.refresh(cs)
    assert cs.actual_charge_seconds == 13783


@pytest.mark.asyncio
async def test_home_with_granny_uses_delivered_and_matches_location(test_sessionmaker, seeded_user_car):
    from plugtrack.models import Location
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        s.add(Location(user_id=user_id, name="Home", is_free=False,
                       default_cost_per_kwh_p=19.26, centroid_lat=0.0, centroid_lng=0.0,
                       radius_m=50))
        await s.commit()
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", source_kinds=["mycupra", "granny"]))
        await s.commit(); await s.refresh(cs)
    assert cs.kwh_added == 9.3                 # delivered wins
    assert cs.kwh_calculated > 0               # SoC banked
    assert cs.location_id is not None          # matched "home"
    assert cs.cost_basis == "location_rate"
    assert cs.charging_type == "ac"


@pytest.mark.asyncio
async def test_home_caption_matches_is_home_location_by_flag(test_sessionmaker, seeded_user_car):
    # The home location is NOT named "Home" (it's geocoded to an address), but
    # carries is_home=True. A "home" caption must still link it.
    from plugtrack.models import Location
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        s.add(Location(user_id=user_id, name="5 Acacia Avenue", is_home=True, is_free=False,
                       default_cost_per_kwh_p=19.26, centroid_lat=50.7, centroid_lng=-3.5,
                       radius_m=50))
        await s.commit()
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", source_kinds=["mycupra", "granny"]))
        await s.commit(); await s.refresh(cs)
    assert cs.location_id is not None          # linked via is_home, not by name
    assert cs.cost_basis == "location_rate"


@pytest.mark.asyncio
async def test_network_charge_is_dc(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=37.9, cost_total_pence=1706, network="Tesla",
                           soc_start=None, soc_end=None, source_kinds=["tesla"]))
        await s.commit(); await s.refresh(cs)
    assert cs.charging_type == "dc"
    assert cs.cost_basis == "override_total" and cs.cost_pence == 1706


@pytest.mark.asyncio
async def test_commit_sets_odometer_miles_to_km(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", odometer=12345, odometer_unit="mi"))
        await s.commit(); await s.refresh(cs)
    assert cs.odometer_at_session_km == pytest.approx(12345 * 1.609344)


@pytest.mark.asyncio
async def test_commit_respects_explicit_km(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", odometer=20000, odometer_unit="km"))
        await s.commit(); await s.refresh(cs)
    assert cs.odometer_at_session_km == pytest.approx(20000.0)


@pytest.mark.asyncio
async def test_commit_defaults_unit_from_setting(test_sessionmaker, seeded_user_car):
    # distance_unit default is "mi" (seeded), so a bare number is treated as miles.
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        from plugtrack.settings.seeds import seed_defaults
        await seed_defaults(s); await s.commit()
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", odometer=12345, odometer_unit=None))
        await s.commit(); await s.refresh(cs)
    assert cs.odometer_at_session_km == pytest.approx(12345 * 1.609344)


@pytest.mark.asyncio
async def test_commit_no_odometer_leaves_field_unset(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id, merged=_merged())
        await s.commit(); await s.refresh(cs)
    assert cs.odometer_at_session_km is None


@pytest.mark.asyncio
async def test_commit_normalizes_unit_aliases(test_sessionmaker, seeded_user_car):
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", odometer=12345, odometer_unit="miles"))
        await s.commit(); await s.refresh(cs)
    assert cs.odometer_at_session_km == pytest.approx(12345 * 1.609344)
    async with test_sessionmaker() as s:
        cs2 = await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(start_at=__import__("datetime").datetime(2026, 6, 14, 9, 0, tzinfo=__import__("datetime").timezone.utc),
                           energy_kwh=5.0, location_name="home", odometer=20000, odometer_unit="kilometres"))
        await s.commit(); await s.refresh(cs2)
    assert cs2.odometer_at_session_km == pytest.approx(20000.0)


@pytest.mark.asyncio
async def test_commit_creates_geocoded_location(test_sessionmaker, seeded_user_car, monkeypatch):
    from sqlalchemy import func, select
    from plugtrack.models import Location
    from plugtrack.services.geocoding import GeocodeResult
    import plugtrack.services.ingest_location as il

    class FakeProvider:
        async def forward(self, query):
            return GeocodeResult(address="Lifton", provider="fake", lat=50.6437, lng=-4.2846)
        async def reverse(self, lat, lng):
            return None
    monkeypatch.setattr(il, "get_provider", lambda settings: FakeProvider())

    user_id, car_id = seeded_user_car
    merged = _merged(
        energy_kwh=37.9, cost_total_pence=1706, network="Tesla", soc_start=None, soc_end=None,
        location_name="Lifton", location_address="1 Fore Street, Lifton, PL16 0AA",
        location_short_name="Tesla Lifton", source_kinds=["tesla"])
    async with test_sessionmaker() as s:
        cs = await commit_merged_session(s, user_id=user_id, car_id=car_id, merged=merged)
        await s.commit()
        assert cs.location_id is not None
        loc = await s.get(Location, cs.location_id)
        assert loc.name == "Tesla Lifton"
        assert (await s.execute(select(func.count(Location.id)))).scalar_one() == 1


@pytest.mark.asyncio
async def test_preview_does_not_geocode_or_create(test_sessionmaker, seeded_user_car, monkeypatch):
    from sqlalchemy import func, select
    from plugtrack.models import Location
    import plugtrack.services.ingest_location as il
    from plugtrack.services.screenshot_commit import preview_merged_session

    def _boom(settings):
        raise AssertionError("preview must not build a geocoder")
    monkeypatch.setattr(il, "get_provider", _boom)

    user_id, car_id = seeded_user_car
    merged = _merged(
        energy_kwh=37.9, cost_total_pence=1706, network="Tesla", soc_start=None, soc_end=None,
        location_name="Lifton", location_address="1 Fore Street, Lifton",
        location_short_name="Tesla Lifton", source_kinds=["tesla"])
    async with test_sessionmaker() as s:
        cs = await preview_merged_session(s, user_id=user_id, car_id=car_id, merged=merged)
        assert cs.location_id is None
        assert (await s.execute(select(func.count(Location.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_committed_odometer_drives_current_mileage(test_sessionmaker, seeded_user_car):
    import datetime as dt
    from plugtrack.services import mileage_tracking as mt
    user_id, car_id = seeded_user_car
    await _set_home_rate(test_sessionmaker)
    start = dt.date(2026, 1, 1)
    async with test_sessionmaker() as s:
        await mt.set_tracking(s, user_id=user_id, car_id=car_id, start_date=start,
                              opening_miles=10000, annual_mileage_target_miles=None,
                              today=dt.date(2026, 6, 17))
        await s.commit()
    # Commit a charge carrying a 12,345 mi odometer.
    async with test_sessionmaker() as s:
        await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(energy_kwh=9.3, location_name="home", odometer=12345, odometer_unit="mi"))
        await s.commit()
    async with test_sessionmaker() as s:
        status = await mt.get_status(s, user_id=user_id, car_id=car_id, today=dt.date(2026, 6, 17))
    assert status.current_period is not None
    assert status.current_period.current_odometer_km == pytest.approx(12345 * 1.609344)
    # A later, lower reading must NOT regress current mileage (max() protects it).
    async with test_sessionmaker() as s:
        await commit_merged_session(
            s, user_id=user_id, car_id=car_id,
            merged=_merged(start_at=dt.datetime(2026, 6, 16, 9, 0, tzinfo=dt.timezone.utc),
                           energy_kwh=5.0, location_name="home", odometer=11000, odometer_unit="mi"))
        await s.commit()
    async with test_sessionmaker() as s:
        status2 = await mt.get_status(s, user_id=user_id, car_id=car_id, today=dt.date(2026, 6, 17))
    assert status2.current_period.current_odometer_km == pytest.approx(12345 * 1.609344)
