"""Source of truth for every settings key in PlugTrack.

Each entry defines key, value_type, group_name, label, description,
default value, and `is_secret` flag. `seed_defaults` reads this list on
every startup and inserts any rows missing from the `setting` table.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CatalogueEntry:
    key: str
    value_type: str  # 'string' | 'int' | 'float' | 'bool' | 'enum'
    group_name: str
    label: str
    description: str
    default_value: Optional[str]
    is_secret: bool = False


CATALOGUE: tuple[CatalogueEntry, ...] = (
    # Cupra Connect
    CatalogueEntry(
        key="cupra_username",
        value_type="string",
        group_name="cupra_connect",
        label="Cupra Connect username",
        description="Email address used to sign in to the My Cupra app.",
        default_value=None,
        is_secret=True,
    ),
    CatalogueEntry(
        key="cupra_password",
        value_type="string",
        group_name="cupra_connect",
        label="Cupra Connect password",
        description="Password for the My Cupra account.",
        default_value=None,
        is_secret=True,
    ),
    CatalogueEntry(
        key="cupra_spin",
        value_type="string",
        group_name="cupra_connect",
        label="S-PIN (optional)",
        description="Security PIN required for some Cupra Connect protected actions.",
        default_value=None,
        is_secret=True,
    ),
    CatalogueEntry(
        key="vehicle_provider",
        value_type="enum",
        group_name="cupra_connect",
        label="Vehicle data provider",
        description="Which integration to use for live vehicle data. Only Cupra Connect is supported in v1.",
        default_value="cupra_connect",
    ),
    # Sync — adaptive cadence per state (see spec §3.6)
    CatalogueEntry(
        key="sync_interval_minutes_idle",
        value_type="int",
        group_name="sync",
        label="Sync interval — idle (minutes)",
        description="Cadence when no plug-in detected. Default 30.",
        default_value="30",
    ),
    CatalogueEntry(
        key="sync_interval_minutes_plugged",
        value_type="int",
        group_name="sync",
        label="Sync interval — plugged-in (minutes)",
        description="Cadence when cable is connected but charging is not active. Default 10.",
        default_value="10",
    ),
    CatalogueEntry(
        key="sync_interval_minutes_charging",
        value_type="int",
        group_name="sync",
        label="Sync interval — charging (minutes)",
        description="Ceiling cadence while actively charging. Actual interval may be tightened using cloud-supplied charging_time_left. Default 5.",
        default_value="5",
    ),
    CatalogueEntry(
        key="sync_enabled",
        value_type="bool",
        group_name="sync",
        label="Background sync enabled",
        description="Turn the scheduled background sync on or off.",
        default_value="true",
    ),
    CatalogueEntry(
        key="sync_daily_request_budget",
        value_type="int",
        group_name="sync",
        label="Daily API request budget",
        description=(
            "Maximum number of adapter getter calls PlugTrack may make per day. "
            "Cupra's account-wide quota is ~1,500/day shared with the phone app; "
            "the default 800 leaves ~700 headroom for the app."
        ),
        default_value="800",
    ),
    CatalogueEntry(
        key="sync_quota_soft_fraction",
        value_type="float",
        group_name="sync",
        label="Quota stretch threshold (fraction)",
        description=(
            "Fraction of the daily budget at which polling intervals start to "
            "stretch. E.g. 0.75 means stretching begins when 75% of the budget "
            "is used; at 100% polling pauses until the next day."
        ),
        default_value="0.75",
    ),
    # Cost defaults
    CatalogueEntry(
        key="default_home_rate_p_per_kwh",
        value_type="float",
        group_name="cost",
        label="Home charging rate (p/kWh)",
        description="Default cost per kWh applied when entering a home charging session.",
        default_value="7.5",
    ),
    CatalogueEntry(
        key="petrol_price_p_per_litre",
        value_type="float",
        group_name="cost",
        label="Petrol price (p/litre)",
        description="Used for petrol-vs-EV cost comparison.",
        default_value="148.9",
    ),
    CatalogueEntry(
        key="petrol_mpg",
        value_type="float",
        group_name="cost",
        label="Petrol MPG",
        description="Comparable petrol vehicle's miles per gallon.",
        default_value="50.0",
    ),
    # Display
    CatalogueEntry(
        key="theme",
        value_type="enum",
        group_name="display",
        label="Theme",
        description="UI theme: light, dark, or system preference.",
        default_value="system",
    ),
    CatalogueEntry(
        key="currency",
        value_type="string",
        group_name="display",
        label="Currency",
        description="ISO currency code (e.g. GBP, EUR, USD).",
        default_value="GBP",
    ),
    CatalogueEntry(
        key="distance_unit",
        value_type="enum",
        group_name="display",
        label="Distance unit",
        description="Display unit for distances. Stored as km internally; converted at render. Default 'mi'.",
        default_value="mi",
    ),
    # Locations / geocoding — wired in Phase 5 but seeded in Phase 1
    # so the catalogue is stable from first deploy.
    CatalogueEntry(
        key="geocoding_enabled",
        value_type="bool",
        group_name="locations",
        label="Reverse-geocode locations",
        description="When enabled, charging locations are matched to a human-readable address via a third-party service. Disable for full privacy.",
        default_value="true",
    ),
    CatalogueEntry(
        key="geocoding_provider",
        value_type="enum",
        group_name="locations",
        label="Geocoding provider",
        description="Service used to look up addresses. 'nominatim' is free and no key needed; 'mapbox' / 'opencage' need geocoding_api_key.",
        default_value="nominatim",
    ),
    CatalogueEntry(
        key="geocoding_api_key",
        value_type="string",
        group_name="locations",
        label="Geocoding API key (optional)",
        description="Required for mapbox or opencage providers. Leave blank for nominatim.",
        default_value=None,
        is_secret=True,
    ),
    CatalogueEntry(
        key="location_cluster_radius_m",
        value_type="int",
        group_name="locations",
        label="Location cluster radius (metres)",
        description="GPS coords within this radius of an existing location are treated as the same place.",
        default_value="100",
    ),
    # Unconfirmed (SoC-delta) charge detection — tiered, odometer-corroborated
    CatalogueEntry(
        key="unconfirmed_soc_delta_threshold",
        value_type="int",
        group_name="detection",
        label="SoC delta threshold (percentage points)",
        description=(
            "Minimum SoC rise between two consecutive IDLE polls needed to "
            "consider the gap a charge. Rises below this are treated as regen "
            "/ measurement noise / preconditioning. Default 5."
        ),
        default_value="5",
    ),
    CatalogueEntry(
        key="unconfirmed_regen_ceiling",
        value_type="int",
        group_name="detection",
        label="Regen ceiling (percentage points)",
        description=(
            "SoC rises at or above this threshold are always treated as a "
            "charge, even if the odometer moved (regen cannot add this many "
            "percentage points). Rises below this band require the car to have "
            "been stationary. Default 15."
        ),
        default_value="15",
    ),
    CatalogueEntry(
        key="unconfirmed_stationary_tolerance_km",
        value_type="int",
        group_name="detection",
        label="Stationary tolerance (km)",
        description=(
            "Maximum odometer movement between two IDLE polls that still "
            "counts as 'stationary'. Rises in the delta-threshold–regen-ceiling "
            "band where the car moved more than this are suppressed (ambiguous "
            "regen vs charge). Default 1."
        ),
        default_value="1",
    ),
)
