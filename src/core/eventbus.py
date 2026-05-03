"""Tiny async pub/sub for in-process structured event streaming.

Used by api_server and facilitator_server to emit observable events that
subscribers (e.g. the observer CLI consuming /events SSE) can read without
coupling to internal state.

Producers call publish() synchronously. Slow subscribers do NOT block the
producer: when a subscriber's queue is full, the oldest event is dropped to
make room for the new one and the subscription's `dropped` counter is
incremented so consumers can detect backpressure honestly.

Threading: asyncio.Queue is not thread-safe. Producers running in worker
threads (e.g. Facilitator's validator fan-out) MUST go through
make_threadsafe_publisher(loop), which marshals publish() back onto the loop
thread via loop.call_soon_threadsafe.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Callable


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[dict]
    dropped: int = 0


class EventBus:
    def __init__(self, queue_maxsize: int = 256) -> None:
        self._subs: set[Subscription] = set()
        self._queue_maxsize = queue_maxsize

    def publish(self, event: dict) -> None:
        for sub in list(self._subs):
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    sub.queue.get_nowait()
                    sub.dropped += 1
                except asyncio.QueueEmpty:
                    pass
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    def make_threadsafe_publisher(
        self, loop: asyncio.AbstractEventLoop
    ) -> Callable[[dict], None]:
        return lambda event: loop.call_soon_threadsafe(self.publish, event)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[Subscription]:
        sub = Subscription(queue=asyncio.Queue(maxsize=self._queue_maxsize))
        self._subs.add(sub)
        try:
            yield sub
        finally:
            self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
