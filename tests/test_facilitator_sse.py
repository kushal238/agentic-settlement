"""Tests for the SSE event stream generator.

We test `sse_event_stream` directly rather than going through the HTTP layer
because httpx's ASGITransport buffers the entire response before returning,
which makes in-process testing of infinite streaming responses impossible.
The HTTP layer is a thin StreamingResponse wrapper -- end-to-end coverage of
that wrapper comes from PR2 (observer CLI hitting a live server).
"""

import asyncio
import json
import threading

import pytest

from src.core.eventbus import EventBus
from src.facilitator_server.routes.events import sse_event_stream


async def _never_disconnected() -> bool:
    return False


@pytest.mark.asyncio
async def test_stream_yields_data_frames_for_published_events():
    bus = EventBus()
    gen = sse_event_stream(bus, _never_disconnected, heartbeat_interval_s=60.0)

    # Drive the generator into its main loop so the subscription registers.
    consumer = asyncio.create_task(gen.__anext__())
    while bus.subscriber_count == 0:
        await asyncio.sleep(0.005)

    bus.publish({"kind": "TEST_A", "n": 1})
    chunk = await asyncio.wait_for(consumer, timeout=1.0)
    assert chunk == 'data: {"kind": "TEST_A", "n": 1}\n\n'

    bus.publish({"kind": "TEST_B"})
    chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert json.loads(chunk[len("data: "):]) == {"kind": "TEST_B"}

    await gen.aclose()


@pytest.mark.asyncio
async def test_stream_emits_heartbeat_when_idle():
    bus = EventBus()
    gen = sse_event_stream(bus, _never_disconnected, heartbeat_interval_s=0.05)

    chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert chunk == ": heartbeat\n\n"

    await gen.aclose()


@pytest.mark.asyncio
async def test_stream_exits_when_disconnected():
    bus = EventBus()
    disconnected = False

    async def is_disconnected() -> bool:
        return disconnected

    gen = sse_event_stream(bus, is_disconnected, heartbeat_interval_s=0.05)

    # First iteration: not disconnected yet -> heartbeat
    chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert chunk == ": heartbeat\n\n"

    disconnected = True
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)

    # Subscription should have been cleaned up by the async-with exit.
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_stream_receives_events_from_threadsafe_publisher():
    """Events published via make_threadsafe_publisher (the path Facilitator
    uses from worker threads) reach the SSE consumer."""
    bus = EventBus()
    loop = asyncio.get_running_loop()
    publish = bus.make_threadsafe_publisher(loop)

    gen = sse_event_stream(bus, _never_disconnected, heartbeat_interval_s=60.0)

    consumer = asyncio.create_task(gen.__anext__())
    while bus.subscriber_count == 0:
        await asyncio.sleep(0.005)

    t = threading.Thread(target=lambda: publish({"kind": "FROM_THREAD"}))
    t.start()
    t.join()

    chunk = await asyncio.wait_for(consumer, timeout=1.0)
    assert json.loads(chunk[len("data: "):]) == {"kind": "FROM_THREAD"}

    await gen.aclose()
