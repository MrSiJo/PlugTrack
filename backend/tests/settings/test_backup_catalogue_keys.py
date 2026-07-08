"""Failing test for backup catalogue keys (Task 1).

Assert that backup_enabled, backup_interval_hours, and backup_retention
exist in the CATALOGUE with the correct value_type, group_name, and
default_value before any implementation is added.
"""

from __future__ import annotations

import pytest
from plugtrack.settings.catalogue import CATALOGUE

BACKUP_KEYS = {
    "backup_enabled": ("bool", "backup", "true"),
    "backup_interval_hours": ("int", "backup", "24"),
    "backup_retention": ("int", "backup", "7"),
}


def test_backup_keys_present_with_expected_types_and_groups():
    by_key = {e.key: e for e in CATALOGUE}
    for key, (vtype, group, default) in BACKUP_KEYS.items():
        assert key in by_key, f"{key} missing from catalogue"
        assert by_key[key].value_type == vtype, f"{key}: expected value_type={vtype!r}"
        assert by_key[key].group_name == group, f"{key}: expected group_name={group!r}"
        assert by_key[key].default_value == default, (
            f"{key}: expected default_value={default!r}, got {by_key[key].default_value!r}"
        )
        assert by_key[key].is_secret is False, f"{key} should not be secret"


@pytest.mark.asyncio
async def test_backup_keys_seeded(test_sessionmaker):
    """seed_defaults must insert the backup keys into the setting table."""
    from plugtrack.models import Setting
    from plugtrack.settings.seeds import seed_defaults
    from sqlalchemy import select

    async with test_sessionmaker() as s:
        await seed_defaults(s)
        await s.commit()
        rows = {r.key for r in (await s.execute(select(Setting))).scalars().all()}

    for key in BACKUP_KEYS:
        assert key in rows, f"{key} not seeded"
