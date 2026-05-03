"""Tests for src.core.eventbus.EventBus."""

import asyncio
import threading

import pytest

from src.core.eventbus import EventBus


@pytest.mark.asyncio
async def test_publish_without_subscribers_is_noop():
    bus = EventBus()
    bus.publish({"kind": "X"})  # should not raise


@pytest.mark.asyncio
async def test_single_subscriber_receives_events_in_order():
    bus = EventBus()
    received: list[dict] = []
    async with bus.subscribe() as sub:
        bus.publish({"kind": "A", "i": 1})
        bus.publish({"kind": "B", "i": 2})
        for _ in range(2):
            received.append(await asyncio.wait_for(sub.queue.get(), timeout=1.0))
    assert received == [{"kind": "A", "i": 1}, {"kind": "B", "i": 2}]
    assert sub.dropped == 0


@pytest.mark.asyncio
async def test_multiple_subscribers_each_get_every_event():
    bus = EventBus()
    async with bus.subscribe() as s1, bus.subscribe() as s2:
        bus.publish({"kind": "X"})
        e1 = await asyncio.wait_for(s1.queue.get(), timeout=1.0)
        e2 = await asyncio.wait_for(s2.queue.get(), timeout=1.0)
    assert e1 == {"kind": "X"}
    assert e2 == {"kind": "X"}


@pytest.mark.asyncio
async def test_subscriber_removed_on_context_exit():
    bus = EventBus()
    async with bus.subscribe():
        assert bus.subscriber_count == 1
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_slow_subscriber_drops_oldest_and_increments_counter():
    bus = EventBus(queue_maxsize=2)
    async with bus.subscribe() as sub:
        bus.publish({"kind": "A"})
        bus.publish({"kind": "B"})
        bus.publish({"kind": "C"})  # forces drop of oldest

        drained: list[dict] = []
        while not sub.queue.empty():
            drained.append(sub.queue.get_nowait())

    kinds = [e["kind"] for e in drained]
    assert kinds == ["B", "C"]
    assert sub.dropped == 1


@pytest.mark.asyncio
async def test_threadsafe_publisher_marshals_to_loop():
    bus = EventBus()
    loop = asyncio.get_running_loop()
    publish = bus.make_threadsafe_publisher(loop)

    async with bus.subscribe() as sub:
        def worker():
            publish({"kind": "FROM_THREAD", "tid": threading.get_ident()})

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)

    assert event["kind"] == "FROM_THREAD"
    assert event["tid"] != threading.get_ident()
