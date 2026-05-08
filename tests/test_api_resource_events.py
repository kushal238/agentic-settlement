"""End-to-end tests of /resource event emission.

Covers each branch of the route -- no proof header, malformed proof, invalid
proof signatures, wrong recipient, insufficient amount, happy path -- and
asserts the expected event sequence with consistent request_id.

Bridging detail: TestClient runs the FastAPI app in its own thread with its
own event loop. Subscribers must run on that loop (where the bus lives) but
be observable from the test thread, so we schedule them via
asyncio.run_coroutine_threadsafe and read the result from a Future.
"""

import asyncio
import base64
import json
import time

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src.api_server.events import (
    PROOF_RECEIVED,
    PROOF_REJECTED,
    PROOF_VERIFIED,
    REQUIREMENTS_ISSUED,
    RESOURCE_RELEASED,
    RESOURCE_REQUESTED,
)
from src.api_server.main import create_app
from src.core.account import AccountStateStore
from src.core.claim import create_claim
from src.core.eventbus import EventBus
from src.core.facilitator import FacilitatorResult
from src.core.quorum_proof import build_payment_proof
from src.core.validator import Certificate, Validator


def _proof_header(proof: dict) -> dict[str, str]:
    encoded = base64.urlsafe_b64encode(json.dumps(proof).encode()).decode()
    return {"X-Payment-Proof": encoded}


def _valid_payment_proof(amount: int = 10, recipient: str = "server-recipient") -> dict:
    sender_sk = SigningKey.generate()
    sender_vk = sender_sk.verify_key
    recipient_sk = SigningKey.generate()
    recipient_vk = recipient_sk.verify_key
    claim = create_claim("agent-1", recipient, amount, 0, sender_vk, sender_sk)

    validators: list[Validator] = []
    for i in range(4):
        st = AccountStateStore()
        st.create_account("agent-1", sender_vk, balance=100)
        st.create_account(recipient, recipient_vk, balance=0)
        validators.append(Validator(f"V{i+1}", st))

    certificates = {}
    for validator in validators[:3]:
        cert = validator.verify_and_certify(claim)
        assert isinstance(cert, Certificate)
        certificates[validator.validator_id] = cert

    result = FacilitatorResult(
        claim=claim,
        quorum_met=True,
        success_count=len(certificates),
        certificates=certificates,
        rejections={},
        dead=set(),
        faults=[],
    )
    return build_payment_proof(result, f=1)


def _collect_events(bus: EventBus, n: int):
    """Coroutine factory: subscribe and return up to n events, with a per-get
    timeout so the test fails fast if the route doesn't emit what we expect.
    """
    async def _impl():
        events = []
        async with bus.subscribe() as sub:
            try:
                while len(events) < n:
                    events.append(await asyncio.wait_for(sub.queue.get(), timeout=2.0))
            except asyncio.TimeoutError:
                pass
        return events
    return _impl()


def _drive_and_collect(make_request, expected_n: int):
    """Run a request via TestClient and collect expected_n events from the bus.

    `make_request(client) -> Response` is called with a TestClient that has
    its lifespan triggered. Returns (response, events).
    """
    app = create_app()
    with TestClient(app) as client:
        bus: EventBus = app.state.event_bus
        loop: asyncio.AbstractEventLoop = app.state.event_loop
        future = asyncio.run_coroutine_threadsafe(_collect_events(bus, expected_n), loop)
        # Let the subscriber register before triggering events.
        time.sleep(0.05)
        resp = make_request(client)
        events = future.result(timeout=5.0)
    return resp, events


def _assert_consistent_metadata(events: list[dict]) -> str:
    """Each event has request_id (all equal) and ts_mono_ns (int). Returns the request_id."""
    request_ids = {e.get("request_id") for e in events}
    assert len(request_ids) == 1, f"events span multiple request_ids: {request_ids}"
    request_id = request_ids.pop()
    assert request_id is not None
    assert all(isinstance(e.get("ts_mono_ns"), int) for e in events)
    return request_id


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------

