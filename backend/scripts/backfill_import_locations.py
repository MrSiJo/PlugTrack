# backend/scripts/backfill_import_locations.py
"""One-off: link/create Locations for existing source='import' sessions.

Run inside the API container:
    docker compose -f compose-dev.yaml exec plugtrack-api python -m scripts.backfill_import_locations
"""
import asyncio

from plugtrack.db import SessionLocal
from plugtrack.services.ingest_location import (
    backfill_import_session_locations, clean_location_name,
)
from plugtrack.services.telegram_ingest import BotConfig, load_bot_config


async def main() -> None:
    config = await load_bot_config(SessionLocal)
    name_cleaner = None
    if isinstance(config, BotConfig):
        user_id = config.user_id
        key, model = config.openai_key, config.model

        async def name_cleaner(network, label, address):  # noqa: F811
            return await clean_location_name(network, label, address, api_key=key, model=model)
    else:
        # Fall back to the first user; no LLM cleaner (deterministic names only).
        from sqlalchemy import select
        from plugtrack.models import User
        async with SessionLocal() as s:
            user_id = (await s.execute(select(User.id).order_by(User.id))).scalars().first()
        if user_id is None:
            print("no user found; nothing to do")
            return

    async with SessionLocal() as s:
        n = await backfill_import_session_locations(s, user_id=user_id, name_cleaner=name_cleaner)
        await s.commit()
    print(f"backfill linked {n} session(s)")


if __name__ == "__main__":
    asyncio.run(main())
