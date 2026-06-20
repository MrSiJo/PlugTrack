# backend/plugtrack/services/telegram_health.py
"""Shared health check for the Telegram ingest bot.

Pure-ish: collaborators (telegram client, openai validator, sessionmaker,
the loaded config, running flag, clock) are injected so the same report
backs POST /api/telegram/test and the in-chat /test command.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from .telegram_ingest import BotConfig, ConfigProblem


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class UsageSummary:
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cost_pence: Optional[int]


@dataclass
class HealthReport:
    checks: list[Check]
    all_ok: bool
    usage_this_month: Optional[UsageSummary]


async def _month_usage(sessionmaker, *, now: datetime, config: Optional[BotConfig]) -> Optional[UsageSummary]:
    from ..models import ScreenshotImport
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with sessionmaker() as s:
        rows = (await s.execute(
            select(ScreenshotImport).where(ScreenshotImport.created_at >= start)
        )).scalars().all()
    it = sum(r.input_tokens or 0 for r in rows)
    ot = sum(r.output_tokens or 0 for r in rows)
    rt = sum(r.reasoning_tokens or 0 for r in rows)
    cost = None
    if config and config.input_price_p is not None and config.output_price_p is not None:
        cost = round(it / 1000 * config.input_price_p + ot / 1000 * config.output_price_p)
    return UsageSummary(input_tokens=it, output_tokens=ot, reasoning_tokens=rt, cost_pence=cost)


# Config-problem reasons already covered by the dedicated Telegram/OpenAI
# checks below — don't duplicate them as generic "Config" ✗ lines.
_COVERED_REASONS = {"telegram_bot_token not set", "openai_api_key not set"}


async def build_health_report(
    *,
    token: Optional[str],
    openai_key: Optional[str],
    model: Optional[str],
    make_telegram_client: Callable[[str], Any],
    openai_validate: Callable[[str], Awaitable[tuple[bool, str]]],
    config_or_problem,
    sessionmaker,
    is_running: bool,
    requesting_user_id: Optional[int] = None,
    now: datetime,
) -> HealthReport:
    checks: list[Check] = []
    config = config_or_problem if isinstance(config_or_problem, BotConfig) else None

    # Telegram — validate the configured token directly via getMe, regardless
    # of whether the long-poll bot is currently running. This makes Test a
    # real diagnostic *during setup* (before the bot can start).
    if token:
        client = make_telegram_client(token)
        try:
            me = await client.get_me()
            uname = me.get("username")
            checks.append(Check("Telegram", True, f"connected as @{uname}" if uname else "connected"))
        except Exception as exc:  # noqa: BLE001
            checks.append(Check("Telegram", False, f"token check failed: {exc}"))
        finally:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:  # noqa: BLE001
                    pass
    else:
        checks.append(Check("Telegram", False, "bot token not set"))

    # OpenAI — validate the configured key directly, independent of whether
    # the rest of the config assembled.
    if openai_key:
        ok, detail = await openai_validate(openai_key)
        checks.append(Check("OpenAI", ok, f"{detail} ({model})" if (ok and model) else detail))
    else:
        checks.append(Check("OpenAI", False, "API key not set"))

    # Allowlist (only meaningful once the full config assembled).
    if config:
        # A web/UI caller has no Telegram identity, so requesting_user_id is
        # None there and we only confirm the allowlist is configured. The
        # in-chat /test command passes the real Telegram from_id for a true
        # membership check.
        allow_ok = requesting_user_id is None or requesting_user_id in config.allowed
        detail = "configured" if requesting_user_id is None else (
            "you are on the allowlist" if allow_ok else "you are NOT on the allowlist")
        checks.append(Check("Allowlist", allow_ok, detail))
    else:
        for reason in config_or_problem.reasons:
            if reason in _COVERED_REASONS:
                continue
            checks.append(Check("Config", False, reason))

    checks.append(Check("Bot running", is_running, "yes" if is_running else "no"))

    usage = await _month_usage(sessionmaker, now=now, config=config)
    all_ok = all(c.ok for c in checks)
    return HealthReport(checks=checks, all_ok=all_ok, usage_this_month=usage)


def format_health_text(report: HealthReport) -> str:
    lines = [("✓" if c.ok else "✗") + f" {c.name}: {c.detail}" for c in report.checks]
    if report.usage_this_month:
        u = report.usage_this_month
        cost = f" · £{u.cost_pence/100:.2f}" if u.cost_pence is not None else ""
        lines.append(f"📊 This month: {u.input_tokens + u.output_tokens} tokens{cost}")
    return "\n".join(lines)