def test_no_proof_header_emits_requirements_issued():
    resp, events = _drive_and_collect(lambda c: c.get("/resource"), expected_n=2)
    assert resp.status_code == 402
    _assert_consistent_metadata(events)
    kinds = [e["kind"] for e in events]
    assert kinds == [RESOURCE_REQUESTED, REQUIREMENTS_ISSUED]
    assert events[0]["has_proof_header"] is False
    assert events[1]["reason"] == "no_proof_header"


def test_malformed_proof_emits_proof_rejected():
    resp, events = _drive_and_collect(
        lambda c: c.get("/resource", headers={"X-Payment-Proof": "not-base64-json"}),
        expected_n=3,
    )
    assert resp.status_code == 400
    _assert_consistent_metadata(events)
    kinds = [e["kind"] for e in events]
    assert kinds == [RESOURCE_REQUESTED, PROOF_RECEIVED, PROOF_REJECTED]
    assert events[0]["has_proof_header"] is True
    rejected = events[2]
    assert rejected["reason"] == "malformed"
    assert "detail" in rejected


def test_invalid_proof_signature_emits_proof_rejected_and_requirements_issued():
    proof = _valid_payment_proof()
    first_vid = next(iter(proof["certificates"].keys()))
    proof["certificates"][first_vid]["validator_signature"] = base64.urlsafe_b64encode(b"\x00" * 64).decode()
    resp, events = _drive_and_collect(
        lambda c: c.get("/resource", headers=_proof_header(proof)),
        expected_n=4,
    )
    assert resp.status_code == 402
    _assert_consistent_metadata(events)
    kinds = [e["kind"] for e in events]
    assert kinds == [RESOURCE_REQUESTED, PROOF_RECEIVED, PROOF_REJECTED, REQUIREMENTS_ISSUED]
    assert events[2]["reason"] == "invalid_proof"
    assert events[3]["reason"] == "invalid_proof"


def test_wrong_recipient_emits_proof_rejected_and_requirements_issued():
    proof = _valid_payment_proof(recipient="wrong-recipient")
    resp, events = _drive_and_collect(
        lambda c: c.get("/resource", headers=_proof_header(proof)),
        expected_n=4,
    )
    assert resp.status_code == 402
    _assert_consistent_metadata(events)
    kinds = [e["kind"] for e in events]
    assert kinds == [RESOURCE_REQUESTED, PROOF_RECEIVED, PROOF_REJECTED, REQUIREMENTS_ISSUED]
    rejected = events[2]
    assert rejected["reason"] == "wrong_recipient"
    assert rejected["expected"] == "server-recipient"
    assert rejected["got"] == "wrong-recipient"


def test_insufficient_amount_emits_proof_rejected():
    proof = _valid_payment_proof(amount=1)  # PAYMENT_AMOUNT defaults to 10
    resp, events = _drive_and_collect(
        lambda c: c.get("/resource", headers=_proof_header(proof)),
        expected_n=4,
    )
    assert resp.status_code == 402
    _assert_consistent_metadata(events)
    kinds = [e["kind"] for e in events]
    assert kinds == [RESOURCE_REQUESTED, PROOF_RECEIVED, PROOF_REJECTED, REQUIREMENTS_ISSUED]
    rejected = events[2]
    assert rejected["reason"] == "insufficient_amount"
    assert rejected["minimum"] == 10
    assert rejected["got"] == 1


def test_happy_path_emits_full_sequence():
    proof = _valid_payment_proof()
    resp, events = _drive_and_collect(
        lambda c: c.get("/resource", headers=_proof_header(proof)),
        expected_n=4,
    )
    assert resp.status_code == 200
    _assert_consistent_metadata(events)
    kinds = [e["kind"] for e in events]
    assert kinds == [RESOURCE_REQUESTED, PROOF_RECEIVED, PROOF_VERIFIED, RESOURCE_RELEASED]
    verified = events[2]
    assert verified["sender"] == "agent-1"
    assert verified["recipient"] == "server-recipient"
    assert verified["amount"] == 10
    assert verified["quorum_size"] == 3
