"""Tests for the ChargingHistoryProvider Protocol.

The contract is structural — anything with a matching `fetch_sessions`
method satisfies it without explicit subclassing.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plugtrack.plugins.contracts import ChargingHistoryProvider, RawChargingSession


class _StubProvider:
    """No-op provider used purely to verify Protocol conformance."""

    async def fetch_sessions(self, car, since):  # type: ignore[no-untyped-def]
        return []


def test_stub_provider_satisfies_protocol():
    stub = _StubProvider()
    assert isinstance(stub, ChargingHistoryProvider)


def test_object_without_method_does_not_satisfy_protocol():
    class _NoMethod:
        pass

    assert not isinstance(_NoMethod(), ChargingHistoryProvider)


def test_raw_charging_session_is_frozen():
    raw = RawChargingSession(
        start_soc=20,
        end_soc=80,
        kwh_added=42.0,
        charge_start_at=datetime.now(timezone.utc),
        charge_end_at=datetime.now(timezone.utc),
        telematics_session_id="abc123",
    )
    with pytest.raises((AttributeError, TypeError)):
        raw.start_soc = 30  # type: ignore[misc]
    # Reserved fields default to None.
    assert raw.evse_id is None
    assert raw.energy_loss_kwh is None
    assert raw.voucher_amount_pence is None
