# backend/tests/services/test_telegram_manager.py
import asyncio
import pytest

from plugtrack.services.telegram_manager import TelegramBotManager
from plugtrack.services.telegram_ingest import BotConfig, ConfigProblem


@pytest.mark.asyncio
async def test_reconcile_starts_and_stops(monkeypatch, test_sessionmaker):
    started = asyncio.Event()
    async def fake_run_bot(ctx, *, stop):
        started.set()
        await stop.wait()
    monkeypatch.setattr("plugtrack.services.telegram_manager.run_bot", fake_run_bot)

    cfg = BotConfig(token="t", openai_key="k", model="gpt-5-mini",
                    allowed={111}, user_id=1)
    state = {"cfg": cfg}
    async def fake_load(sm):
        return state["cfg"]
    monkeypatch.setattr("plugtrack.services.telegram_manager.load_bot_config", fake_load)
    monkeypatch.setattr("plugtrack.services.telegram_manager.build_ingest_context",
                        lambda c, *, sessionmaker, health_check, ai_enabled: object())

    mgr = TelegramBotManager(test_sessionmaker)
    await mgr.reconcile()
    await asyncio.wait_for(started.wait(), 1)
    assert mgr.is_running

    state["cfg"] = ConfigProblem(reasons=["disabled"])
    await mgr.reconcile()
    assert not mgr.is_running
    await mgr.stop()


@pytest.mark.asyncio
async def test_reconcile_idempotent_no_restart(monkeypatch, test_sessionmaker):
    runs = {"n": 0}
    async def fake_run_bot(ctx, *, stop):
        runs["n"] += 1
        await stop.wait()
    monkeypatch.setattr("plugtrack.services.telegram_manager.run_bot", fake_run_bot)
    cfg = BotConfig(token="t", openai_key="k", model="m", allowed={1}, user_id=1)
    monkeypatch.setattr("plugtrack.services.telegram_manager.load_bot_config",
                        lambda sm: _coro(cfg))
    monkeypatch.setattr("plugtrack.services.telegram_manager.build_ingest_context",
                        lambda c, *, sessionmaker, health_check, ai_enabled: object())
    mgr = TelegramBotManager(test_sessionmaker)
    await mgr.reconcile()
    await mgr.reconcile()  # unchanged fingerprint -> no new task
    assert runs["n"] == 1
    await mgr.stop()


def test_fingerprint_differs_on_ai_enabled():
    from plugtrack.services.telegram_manager import _fingerprint
    base = BotConfig(token="t", openai_key="k", model="m", allowed={1}, user_id=1,
                     ai_enabled=False)
    enabled = BotConfig(token="t", openai_key="k", model="m", allowed={1}, user_id=1,
                        ai_enabled=True)
    assert _fingerprint(base) != _fingerprint(enabled)


async def _coro(v):
    return v
