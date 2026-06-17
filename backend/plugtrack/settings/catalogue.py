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
    CatalogueEntry(
        key="public_base_url",
        value_type="string",
        group_name="display",
        label="Public base URL",
        description=(
            "Externally reachable base URL of the PlugTrack UI, e.g. "
            "http://host:9279. Used to deep-link imported sessions from "
            "Telegram. Leave blank to omit the link."
        ),
        default_value=None,
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
    # Home charge planner
    CatalogueEntry(
        key="home_charge_window_start",
        value_type="string",
        group_name="charging",
        label="Home charge window start (HH:MM)",
        description=(
            "Start time of the nightly home-charge window in 24-hour HH:MM "
            "format. The window is assumed to cross midnight so the start time "
            "is always later in the day than the end time (e.g. 23:45 → 07:15)."
        ),
        default_value="23:45",
    ),
    CatalogueEntry(
        key="home_charge_window_end",
        value_type="string",
        group_name="charging",
        label="Home charge window end (HH:MM)",
        description=(
            "End time of the nightly home-charge window in 24-hour HH:MM "
            "format. Must be earlier in the day than window_start because the "
            "window crosses midnight (e.g. 23:45 → 07:15 is 450 minutes)."
        ),
        default_value="07:15",
    ),
    CatalogueEntry(
        key="home_charge_fallback_kw",
        value_type="float",
        group_name="charging",
        label="Home charge fallback power (kW)",
        description=(
            "Assumed AC charging power (kW) used by the home charge planner "
            "when fewer than 3 recent home AC sessions are available to "
            "derive a reliable median. Typical 7.4 kW for a 32A Type-2 "
            "wallbox."
        ),
        default_value="7.4",
    ),
    # Standalone mode — gate the (now-blocked) pycupra sync stack off.
    CatalogueEntry(
        key="pycupra_enabled",
        value_type="bool",
        group_name="sync",
        label="pycupra integration enabled",
        description=(
            "Master switch for the Cupra Connect sync stack. Disabled by "
            "default: VAG blocked the third-party API (App Check) on 2026-06-08. "
            "Leave off; PlugTrack is fed by Telegram screenshot imports instead."
        ),
        default_value="false",
    ),
    # Telegram screenshot ingestion
    CatalogueEntry(
        key="telegram_bot_enabled",
        value_type="bool",
        group_name="telegram",
        label="Telegram bot enabled",
        description="Run the always-on Telegram bot that ingests charge screenshots.",
        default_value="false",
    ),
    CatalogueEntry(
        key="telegram_bot_token",
        value_type="string",
        group_name="telegram",
        label="Telegram bot token",
        description="BotFather HTTP API token. Stored encrypted.",
        default_value=None,
        is_secret=True,
    ),
    CatalogueEntry(
        key="telegram_allowed_user_ids",
        value_type="string",
        group_name="telegram",
        label="Allowed Telegram user IDs",
        description="Comma-separated numeric Telegram user IDs permitted to feed the bot.",
        default_value=None,
    ),
    CatalogueEntry(
        key="telegram_default_car_id",
        value_type="int",
        group_name="telegram",
        label="Default car for imports",
        description="Car ID that imported charging sessions are attached to.",
        default_value=None,
    ),
    # OpenAI vision extraction
    CatalogueEntry(
        key="openai_api_key",
        value_type="string",
        group_name="openai",
        label="OpenAI API key",
        description="Used for vision extraction of charge screenshots. Stored encrypted.",
        default_value=None,
        is_secret=True,
    ),
    CatalogueEntry(
        key="openai_model",
        value_type="string",
        group_name="openai",
        label="OpenAI vision model",
        description="Vision-capable model for screenshot extraction.",
        default_value="gpt-5.5",
    ),
    CatalogueEntry(
        key="openai_input_price_per_1k_pence",
        value_type="float",
        group_name="openai",
        label="OpenAI input price (pence / 1k tokens)",
        description="Optional. Used to show £ cost per extraction. Leave blank to show tokens only.",
        default_value=None,
    ),
    CatalogueEntry(
        key="openai_output_price_per_1k_pence",
        value_type="float",
        group_name="openai",
        label="OpenAI output price (pence / 1k tokens)",
        description="Optional. Output tokens include reasoning tokens (≈0 here). Leave blank to show tokens only.",
        default_value=None,
    ),
)
