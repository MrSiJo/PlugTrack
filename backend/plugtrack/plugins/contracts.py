"""Plugin contracts for swappable providers.

v1 ships NO implementation of `ChargingHistoryProvider` — pycupra
exposes no charging history (verified live in Phase 0). Sessions are
synthesised in-app from polled telemetry. The contract is here so a
future personal/private plugin can satisfy it without forking the
codebase.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ..models import Car


@dataclass(frozen=True)
class RawChargingSession:
    """Provider-agnostic charging-session record returned by a history provider.

    Mirrors the user-relevant subset of the `charging_session` schema
    (spec §3.3) — the orchestrator merges these with synthesised
    sessions, deduping on `telematics_session_id`.
    """

    start_soc: int
    end_soc: int
    kwh_added: float
    charge_start_at: datetime
    charge_end_at: datetime
    telematics_session_id: Optional[str]

    # Reserved cariad-style fields, all Optional. v1 will leave these
    # NULL even if a future provider populates them — they exist so the
    # storage layer is forward-compatible.
    evse_id: Optional[str] = None
    station_address: Optional[str] = None
    energy_loss_kwh: Optional[float] = None
    authentication_type: Optional[str] = None
    contract: Optional[str] = None
    voucher_amount_pence: Optional[int] = None
    blocking_fees_pence: Optional[int] = None


@runtime_checkable
class ChargingHistoryProvider(Protocol):
    """Structural contract for a charging-history provider.

    Implementers must offer an async `fetch_sessions(car, since)` method
    returning a list of `RawChargingSession`. Runtime-checkable so the
    orchestrator can probe registration status without importing the
    plugin module directly.
    """

    async def fetch_sessions(
        self, car: "Car", since: datetime
    ) -> list[RawChargingSession]: ...
