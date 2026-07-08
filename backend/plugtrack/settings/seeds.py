"""Idempotent seeding of the `setting` table from the catalogue."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Setting
from .catalogue import CATALOGUE


async def seed_defaults(session: AsyncSession) -> int:
    """Insert any catalogue rows missing from the `setting` table.

    Returns the number of rows inserted. Existing rows (regardless of
    current value) are never modified.
    """
    result = await session.execute(select(Setting.key))
    existing = {row[0] for row in result.all()}

    inserted = 0
    for entry in CATALOGUE:
        if entry.key in existing:
            continue
        session.add(
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
        inserted += 1
    await session.flush()
    return inserted
