"""Tests for SyncOrchestrator skeleton + per-car mutex."""
from __future__ import annotations

import asyncio

import pytest

from plugtrack.services.sync_orchestrator import (
    CarSyncState,
    SyncJob,
    SyncOrchestrator,
)


@pytest.mark.asyncio
async def test_state_creation_idempotent() -> None:
    orch = SyncOrchestrator()
    s1 = orch.ensure_state(1)
    s2 = orch.ensure_state(1)
    assert s1 is s2


@pytest.mark.asyncio
async def test_concurrent_sync_same_car_serialised_and_idempotent() -> None:
    """Two concurrent calls for the same car should hit the same job."""
    started: list[str] = []

    async def slow_worker(job: SyncJob, state: CarSyncState) -> None:
        started.append(job.job_id)
        await asyncio.sleep(0.05)

    orch = SyncOrchestrator(poll_worker=slow_worker)

    task_a = asyncio.create_task(orch.sync_car(1, kind="force"))
    # Yield once so task_a takes the lock first.
    await asyncio.sleep(0)
    task_b = asyncio.create_task(orch.sync_car(1, kind="force"))

    job_a = await task_a
    job_b = await task_b

    # Both callers receive the SAME job object — second call attached to
    # the in-flight one rather than queuing a new one.
    assert job_a.job_id == job_b.job_id
    assert started.count(job_a.job_id) == 1, "worker ran twice for the same call"


@pytest.mark.asyncio
async def test_different_cars_run_in_parallel() -> None:
    """sync_car(1) + sync_car(2) should run concurrently — not block on each other."""
    in_flight: set[int] = set()
    max_concurrent = 0

    async def worker(job: SyncJob, state: CarSyncState) -> None:
        nonlocal max_concurrent
        in_flight.add(job.car_id)
        max_concurrent = max(max_concurrent, len(in_flight))
        await asyncio.sleep(0.05)
        in_flight.remove(job.car_id)

    orch = SyncOrchestrator(poll_worker=worker)
    await asyncio.gather(orch.sync_car(1), orch.sync_car(2))
    assert max_concurrent == 2


@pytest.mark.asyncio
async def test_state_persists_across_calls() -> None:
    async def worker(job: SyncJob, state: CarSyncState) -> None:
        state.last_state = "PLUGGED_IN"
        state.last_soc = 42

    orch = SyncOrchestrator(poll_worker=worker)
    await orch.sync_car(7)
    s = orch.get_state(7)
    assert s is not None
    assert s.last_state == "PLUGGED_IN"
    assert s.last_soc == 42

    # Subsequent call sees the persisted state.
    seen_soc: list[int] = []

    async def reader(job: SyncJob, state: CarSyncState) -> None:
        seen_soc.append(state.last_soc or -1)

    orch.set_poll_worker(reader)
    await orch.sync_car(7)
    assert seen_soc == [42]


@pytest.mark.asyncio
async def test_worker_error_increments_failure_counter() -> None:
    async def boom(job: SyncJob, state: CarSyncState) -> None:
        raise RuntimeError("kaboom")

    orch = SyncOrchestrator(poll_worker=boom)
    job = await orch.sync_car(3)
    assert job.status == "failed"
    assert job.error_reason == "worker_error"

    state = orch.get_state(3)
    assert state is not None
    assert state.consecutive_failures == 1
    assert state.last_error == "kaboom"


@pytest.mark.asyncio
async def test_successful_sync_resets_failure_counter() -> None:
    sequence = iter([RuntimeError("boom"), None])

    async def worker(job: SyncJob, state: CarSyncState) -> None:
        nxt = next(sequence)
        if isinstance(nxt, Exception):
            raise nxt

    orch = SyncOrchestrator(poll_worker=worker)
    await orch.sync_car(5)
    state = orch.get_state(5)
    assert state is not None
    assert state.consecutive_failures == 1

    await orch.sync_car(5)
    state = orch.get_state(5)
    assert state is not None
    assert state.consecutive_failures == 0
    assert state.last_error is None


@pytest.mark.asyncio
async def test_worker_managed_failure_state_survives() -> None:
    """A worker that records its own failure (never raising) must not have
    its consecutive_failures / last_error clobbered by the orchestrator's
    success path. The production poll-worker swallows errors and reports
    them via the returned state, so the orchestrator must defer to it.
    """
    async def self_reporting_failure(job: SyncJob, state: CarSyncState) -> CarSyncState:
        # Mimic the production worker: never raises, records its own failure.
        state.consecutive_failures += 1
        state.last_error = "credentials_invalid"
        state.auth_invalid = True
        return state

    orch = SyncOrchestrator(poll_worker=self_reporting_failure)
    await orch.sync_car(1)
    s = orch.get_state(1)
    assert s is not None
    assert s.consecutive_failures == 1, "worker-recorded failure was clobbered"
    assert s.last_error == "credentials_invalid"
    assert s.auth_invalid is True


@pytest.mark.asyncio
async def test_active_job_clears_after_completion() -> None:
    async def quick(job: SyncJob, state: CarSyncState) -> None:
        return None

    orch = SyncOrchestrator(poll_worker=quick)
    await orch.sync_car(9)
    assert orch.active_job(9) is None
    state = orch.get_state(9)
    assert state is not None
    assert state.active_job_id is None
