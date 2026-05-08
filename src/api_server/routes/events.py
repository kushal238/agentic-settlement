"""GET /events -- Server-Sent Events stream of structured api_server events.

Mirrors the facilitator's /events endpoint (same wire format, same heartbeat
behavior, same disconnect handling). Kept as a sibling module rather than
shared code so each server's SSE behavior can evolve independently -- the
shared abstraction lives one level down at EventBus.

The generator function `sse_event_stream` is exposed separately from the
route handler so it can be unit-tested without going through HTTP --
httpx.ASGITransport buffers the full response body before returning, which
makes in-process testing of streaming responses impossible.
"""

import asyncio
import json
from typing import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.core.eventbus import EventBus

router = APIRouter()

HEARTBEAT_INTERVAL_S = 15.0


async def sse_event_stream(
    bus: EventBus,
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat_interval_s: float = HEARTBEAT_INTERVAL_S,
) -> AsyncIterator[str]:
    """Yield SSE-formatted strings: data frames for events, comment frames for heartbeats."""
    async with bus.subscribe() as sub:
        while True:
            if await is_disconnected():
                return
            try:
                event = await asyncio.wait_for(
                    sub.queue.get(), timeout=heartbeat_interval_s
                )
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    bus: EventBus = request.app.state.event_bus

    return StreamingResponse(
        sse_event_stream(bus, request.is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
