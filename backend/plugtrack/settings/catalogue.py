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
    CatalogueEntry(
        key="charge_loss_factor",
        value_type="float",
        group_name="charging",
        label="Charging loss factor",
        description=(
            "Fraction of grid energy that reaches the battery (e.g. 0.90 = 10% loss). "
            "Planner inflates charge time accordingly."
        ),
        default_value="0.90",
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
        key="digest_weekly_enabled",
        value_type="bool",
        group_name="telegram",
        label="Weekly digest",
        description="Send a weekly charging recap on Mondays.",
        default_value="false",
    ),
    CatalogueEntry(
        key="digest_monthly_enabled",
        value_type="bool",
        group_name="telegram",
        label="Monthly digest",
        description="Send a monthly charging review on the 1st.",
        default_value="false",
    ),
    CatalogueEntry(
        key="digest_send_hour",
        value_type="int",
        group_name="telegram",
        label="Digest send hour",
        description="Hour of day (0-23, app-local time) to send digests.",
        default_value="8",
    ),
    CatalogueEntry(
        key="digest_last_weekly_sent",
        value_type="string",
        group_name="telegram",
        label="(internal) last weekly digest",
        description="Internal marker — last ISO week a weekly digest was processed.",
        default_value=None,
    ),
    CatalogueEntry(
        key="digest_last_monthly_sent",
        value_type="string",
        group_name="telegram",
        label="(internal) last monthly digest",
        description="Internal marker — last month a monthly digest was processed.",
        default_value=None,
    ),
    # AI — master switch + provider, plus OpenAI-specific keys (grouped under "ai")
    CatalogueEntry(
        key="ai_enabled",
        value_type="bool",
        group_name="ai",
        label="AI features enabled",
        description="Master switch for AI features (screenshot extraction, conversational bot).",
        default_value="false",
    ),
    CatalogueEntry(
        key="ai_provider",
        value_type="enum",
        group_name="ai",
        label="AI provider",
        description="Which AI provider to use. Only OpenAI is implemented in v1.",
        default_value="openai",
    ),
    CatalogueEntry(
        key="openai_api_key",
        value_type="string",
        group_name="ai",
        label="OpenAI API key",
        description="Used for vision extraction of charge screenshots. Stored encrypted.",
        default_value=None,
        is_secret=True,
    ),
    CatalogueEntry(
        key="openai_model",
        value_type="string",
        group_name="ai",
        label="OpenAI vision model",
        description="Vision-capable model for screenshot extraction.",
        default_value="gpt-5.5",
    ),
    CatalogueEntry(
        key="openai_input_price_per_1k_pence",
        value_type="float",
        group_name="ai",
        label="OpenAI input price (pence / 1k tokens)",
        description="Optional. Used to show £ cost per extraction. Leave blank to show tokens only.",
        default_value=None,
    ),
    CatalogueEntry(
        key="openai_output_price_per_1k_pence",
        value_type="float",
        group_name="ai",
        label="OpenAI output price (pence / 1k tokens)",
        description="Optional. Output tokens include reasoning tokens (≈0 here). Leave blank to show tokens only.",
        default_value=None,
    ),
    # Backup / export
    CatalogueEntry(
        key="backup_enabled",
        value_type="bool",
        group_name="backup",
        label="Scheduled backups enabled",
        description="When enabled, PlugTrack automatically snapshots the database on a recurring schedule.",
        default_value="true",
    ),
    CatalogueEntry(
        key="backup_interval_hours",
        value_type="int",
        group_name="backup",
        label="Backup interval (hours)",
        description="How often (in hours) the scheduled backup runs. Default 24 (once daily).",
        default_value="24",
    ),
    CatalogueEntry(
        key="backup_retention",
        value_type="int",
        group_name="backup",
        label="Backup retention (count)",
        description="Keep this many of the most recent backup snapshots; older ones are pruned automatically. Default 7.",
        default_value="7",
    ),
)
