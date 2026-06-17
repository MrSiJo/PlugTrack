import pytest
from sqlalchemy import func, select

from plugtrack.models import Location
from plugtrack.services.geocoding import GeocodeResult
from plugtrack.services.ingest_location import (
    compose_location_name, resolve_ingested_location,
)


class FakeProvider:
    def __init__(self, result):
        self.result = result
        self.queries = []
    async def forward(self, query):
        self.queries.append(query)
        return self.result
    async def reverse(self, lat, lng):
        return None


class MapProvider:
    """Geocoder fake that maps specific query strings to results (else None)."""
    def __init__(self, mapping):
        self.mapping = mapping
        self.queries = []
    async def forward(self, query):
        self.queries.append(query)
        return self.mapping.get(query)
    async def reverse(self, lat, lng):
        return None


def test_compose_name_normalises_network_and_place():
    assert compose_location_name("Tesla Supercharging", "Camborne, UK") == "Tesla Camborne"
    assert compose_location_name("Supercharging", "Lifton") == "Tesla Lifton"
    assert compose_location_name("RAW Charging", "RAW NT TRENGWAINTON 2") == "RAW Trengwainton"
    assert compose_location_name(None, "Lands End") == "Lands End"


def test_extract_uk_postcode():
    from plugtrack.services.ingest_location import _extract_uk_postcode
    assert _extract_uk_postcode("1 Fore Street, Lifton, United Kingdom, PL16 0AA") == "PL16 0AA"
    assert _extract_uk_postcode("Trevenson Lane, Redruth, TR15 3GF") == "TR15 3GF"
    assert _extract_uk_postcode("no postcode here") is None
    assert _extract_uk_postcode(None) is None


@pytest.mark.asyncio
async def test_resolve_falls_back_to_postcode_when_address_misses(test_sessionmaker, seeded_user_car):
    # Full address with embedded ", United Kingdom," misses Nominatim, but the
    # postcode hits — and should still resolve a Location.
    user_id, _ = seeded_user_car
    prov = MapProvider({"PL16 0AA": GeocodeResult(address="Lifton", provider="fake",
                                                  lat=50.6434, lng=-4.2841)})
    async with test_sessionmaker() as s:
        loc_id = await resolve_ingested_location(
            s, user_id=user_id, place_name="Tesla Lifton", raw_label="Lifton",
            address="1 Fore Street, Lifton, United Kingdom, PL16 0AA", network="Tesla",
            provider=prov)
        await s.commit()
        assert loc_id is not None
        loc = await s.get(Location, loc_id)
        assert loc.name == "Tesla Lifton"
    # tried the full address first (miss), then fell back to the postcode (hit)
    assert prov.queries[0] == "1 Fore Street, Lifton, United Kingdom, PL16 0AA"
    assert "PL16 0AA" in prov.queries


@pytest.mark.asyncio
async def test_resolve_creates_named_location(test_sessionmaker, seeded_user_car):
    user_id, _ = seeded_user_car
    prov = FakeProvider(GeocodeResult(address="Lifton", provider="fake", lat=50.6437, lng=-4.2846))
    async with test_sessionmaker() as s:
        loc_id = await resolve_ingested_location(
            s, user_id=user_id, place_name="Tesla Lifton", raw_label="Lifton",
            address="1 Fore Street, Lifton, PL16 0AA", network="Tesla", provider=prov)
        await s.commit()
        loc = await s.get(Location, loc_id)
        assert loc.name == "Tesla Lifton"
        assert loc.default_charge_network == "Tesla"
        assert loc.address == "1 Fore Street, Lifton, PL16 0AA"
        assert loc.visit_count == 1
    assert prov.queries == ["1 Fore Street, Lifton, PL16 0AA"]   # address used, not the clean name


@pytest.mark.asyncio
async def test_resolve_matches_existing_within_radius_and_fills_only_empty(test_sessionmaker, seeded_user_car):
    user_id, _ = seeded_user_car
    async with test_sessionmaker() as s:
        s.add(Location(user_id=user_id, name="Tesla Lifton", centroid_lat=50.6437,
                       centroid_lng=-4.2846, radius_m=100, default_charge_network=None))
        await s.commit()
    # geocode lands ~30 m away -> matches the existing one
    prov = FakeProvider(GeocodeResult(address="x", provider="fake", lat=50.64388, lng=-4.2846))
    async with test_sessionmaker() as s:
        loc_id = await resolve_ingested_location(
            s, user_id=user_id, place_name="SHOULD NOT OVERWRITE", raw_label="Lifton",
            address="Lifton", network="Tesla", provider=prov)
        await s.commit()
        loc = await s.get(Location, loc_id)
        assert loc.name == "Tesla Lifton"                 # existing name preserved (not overwritten)
        assert loc.default_charge_network == "Tesla"      # was empty -> filled
        count = (await s.execute(select(func.count(Location.id)))).scalar_one()
        assert count == 1                                 # matched, not created


@pytest.mark.asyncio
async def test_resolve_geocode_none_returns_none(test_sessionmaker, seeded_user_car):
    user_id, _ = seeded_user_car
    prov = FakeProvider(None)
    async with test_sessionmaker() as s:
        loc_id = await resolve_ingested_location(
            s, user_id=user_id, place_name="X", raw_label="X", address="X", network="Y", provider=prov)
        assert loc_id is None
        count = (await s.execute(select(func.count(Location.id)))).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_backfill_links_unlinked_import_sessions(test_sessionmaker, seeded_user_car):
    import datetime as dt
    from plugtrack.models import ChargingSession, Location
    from sqlalchemy import func, select
    from plugtrack.services.ingest_location import backfill_import_session_locations

    user_id, car_id = seeded_user_car
    async with test_sessionmaker() as s:
        s.add(ChargingSession(
            user_id=user_id, car_id=car_id, date=dt.date(2026, 6, 13), start_soc=20, end_soc=80,
            kwh_added=37.9, charging_type="dc", charging_mode="manual", cost_pence=1706,
            cost_basis="override_total", charge_network="Tesla", user_label="Lifton",
            notes="1 Fore Street, Lifton, PL16 0AA", source="import"))
        await s.commit()

    prov = FakeProvider(GeocodeResult(address="Lifton", provider="fake", lat=50.6437, lng=-4.2846))

    async with test_sessionmaker() as s:
        n = await backfill_import_session_locations(s, user_id=user_id, provider=prov)
        await s.commit()
    assert n == 1
    async with test_sessionmaker() as s:
        cs = (await s.execute(select(ChargingSession).where(ChargingSession.user_id == user_id))).scalars().first()
        assert cs.location_id is not None
        assert (await s.execute(select(func.count(Location.id)))).scalar_one() == 1
        # idempotent: a second run links nothing more
        n2 = await backfill_import_session_locations(s, user_id=user_id, provider=prov)
        assert n2 == 0
