"""End-to-end test of /settle event emission.

Subscribes to the bus while driving /settle via TestClient, then asserts the
full lifecycle event sequence arrives with consistent request_id and the
right payload shape.

Bridging detail: TestClient runs the FastAPI app in a separate thread with
its own event loop. Our subscriber must run on that same loop (where the
bus lives) but be observable from the test thread, so we schedule it via
asyncio.run_coroutine_threadsafe and read the result from a Future.
"""

import asyncio
import base64
import time

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src.core.claim import create_claim
from src.core.eventbus import EventBus
from src.core.facilitator import Facilitator
from src.facilitator_server.events import (
    CLAIM_VERIFIED,
    FANOUT_STARTED,
    PROOF_ASSEMBLED,
    QUORUM_EVALUATED,
    SETTLE_BACKGROUND_DONE,
    SETTLE_RECEIVED,
    VALIDATOR_RESPONDED,
)
from src.facilitator_server.main import create_app
from src.facilitator_server.node_registry import build_facilitator_config


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


@pytest.fixture
def keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key


@pytest.fixture
def app(keys):
    sk, vk = keys
    sk2 = SigningKey.generate()
    genesis = [
        {"account_id": "sender-1", "pubkey_b64": _b64(bytes(vk)), "balance": 1000},
        {"account_id": "recipient-1", "pubkey_b64": _b64(bytes(sk2.verify_key)), "balance": 0},
    ]
    cfg, _ = build_facilitator_config(f=1, per_validator_timeout_s=2.0, genesis_accounts=genesis)
    return create_app(facilitator=Facilitator(cfg))


def _collect_events(bus: EventBus, n: int):
    """Coroutine factory: subscribe to bus, return up to n events.

    Returned coroutine is intended to be scheduled on the app's loop via
    asyncio.run_coroutine_threadsafe so the test thread can wait for the
    result via the returned concurrent.futures.Future.
    """
    async def _impl():
        events = []
        async with bus.subscribe() as sub:
            try:
                while len(events) < n:
                    events.append(await asyncio.wait_for(sub.queue.get(), timeout=5.0))
            except asyncio.TimeoutError:
                pass
        return events
    return _impl()


def test_settle_happy_path_emits_full_event_sequence(app, keys):
    sk, vk = keys
    claim = create_claim("sender-1", "recipient-1", 10, 0, vk, sk)

    with TestClient(app) as client:
        bus: EventBus = app.state.event_bus
        loop: asyncio.AbstractEventLoop = app.state.event_loop

        # f=1 -> n=4 validators -> 4 VALIDATOR_RESPONDED events.
        # Lifecycle: SETTLE_RECEIVED, CLAIM_VERIFIED, FANOUT_STARTED,
        # QUORUM_EVALUATED, PROOF_ASSEMBLED, SETTLE_BACKGROUND_DONE = 6.
        # Total = 10.
        future = asyncio.run_coroutine_threadsafe(_collect_events(bus, 10), loop)

        # Give the subscription a moment to register on the app loop before
        # we trigger any events.
        time.sleep(0.05)

        resp = client.post("/settle", json={
            "sender": claim.sender,
            "recipient": claim.recipient,
            "amount": claim.amount,
            "nonce": claim.nonce,
            "sender_pubkey": _b64(bytes(claim.sender_pubkey)),
            "signature": _b64(claim.signature),
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["quorum_met"] is True

        events = future.result(timeout=10.0)

    # Every event must carry request_id and ts_mono_ns.
    request_ids = {e.get("request_id") for e in events}
    assert len(request_ids) == 1, f"events span multiple request_ids: {request_ids}"
    request_id = request_ids.pop()
    assert request_id is not None
    assert all(isinstance(e.get("ts_mono_ns"), int) for e in events)

    # Lifecycle events must appear in this strict order. Per-validator
    # VALIDATOR_RESPONDED events fire from worker threads in arbitrary order,
    # so we filter them out for the order check.
    lifecycle_kinds = [e["kind"] for e in events if e["kind"] != VALIDATOR_RESPONDED]
    assert lifecycle_kinds == [
        SETTLE_RECEIVED,
        CLAIM_VERIFIED,
        FANOUT_STARTED,
        QUORUM_EVALUATED,
        PROOF_ASSEMBLED,
        SETTLE_BACKGROUND_DONE,
    ], lifecycle_kinds

    # f=1 -> n=4 validators -> 4 VALIDATOR_RESPONDED events.
    validator_events = [e for e in events if e["kind"] == VALIDATOR_RESPONDED]
    assert len(validator_events) == 4
    assert {e["validator_id"] for e in validator_events} == {f"validator-{i}" for i in range(4)}
    assert all(e["outcome"] == "cert" for e in validator_events)

    # Spot-check payload shapes.
    settle_received = next(e for e in events if e["kind"] == SETTLE_RECEIVED)
    assert settle_received["claim"] == {
        "sender": "sender-1",
        "recipient": "recipient-1",
        "amount": 10,
        "nonce": 0,
    }

    fanout_started = next(e for e in events if e["kind"] == FANOUT_STARTED)
    assert fanout_started["f"] == 1
    assert fanout_started["n"] == 4
    assert fanout_started["quorum_threshold"] == 3

    quorum_evaluated = next(e for e in events if e["kind"] == QUORUM_EVALUATED)
    assert quorum_evaluated["quorum_met"] is True
    assert quorum_evaluated["success_count"] == 4

    proof_assembled = next(e for e in events if e["kind"] == PROOF_ASSEMBLED)
    assert proof_assembled["signature_count"] == 4
    assert proof_assembled["proof_build_us"] >= 0

    settle_done = next(e for e in events if e["kind"] == SETTLE_BACKGROUND_DONE)
    assert settle_done["signer_ids"] == sorted(f"validator-{i}" for i in range(4))
    assert settle_done["duration_us"] >= 0
