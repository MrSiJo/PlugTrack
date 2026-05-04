"""Tests for the in-process event bus."""
from __future__ import annotations

import asyncio

import pytest

from plugtrack.services.event_bus import EventBus, SyncEvent, get_event_bus, reset_event_bus


@pytest.mark.asyncio
async def test_singleton_returns_same_instance() -> None:
    reset_event_bus()
    bus_a = get_event_bus()
    bus_b = get_event_bus()
    assert bus_a is bus_b


@pytest.mark.asyncio
async def test_subscribe_receives_published_events_in_order() -> None:
    bus = EventBus()
    job_id = "job-1"
    received: list[SyncEvent] = []

    async def consumer():
        async for evt in bus.subscribe(job_id):
            received.append(evt)

    task = asyncio.create_task(consumer())
    # Yield so the subscriber registers.
    await asyncio.sleep(0)

    await bus.publish(SyncEvent(event="sync.started", data={"car_id": 1}, job_id=job_id))
    await bus.publish(SyncEvent(event="sync.transition", data={"to": "PLUGGED_IN"}, job_id=job_id))
    await bus.publish(SyncEvent(event="sync.completed", data={"duration_ms": 10}, job_id=job_id))

    await asyncio.wait_for(task, timeout=1.0)

    assert [e.event for e in received] == [
        "sync.started",
        "sync.transition",
        "sync.completed",
    ]


@pytest.mark.asyncio
async def test_completed_event_terminates_iterator() -> None:
    bus = EventBus()
    job_id = "job-end"

    async def consumer() -> int:
        count = 0
        async for _ in bus.subscribe(job_id):
            count += 1
        return count

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await bus.publish(SyncEvent(event="sync.started", data={}, job_id=job_id))
    await bus.publish(SyncEvent(event="sync.completed", data={}, job_id=job_id))
    count = await asyncio.wait_for(task, timeout=1.0)
    assert count == 2


@pytest.mark.asyncio
async def test_failed_event_also_terminates_iterator() -> None:
    bus = EventBus()
    job_id = "job-fail"

    async def consumer() -> int:
        count = 0
        async for _ in bus.subscribe(job_id):
            count += 1
        return count

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await bus.publish(SyncEvent(event="sync.failed", data={"reason": "auth"}, job_id=job_id))
    count = await asyncio.wait_for(task, timeout=1.0)
    assert count == 1


@pytest.mark.asyncio
async def test_multi_subscriber_fanout() -> None:
    bus = EventBus()
    job_id = "fanout"
    a_events: list[str] = []
    b_events: list[str] = []

    async def sub(out: list[str]):
        async for evt in bus.subscribe(job_id):
            out.append(evt.event)

    task_a = asyncio.create_task(sub(a_events))
    task_b = asyncio.create_task(sub(b_events))
    await asyncio.sleep(0)
    # Both subscribers should have registered now.
    assert bus.subscriber_count(job_id) == 2

    await bus.publish(SyncEvent(event="sync.started", data={}, job_id=job_id))
    await bus.publish(SyncEvent(event="sync.completed", data={}, job_id=job_id))
    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
    assert a_events == ["sync.started", "sync.completed"]
    assert b_events == ["sync.started", "sync.completed"]


@pytest.mark.asyncio
async def test_events_for_other_jobs_isolated() -> None:
    bus = EventBus()
    job_a_events: list[str] = []
    job_b_events: list[str] = []

    async def sub(job_id: str, out: list[str]):
        async for evt in bus.subscribe(job_id):
            out.append(evt.event)

    task_a = asyncio.create_task(sub("a", job_a_events))
    task_b = asyncio.create_task(sub("b", job_b_events))
    await asyncio.sleep(0)

    await bus.publish(SyncEvent(event="sync.started", data={}, job_id="a"))
    await bus.publish(SyncEvent(event="sync.transition", data={}, job_id="b"))
    await bus.publish(SyncEvent(event="sync.completed", data={}, job_id="a"))
    await bus.publish(SyncEvent(event="sync.completed", data={}, job_id="b"))

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
    assert job_a_events == ["sync.started", "sync.completed"]
    assert job_b_events == ["sync.transition", "sync.completed"]


@pytest.mark.asyncio
async def test_late_subscriber_to_terminated_job_returns_empty() -> None:
    bus = EventBus()
    await bus.publish(SyncEvent(event="sync.completed", data={}, job_id="ghost"))

    received: list[SyncEvent] = []
    async for evt in bus.subscribe("ghost"):
        received.append(evt)
    assert received == []
