# backend/plugtrack/services/telegram_manager.py
"""Owns the Telegram ingest bot task; reconciles it against DB settings.

Exactly one instance lives on app.state (single-worker tripwire). reconcile()
starts/stops/restarts the long-poll task to match current settings; health()
produces the shared HealthReport.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from .openai_admin import validate_key
from .telegram_health import HealthReport, build_health_report
from .telegram_ingest import (
    BotConfig, build_ingest_context, load_bot_config, read_raw_credentials, run_bot,
)

logger = logging.getLogger(__name__)


def _fingerprint(cfg: BotConfig) -> tuple:
    return (cfg.token, cfg.openai_key, cfg.model, cfg.car_id, cfg.user_id,
            frozenset(cfg.allowed))


class TelegramBotManager:
    def __init__(self, sessionmaker) -> None:
        self._sessionmaker = sessionmaker
        self._task: Optional[asyncio.Task] = None
        self._stop: Optional[asyncio.Event] = None
        self._ctx = None
        self._fp: Optional[tuple] = None
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def reconcile(self) -> None:
        async with self._lock:
            cfg = await load_bot_config(self._sessionmaker)
            if not isinstance(cfg, BotConfig):
                await self._stop_locked()
                return
            fp = _fingerprint(cfg)
            if self.is_running and fp == self._fp:
                return
            await self._stop_locked()
            self._ctx = build_ingest_context(
                cfg, sessionmaker=self._sessionmaker,
                health_check=lambda uid: self.health(requesting_user_id=uid),
            )
            self._stop = asyncio.Event()
            self._task = asyncio.create_task(run_bot(self._ctx, stop=self._stop))
            self._fp = fp
            logger.info("telegram bot started")
        # Yield control so the freshly-created task gets scheduled before the
        # next reconcile() observes is_running / the fingerprint.
        await asyncio.sleep(0)

    async def _stop_locked(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task, self._stop, self._ctx, self._fp = None, None, None, None

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def health(self, requesting_user_id: Optional[int] = None) -> HealthReport:
        from .telegram_client import TelegramClient

        cfg = await load_bot_config(self._sessionmaker)
        # Read the raw token/key/model from settings so the health report can
        # validate them DIRECTLY — even when the full config doesn't assemble
        # or the bot isn't running (the common case during setup).
        token, openai_key, model = await read_raw_credentials(self._sessionmaker)
        return await build_health_report(
            token=token, openai_key=openai_key, model=model,
            make_telegram_client=lambda t: TelegramClient(token=t),
            openai_validate=validate_key,
            config_or_problem=cfg, sessionmaker=self._sessionmaker,
            is_running=self.is_running, requesting_user_id=requesting_user_id,
            now=datetime.now(timezone.utc),
        )
