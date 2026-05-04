"""Production poll-worker that wires the StateMachine + adapter + DB.

The orchestrator (`SyncOrchestrator.sync_car`) calls a `poll_worker`
callable with `(job, state)`. Production wires this module's
`production_poll_worker` via a small factory closure (see `make_worker`)
that supplies the per-process collaborators (db sessionmaker, settings
provider, adapter provider) and the EventBus.

The worker:

1. Opens a `SyncRun` row.
2. Calls `adapter_provider(car)` to get an authenticated pycupra
   `Connection` (cached per-user).
3. Pulls a typed `VehicleState` snapshot.
4. Runs `StateMachine.step(state, telemetry)` → `Transitions`.
5. Persists the resulting row writes (PlugInRecord / ChargingSession),
   computes cost on close-session, runs location clustering on
   any→IDLE transitions, and updates SyncRun + emits sync.* events
   throughout.

Most of the moving parts are guarded by try/except → `sync.failed`
events with a stable `reason` string the frontend can switch on. The
worker NEVER raises out to the orchestrator: it returns the (possibly
unchanged) `CarSyncState` so the failure counter / backoff is owned in
one place.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from functools import partial
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import Car, ChargingSession, Location, PlugInRecord, SyncRun
from ..plugins.pycupra.models import Position, VehicleState
from .cost import compute_session_cost
from .event_bus import EventBus, SyncEvent
from .geocoding import get_provider as get_geocoding_provider
from .location_clustering import find_or_create_location
from .session_synthesiser import StateMachine, Transitions
from .sync_orchestrator import CarSyncState, SyncJob


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases for the providers the worker needs.
# ---------------------------------------------------------------------------

# Returns an authenticated provider connection (opaque). Tests inject a
# stub; production hands back a `pycupra.Connection`. Async because real
# auth is async.
AdapterProvider = Callable[[Car], Awaitable[Any]]

# Returns the flat dict of catalogue values we care about. Async because
# we read from the DB.
SettingsProvider = Callable[[int], Awaitable[dict]]

# The vehicle-state fetch — mockable in tests so we never need pycupra.
VehicleStateFetcher = Callable[[Any, str], Awaitable[VehicleState]]


# ---------------------------------------------------------------------------
# Per-process in-memory state carried between polls.
# ---------------------------------------------------------------------------

@dataclass
class _PlugInScratch:
    """In-memory book-keeping for one open plug-in window.

    Tracks the ids of any currently-open rows (so the worker can update
    them without re-querying), the GPS positions observed during the
    window (so location clustering can run when the cable is removed),
    and the accumulated power-curve samples for the active session.
    """

    plug_in_record_id: Optional[int] = None
    open_session_id: Optional[int] = None
    # All session ids opened during this plug-in window — patched with
    # the location_id when the cable is removed and clustering resolves.
    session_ids: list[int] = field(default_factory=list)
    positions: list[Position] = field(default_factory=list)
    power_curve: list[list[float]] = field(default_factory=list)
    session_start_at: Optional[datetime] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Default fetcher — the real adapter. Tests pass a stub.
# ---------------------------------------------------------------------------

async def _default_fetch(connection: Any, vehicle_id: str) -> VehicleState:
    # Imported lazily so unit tests that mock the fetcher never try to
    # import pycupra. Production's adapter_provider returns a real
    # pycupra Connection so this import path is exercised at runtime.
    from ..plugins.pycupra.adapter import fetch_vehicle_state

    return await fetch_vehicle_state(connection, vehicle_id)


# ---------------------------------------------------------------------------
# The worker.
# ---------------------------------------------------------------------------

class ProductionPollWorker:
    """Stateful worker — keeps the per-car plug-in scratch buffers."""

    def __init__(
        self,
        *,
        db_sessionmaker: async_sessionmaker[AsyncSession],
        settings_provider: SettingsProvider,
        adapter_provider: AdapterProvider,
        bus: EventBus,
        vehicle_state_fetcher: VehicleStateFetcher = _default_fetch,
        state_machine: Optional[StateMachine] = None,
    ) -> None:
        self._db_sessionmaker = db_sessionmaker
        self._settings_provider = settings_provider
        self._adapter_provider = adapter_provider
        self._bus = bus
        self._fetch = vehicle_state_fetcher
        self._state_machine = state_machine or StateMachine()
        # Per-car scratch buffers — populated when a plug-in opens,
        # consumed when it closes.
        self._scratch: dict[int, _PlugInScratch] = {}

    # ---------------- public entry ----------------

    async def __call__(self, job: SyncJob, state: CarSyncState) -> CarSyncState:
        return await self.run(job, state)

    async def run(self, job: SyncJob, state: CarSyncState) -> CarSyncState:
        started_at = _utcnow()
        run_started_perf = time.perf_counter()
        sync_run_id: Optional[int] = None

        # Resolve the car row up front so failures still get a SyncRun
        # entry pointing at the right vehicle.
        async with self._db_sessionmaker() as session:
            car = await session.get(Car, job.car_id)
            if car is None:
                # No car row — nothing we can do. Surface as a failure.
                await self._publish(
                    job, "sync.failed",
                    {"reason": "car_missing", "detail": f"car {job.car_id}"},
                )
                state.consecutive_failures += 1
                state.last_error = "car_missing"
                return state

            # Detach so we can reference its fields after the session
            # closes without lazy-loading.
            session.expunge(car)

        # Open the SyncRun row.
        async with self._db_sessionmaker() as session:
            sync_run = SyncRun(
                car_id=car.id,
                started_at=started_at,
                status="running",
                kind=job.kind,
            )
            session.add(sync_run)
            await session.commit()
            sync_run_id = sync_run.id

        await self._publish(
            job, "sync.started",
            {"job_id": job.job_id, "car_id": car.id, "kind": job.kind},
        )

        # ---- Authenticate + fetch telemetry ----
        try:
            connection = await self._adapter_provider(car)
        except _AuthError as exc:
            await self._fail_run(sync_run_id, "credentials_invalid", str(exc))
            await self._publish(
                job, "sync.failed",
                {"reason": "credentials_invalid", "detail": str(exc)},
            )
            state.consecutive_failures += 1
            state.last_error = "credentials_invalid"
            return state
        except Exception as exc:  # noqa: BLE001 — anything else is "network"
            await self._fail_run(sync_run_id, "network", str(exc))
            await self._publish(
                job, "sync.failed",
                {"reason": "network", "detail": str(exc)},
            )
            state.consecutive_failures += 1
            state.last_error = "network"
            return state

        if not car.provider_vehicle_id:
            await self._fail_run(
                sync_run_id, "vehicle_id_missing",
                "car.provider_vehicle_id is unset",
            )
            await self._publish(
                job, "sync.failed",
                {"reason": "vehicle_id_missing", "detail": ""},
            )
            state.consecutive_failures += 1
            state.last_error = "vehicle_id_missing"
            return state

        try:
            telemetry = await self._fetch(connection, car.provider_vehicle_id)
        except _AuthError as exc:
            await self._fail_run(sync_run_id, "credentials_invalid", str(exc))
            await self._publish(
                job, "sync.failed",
                {"reason": "credentials_invalid", "detail": str(exc)},
            )
            state.consecutive_failures += 1
            state.last_error = "credentials_invalid"
            return state
        except Exception as exc:  # noqa: BLE001
            await self._fail_run(sync_run_id, "network", str(exc))
            await self._publish(
                job, "sync.failed",
                {"reason": "network", "detail": str(exc)},
            )
            state.consecutive_failures += 1
            state.last_error = "network"
            return state

        # ---- Run the state machine ----
        transitions = self._state_machine.step(state, telemetry)

        await self._publish(
            job, "sync.poll_completed",
            {
                "state_observed": transitions.state_observed,
                "no_change": bool(transitions.no_change),
            },
        )

        emitted: list[str] = []
        opened = closed = updated = 0

        # Always track positions while we have an open plug-in (so the
        # any→IDLE branch can run clustering).
        scratch = self._scratch.get(car.id)
        if scratch is not None and telemetry.position is not None:
            scratch.positions.append(telemetry.position)

        # Sample the power curve while we're CHARGING. We do this
        # BEFORE applying transitions so the close_session branch sees
        # the final sample.
        if (
            scratch is not None
            and scratch.open_session_id is not None
            and state.last_state == "CHARGING"
            and telemetry.charging
        ):
            self._append_power_sample(scratch, telemetry)

        # ---- Apply each side-effect from the transitions ----
        if transitions.open_plug_in is not None:
            new_id = await self._handle_open_plug_in(
                job, car, transitions.open_plug_in, telemetry
            )
            scratch = self._scratch[car.id]
            scratch.plug_in_record_id = new_id
            emitted.append("open_plug_in")

        if transitions.open_session is not None:
            new_id = await self._handle_open_session(
                job, car, transitions.open_session, telemetry
            )
            scratch = self._scratch.setdefault(car.id, _PlugInScratch())
            scratch.open_session_id = new_id
            scratch.session_ids.append(new_id)
            scratch.session_start_at = transitions.open_session.get(
                "charge_start_at"
            )
            scratch.power_curve = []
            opened += 1
            emitted.append("open_session")

        if transitions.close_session is not None:
            await self._handle_close_session(
                job, car, transitions.close_session, telemetry,
            )
            closed += 1
            emitted.append("close_session")

        if transitions.error_session is not None:
            await self._handle_error_session(
                job, car, transitions.error_session, telemetry,
            )
            closed += 1
            emitted.append("error_session")

        if transitions.close_plug_in is not None:
            updated_count = await self._handle_close_plug_in(
                job, car, transitions.close_plug_in, telemetry,
            )
            updated += updated_count
            emitted.append("close_plug_in")

        # ---- Finalise the SyncRun ----
        final_status = "no_change" if transitions.no_change else "completed"
        async with self._db_sessionmaker() as session:
            run = await session.get(SyncRun, sync_run_id)
            if run is not None:
                run.status = final_status
                run.state_observed = transitions.state_observed
                run.transitions_emitted = emitted
                run.sessions_opened = opened
                run.sessions_closed = closed
                run.sessions_updated = updated
                run.ended_at = _utcnow()
                if transitions.unknown_state:
                    run.error_reason = "unknown_state"
                    run.error_detail = transitions.unknown_state
            await session.commit()

        # ---- Update in-memory state ----
        if transitions.state_observed:
            state.last_state = transitions.state_observed
        state.last_soc = telemetry.battery_level
        state.last_car_captured_timestamp = telemetry.car_captured_timestamp
        state.consecutive_failures = 0
        state.last_error = None

        duration_ms = int((time.perf_counter() - run_started_perf) * 1000)
        await self._publish(
            job, "sync.completed",
            {"job_id": job.job_id, "transitions": emitted, "duration_ms": duration_ms},
        )
        return state

    # ---------------- transition handlers ----------------

    async def _handle_open_plug_in(
        self,
        job: SyncJob,
        car: Car,
        payload: dict,
        telemetry: VehicleState,
    ) -> int:
        async with self._db_sessionmaker() as session:
            row = PlugInRecord(
                user_id=car.user_id,
                car_id=car.id,
                plug_in_at=payload["plug_in_at"],
                plug_in_soc=int(payload["plug_in_soc"]),
                plug_in_odometer_km=payload.get("plug_in_odometer_km"),
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            row_id = row.id

        # Reset scratch for the new plug-in window.
        scratch = _PlugInScratch(plug_in_record_id=row_id)
        if telemetry.position is not None:
            scratch.positions.append(telemetry.position)
        self._scratch[car.id] = scratch

        await self._publish(
            job, "sync.plug_in_opened",
            {
                "plug_in_record": {
                    "id": row_id,
                    "car_id": car.id,
                    "plug_in_at": payload["plug_in_at"],
                    "plug_in_soc": payload["plug_in_soc"],
                    "plug_in_odometer_km": payload.get("plug_in_odometer_km"),
                },
            },
        )
        return row_id

    async def _handle_open_session(
        self,
        job: SyncJob,
        car: Car,
        payload: dict,
        telemetry: VehicleState,
    ) -> int:
        scratch = self._scratch.get(car.id)
        plug_in_id = scratch.plug_in_record_id if scratch is not None else None
        charge_start_at: datetime = payload["charge_start_at"]
        async with self._db_sessionmaker() as session:
            row = ChargingSession(
                user_id=car.user_id,
                car_id=car.id,
                plug_in_record_id=plug_in_id,
                date=charge_start_at.date() if isinstance(charge_start_at, datetime) else date.today(),
                charge_start_at=charge_start_at,
                charge_end_at=None,
                start_soc=int(payload["start_soc"]),
                end_soc=int(payload["start_soc"]),
                kwh_added=0.0,
                odometer_at_session_km=payload.get("odometer_at_session_km"),
                charging_type=payload.get("charging_type", "unknown"),
                charging_mode=payload.get("charging_mode", "unknown"),
                interrupted=False,
                source="synthesis",
                raw_payload={
                    "charging_state_raw": telemetry.charging_state_raw,
                    "charging_power": telemetry.charging_power,
                    "target_soc": telemetry.target_soc,
                },
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            row_id = row.id

        await self._publish(
            job, "sync.session_opened",
            {
                "session": {
                    "id": row_id,
                    "car_id": car.id,
                    "plug_in_record_id": plug_in_id,
                    "charge_start_at": charge_start_at,
                    "start_soc": payload["start_soc"],
                    "charging_type": payload.get("charging_type", "unknown"),
                    "charging_mode": payload.get("charging_mode", "unknown"),
                },
            },
        )
        return row_id

    async def _handle_close_session(
        self,
        job: SyncJob,
        car: Car,
        payload: dict,
        telemetry: VehicleState,
    ) -> None:
        scratch = self._scratch.get(car.id)
        session_id = scratch.open_session_id if scratch is not None else None
        if session_id is None:
            # Sub-poll-interval: open + close in one cycle. The most
            # recent session id from this plug-in window is what we want.
            if scratch is not None and scratch.session_ids:
                session_id = scratch.session_ids[-1]
        if session_id is None:
            logger.warning("close_session with no open session for car %s", car.id)
            return

        end_soc = int(payload["end_soc"])

        async with self._db_sessionmaker() as session:
            row = await session.get(ChargingSession, session_id)
            if row is None:
                logger.warning("close_session: session %s missing", session_id)
                return

            start_soc = row.start_soc
            row.charge_end_at = payload["charge_end_at"]
            row.end_soc = end_soc
            row.interrupted = bool(payload.get("interrupted", False))
            kwh_added = max(0.0, (end_soc - start_soc) / 100.0 * float(car.battery_kwh))
            row.kwh_added = kwh_added

            # Cost computation. Use the linked location (via the
            # plug_in_record) when available.
            location: Optional[Location] = None
            if row.plug_in_record_id is not None:
                pir = await session.get(PlugInRecord, row.plug_in_record_id)
                if pir is not None and pir.location_id is not None:
                    location = await session.get(Location, pir.location_id)

            settings = await self._settings_provider(car.user_id)
            home_rate = float(settings.get("default_home_rate_p_per_kwh") or 0.0)
            cost_pence, cost_basis, tariff_p = compute_session_cost(
                kwh_added=kwh_added,
                location=location,
                session_overrides={
                    "cost_per_kwh_override_p": row.cost_per_kwh_override_p,
                    "total_cost_pence_override": row.total_cost_pence_override,
                },
                settings_default_home_rate_p_per_kwh=home_rate,
            )
            row.cost_pence = cost_pence
            row.cost_basis = cost_basis
            row.tariff_p_per_kwh = tariff_p

            # Persist the accumulated power curve.
            if scratch is not None and scratch.power_curve:
                row.power_curve = list(scratch.power_curve)
                scratch.power_curve = []

            payload_for_event = {
                "id": row.id,
                "car_id": row.car_id,
                "charge_end_at": row.charge_end_at,
                "end_soc": row.end_soc,
                "kwh_added": row.kwh_added,
                "cost_pence": row.cost_pence,
                "cost_basis": row.cost_basis,
                "tariff_p_per_kwh": row.tariff_p_per_kwh,
                "interrupted": row.interrupted,
            }
            await session.commit()

        if scratch is not None:
            scratch.open_session_id = None

        await self._publish(
            job, "sync.session_closed",
            {"session": payload_for_event},
        )

    async def _handle_error_session(
        self,
        job: SyncJob,
        car: Car,
        payload: dict,
        telemetry: VehicleState,
    ) -> None:
        scratch = self._scratch.get(car.id)
        session_id = scratch.open_session_id if scratch is not None else None
        if session_id is None:
            logger.warning("error_session with no open session for car %s", car.id)
            return

        async with self._db_sessionmaker() as session:
            row = await session.get(ChargingSession, session_id)
            if row is None:
                return
            row.charge_end_at = payload["charge_end_at"]
            row.end_soc = int(payload["end_soc"])
            row.interrupted = True
            row.error_reason = payload.get("error_reason")
            await session.commit()

        if scratch is not None:
            scratch.open_session_id = None

        await self._publish(
            job, "sync.session_closed",
            {
                "session": {
                    "id": session_id,
                    "car_id": car.id,
                    "interrupted": True,
                    "error_reason": payload.get("error_reason"),
                },
            },
        )
        await self._publish(
            job, "sync.error",
            {"message": payload.get("error_reason", "")},
        )

    async def _handle_close_plug_in(
        self,
        job: SyncJob,
        car: Car,
        payload: dict,
        telemetry: VehicleState,
    ) -> int:
        scratch = self._scratch.pop(car.id, None)
        plug_in_id = scratch.plug_in_record_id if scratch is not None else None
        updated = 0

        # 1. Close the plug_in_record row.
        if plug_in_id is not None:
            async with self._db_sessionmaker() as session:
                row = await session.get(PlugInRecord, plug_in_id)
                if row is not None:
                    row.plug_out_at = payload["plug_out_at"]
                    row.plug_out_soc = int(payload["plug_out_soc"])
                    row.plug_out_odometer_km = payload.get("plug_out_odometer_km")
                    await session.commit()

            await self._publish(
                job, "sync.plug_in_closed",
                {
                    "plug_in_record": {
                        "id": plug_in_id,
                        "car_id": car.id,
                        "plug_out_at": payload["plug_out_at"],
                        "plug_out_soc": payload["plug_out_soc"],
                        "plug_out_odometer_km": payload.get("plug_out_odometer_km"),
                    },
                },
            )

        # 2. Run location clustering if any positions were observed.
        location_id: Optional[int] = None
        positions = scratch.positions if scratch is not None else []
        if positions and plug_in_id is not None:
            avg_lat = sum(p.lat for p in positions) / len(positions)
            avg_lng = sum(p.lng for p in positions) / len(positions)
            was_created = False
            async with self._db_sessionmaker() as session:
                location, was_created = await find_or_create_location(
                    session, car.user_id, avg_lat, avg_lng
                )
                await session.commit()
                location_id = location.id

            # Patch the plug-in + every session opened in this window.
            async with self._db_sessionmaker() as session:
                pir = await session.get(PlugInRecord, plug_in_id)
                if pir is not None:
                    pir.location_id = location_id
                if scratch is not None:
                    for sid in scratch.session_ids:
                        sess_row = await session.get(ChargingSession, sid)
                        if sess_row is not None:
                            sess_row.location_id = location_id
                await session.commit()

            for sid in (scratch.session_ids if scratch is not None else []):
                updated += 1
                await self._publish(
                    job, "sync.session_updated",
                    {"session_id": sid, "fields": ["location_id"]},
                )

            # 3. If we just created a brand-new location row, schedule a
            #    fire-and-forget reverse-geocode. The actual provider
            #    call inside `_geocode_async` is wrapped in
            #    `asyncio.shield` so worker / lifespan shutdown doesn't
            #    kill a mid-flight HTTP request and leave the row
            #    half-populated.
            if was_created and location_id is not None:
                user_id = car.user_id
                asyncio.create_task(
                    self._geocode_async(user_id, location_id, avg_lat, avg_lng)
                )

        return updated

    async def _geocode_async(
        self,
        user_id: int,
        location_id: int,
        lat: float,
        lng: float,
    ) -> None:
        """Background reverse-geocode for a freshly-created Location.

        Reads settings, picks a provider via the factory, and writes the
        result back. Failures (network, parse, provider-disabled) are
        logged and the row is left with `address=NULL`.
        """
        try:
            settings = await self._settings_provider(user_id)
        except Exception:
            logger.exception("geocode: failed to read settings")
            return

        try:
            provider = get_geocoding_provider(settings)
        except ValueError as exc:
            # Provider mis-configured (e.g. mapbox without key). Log and
            # bail — the row stays unannotated until the user fixes
            # settings + re-runs.
            logger.warning("geocode: provider misconfigured: %s", exc)
            return

        try:
            # Shield the actual HTTP round-trip so a worker/lifespan
            # shutdown mid-fetch doesn't cancel an in-flight request and
            # leave the location row half-populated.
            result = await asyncio.shield(provider.reverse(lat, lng))
        except asyncio.CancelledError:
            # Re-raise so the surrounding task knows it was cancelled,
            # but the shielded inner request continues to completion in
            # its own task per asyncio.shield semantics.
            raise
        except Exception:
            logger.exception("geocode: provider raised")
            return

        if result is None:
            # NoOp / no-match / network error already logged inside the
            # provider.
            return

        try:
            async with self._db_sessionmaker() as session:
                row = await session.get(Location, location_id)
                if row is None:
                    return
                row.address = result.address
                row.address_provider = result.provider
                row.address_fetched_at = _utcnow()
                await session.commit()
        except Exception:
            logger.exception("geocode: db write failed for location %s", location_id)

    # ---------------- helpers ----------------

    def _append_power_sample(
        self, scratch: _PlugInScratch, telemetry: VehicleState
    ) -> None:
        if scratch.session_start_at is None:
            return
        delta = (
            telemetry.car_captured_timestamp - scratch.session_start_at
        ).total_seconds()
        scratch.power_curve.append(
            [
                float(delta),
                float(telemetry.battery_level),
                float(telemetry.charging_power or 0.0),
            ]
        )

    async def _publish(self, job: SyncJob, event: str, data: dict) -> None:
        try:
            await self._bus.publish(
                SyncEvent(event=event, data=data, job_id=job.job_id)
            )
        except Exception:
            # Event-bus failures must not crash the worker.
            logger.exception("event-bus publish failed for %s", event)

    async def _fail_run(
        self, sync_run_id: Optional[int], reason: str, detail: str
    ) -> None:
        if sync_run_id is None:
            return
        async with self._db_sessionmaker() as session:
            run = await session.get(SyncRun, sync_run_id)
            if run is None:
                return
            run.status = "failed"
            run.error_reason = reason
            run.error_detail = detail[:1024] if detail else None
            run.ended_at = _utcnow()
            await session.commit()


# ---------------------------------------------------------------------------
# Public API: factory functions used by main.py and tests.
# ---------------------------------------------------------------------------

class _AuthError(Exception):
    """Raised by adapter providers when credentials are rejected.

    The worker translates this to `sync.failed` with
    `reason='credentials_invalid'`. Network/transient errors should NOT
    use this — anything else is bucketed as `network`.
    """


# ---------------------------------------------------------------------------
# Lifespan wiring helpers — settings + adapter providers.
# ---------------------------------------------------------------------------

# In-memory cache of authenticated provider connections, keyed by user_id.
# Cleared by `clear_cached_connections()` when the user wipes tokens via
# the Settings page.
_connections: dict[int, Any] = {}


def clear_cached_connections() -> None:
    """Wipe the per-user adapter connection cache.

    Called by the `clear-pycupra-tokens` settings route so the next sync
    re-authenticates from disk + the freshly-saved settings.
    """
    _connections.clear()


async def get_user_sync_settings(session: AsyncSession, user_id: int) -> dict:
    """Read the settings catalogue values relevant to sync.

    `user_id` is currently unused (single-user app, settings are
    process-wide), but threaded through so a future migration to
    per-user settings doesn't break callers.
    """
    from ..models import Setting

    keys = (
        "sync_enabled",
        "sync_interval_minutes_idle",
        "sync_interval_minutes_plugged",
        "sync_interval_minutes_charging",
        "default_home_rate_p_per_kwh",
        "cupra_username",
        "cupra_password",
        "cupra_spin",
    )
    result = await session.execute(
        select(Setting).where(Setting.key.in_(keys))
    )
    rows = result.scalars().all()
    return {row.key: row.value for row in rows}


def make_settings_provider(
    db_sessionmaker: async_sessionmaker[AsyncSession],
) -> SettingsProvider:
    """Return an async settings_provider closure bound to the db."""

    async def _provider(user_id: int) -> dict:
        async with db_sessionmaker() as session:
            return await get_user_sync_settings(session, user_id)

    return _provider


def make_pycupra_adapter_provider(
    db_sessionmaker: async_sessionmaker[AsyncSession],
    *,
    token_dir: Optional[Any] = None,
) -> AdapterProvider:
    """Return an async adapter_provider that lazily authenticates pycupra.

    On first call per-user it decrypts cupra credentials from settings,
    calls `authenticate(...)`, and caches the resulting Connection in
    `_connections`. On subsequent calls the cached Connection is
    returned. Auth failures pop the cache so the next call retries.
    """
    from pathlib import Path

    from ..bootstrap import get_settings as get_app_settings
    from ..plugins.pycupra.adapter import authenticate
    from ..plugins.pycupra.models import Credentials
    from ..security.crypto import decrypt_secret

    resolved_token_dir = (
        Path(token_dir)
        if token_dir is not None
        else Path(__file__).resolve().parents[3] / "data" / "pycupra"
    )
    auth_lock = asyncio.Lock()

    async def _provider(car: Car) -> Any:
        cached = _connections.get(car.user_id)
        if cached is not None:
            return cached
        async with auth_lock:
            cached = _connections.get(car.user_id)
            if cached is not None:
                return cached
            settings_map = await make_settings_provider(db_sessionmaker)(car.user_id)
            username = settings_map.get("cupra_username")
            password_raw = settings_map.get("cupra_password")
            spin_raw = settings_map.get("cupra_spin")
            if not username or not password_raw:
                raise _AuthError("cupra credentials not configured")

            app_secret = get_app_settings().app_secret_key
            try:
                password = decrypt_secret(password_raw, app_secret)
                spin = (
                    decrypt_secret(spin_raw, app_secret) if spin_raw else None
                )
            except Exception as exc:  # noqa: BLE001
                raise _AuthError(f"failed to decrypt credentials: {exc}") from exc

            try:
                connection = await authenticate(
                    Credentials(username=username, password=password, spin=spin),
                    token_dir=resolved_token_dir,
                )
            except Exception as exc:  # noqa: BLE001
                # Auth failures should not retain a half-open Connection.
                _connections.pop(car.user_id, None)
                raise _AuthError(str(exc)) from exc

            _connections[car.user_id] = connection
            return connection

    return _provider


def make_worker(
    *,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings_provider: SettingsProvider,
    adapter_provider: AdapterProvider,
    bus: EventBus,
    vehicle_state_fetcher: VehicleStateFetcher = _default_fetch,
) -> Callable[[SyncJob, CarSyncState], Awaitable[CarSyncState]]:
    """Build the orchestrator-shaped poll worker.

    The orchestrator's contract is `(job, state) -> Awaitable`. We bind
    the collaborators here and return a closure matching that shape.
    """
    worker = ProductionPollWorker(
        db_sessionmaker=db_sessionmaker,
        settings_provider=settings_provider,
        adapter_provider=adapter_provider,
        bus=bus,
        vehicle_state_fetcher=vehicle_state_fetcher,
    )
    return worker


# ---------------------------------------------------------------------------
# Public function-style alias.
#
# The spec describes the worker as a free function with this signature:
#
#     async def production_poll_worker(
#         job, car, state, bus, *, db_sessionmaker, settings_provider,
#         adapter_provider,
#     ) -> CarSyncState
#
# We keep that as a thin wrapper over the class for callers that want
# the spec-shaped API directly (e.g. tests).
# ---------------------------------------------------------------------------

async def production_poll_worker(
    job: SyncJob,
    car: Car,
    state: CarSyncState,
    bus: EventBus,
    *,
    db_sessionmaker: async_sessionmaker[AsyncSession],
    settings_provider: SettingsProvider,
    adapter_provider: AdapterProvider,
    vehicle_state_fetcher: VehicleStateFetcher = _default_fetch,
) -> CarSyncState:
    """Spec-shaped façade around ProductionPollWorker.

    `car` is accepted for spec compatibility but the worker re-resolves
    it from `job.car_id` internally so the per-process scratch buffers
    stay keyed off a single source of truth.
    """
    worker = ProductionPollWorker(
        db_sessionmaker=db_sessionmaker,
        settings_provider=settings_provider,
        adapter_provider=adapter_provider,
        bus=bus,
        vehicle_state_fetcher=vehicle_state_fetcher,
    )
    return await worker.run(job, state)


__all__ = [
    "ProductionPollWorker",
    "_AuthError",
    "AdapterProvider",
    "SettingsProvider",
    "VehicleStateFetcher",
    "clear_cached_connections",
    "get_user_sync_settings",
    "make_pycupra_adapter_provider",
    "make_settings_provider",
    "make_worker",
    "production_poll_worker",
]
