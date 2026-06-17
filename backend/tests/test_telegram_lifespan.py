# backend/tests/test_telegram_lifespan.py
import pytest


@pytest.mark.asyncio
async def test_manager_present_bot_not_started_by_default(app):
    async with app.router.lifespan_context(app):
        mgr = getattr(app.state, "telegram_manager", None)
        assert mgr is not None
        assert mgr.is_running is False  # disabled by default
