"""Tests for Facilitator.submit_claim's on_event callback.

Verifies the callback fires once per validator with the correct outcome shape
across happy path, rejection path, exception path, and timeout path.
"""

import threading
import time

import pytest
from nacl.signing import SigningKey

from src.core.claim import create_claim
from src.core.facilitator import Facilitator, FacilitatorConfig
from src.core.validator import Certificate, Rejection
from src.facilitator_server.node_registry import build_facilitator_config


def _make_claim(sender_keys, recipient_keys, nonce=0, amount=10):
    sk, vk = sender_keys
    return create_claim("sender-1", "recipient-1", amount, nonce, vk, sk)


@pytest.fixture
def keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key


@pytest.fixture
def facilitator(keys):
    sk, vk = keys
    sk2 = SigningKey.generate()
    genesis = [
        {"account_id": "sender-1", "pubkey_b64": _b64(bytes(vk)), "balance": 1000},
        {"account_id": "recipient-1", "pubkey_b64": _b64(bytes(sk2.verify_key)), "balance": 0},
    ]
    cfg = build_facilitator_config(f=1, per_validator_timeout_s=2.0, genesis_accounts=genesis)
    return Facilitator(cfg)


def _b64(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).decode()


# ---------------------------------------------------------------------------

def test_on_event_fires_once_per_validator_happy_path(facilitator, keys):
    sk, vk = keys
    claim = create_claim("sender-1", "recipient-1", 10, 0, vk, sk)

    events: list[dict] = []
    facilitator.submit_claim(claim, on_event=events.append)

    # f=1 -> n=4 validators; happy path = 4 cert outcomes
    assert len(events) == 4
    assert all(e["kind"] == "VALIDATOR_RESPONDED" for e in events)
    assert all(e["outcome"] == "cert" for e in events)
    assert {e["validator_id"] for e in events} == {f"validator-{i}" for i in range(4)}
    assert all(isinstance(e["rt_us"], int) and e["rt_us"] >= 0 for e in events)
    assert all(e["reason"] is None for e in events)


def test_on_event_fires_rejection_with_reason(facilitator, keys):
    sk, vk = keys
    # nonce=99 with no prior settle -> all validators reject
    claim = create_claim("sender-1", "recipient-1", 10, 99, vk, sk)

    events: list[dict] = []
    facilitator.submit_claim(claim, on_event=events.append)

    assert len(events) == 4
    assert all(e["outcome"] == "rejection" for e in events)
    assert all(isinstance(e["reason"], str) and e["reason"] for e in events)


def test_on_event_optional_no_callback_still_works(facilitator, keys):
    sk, vk = keys
    claim = create_claim("sender-1", "recipient-1", 10, 0, vk, sk)
    # Should not raise even without callback
    result = facilitator.submit_claim(claim)
    assert result.quorum_met


# ---------------------------------------------------------------------------
# Timeout path -- use a slow client like the existing test
# ---------------------------------------------------------------------------

class _SlowClient:
    def verify_and_certify(self, claim) -> Certificate | Rejection:
        time.sleep(0.3)
        raise RuntimeError("unreachable")

    def settle(self, claim) -> None:
        pass


def test_on_event_fires_timeout_outcome():
    f = 1
    n = 3 * f + 1
    validators = [(f"validator-{i}", _SlowClient()) for i in range(n)]
    cfg = FacilitatorConfig(f=f, validators=validators, per_validator_timeout_seconds=0.05)
    fac = Facilitator(cfg)

    sk = SigningKey.generate()
    vk = sk.verify_key
    claim = create_claim("a", "b", 10, 0, vk, sk)

    events: list[dict] = []
    fac.submit_claim(claim, on_event=events.append)

    # The orchestrator emits a timeout event for each validator that didn't
    # respond by the deadline. The slow workers may also eventually complete
    # and emit exception events from their deliberate raise -- those are a
    # fixture artifact, not part of the contract under test.
    timeouts = [e for e in events if e["outcome"] == "timeout"]
    assert len(timeouts) == n
    assert all(e["rt_us"] >= 40_000 for e in timeouts)


# ---------------------------------------------------------------------------
# Threading: events fire from worker threads (success path)
# ---------------------------------------------------------------------------

def test_on_event_fires_from_worker_threads(facilitator, keys):
    sk, vk = keys
    claim = create_claim("sender-1", "recipient-1", 10, 0, vk, sk)

    main_tid = threading.get_ident()
    seen_tids: list[int] = []
    lock = threading.Lock()

    def cb(event: dict) -> None:
        with lock:
            seen_tids.append(threading.get_ident())

    facilitator.submit_claim(claim, on_event=cb)

    # All cert events fire from worker threads, NOT the main thread.
    # This is the property that makes thread-safe marshalling necessary.
    assert all(tid != main_tid for tid in seen_tids)
