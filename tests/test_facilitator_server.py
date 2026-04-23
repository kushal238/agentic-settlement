"""Tests for the Facilitator Server HTTP layer (POST /settle, GET /health)."""

import base64

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src.core.claim import create_claim
from src.core.facilitator import Facilitator
from src.core.quorum_proof import verify_payment_proof
from src.facilitator_server.main import create_app
from src.facilitator_server.node_registry import build_facilitator_config


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sender_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key


@pytest.fixture(scope="module")
def recipient_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key


@pytest.fixture(scope="module")
def facilitator(sender_keys, recipient_keys):
    _, sender_vk = sender_keys
    _, recipient_vk = recipient_keys
    genesis = [
        {"account_id": "sender-1", "pubkey_b64": _b64(bytes(sender_vk)), "balance": 1000},
        {"account_id": "recipient-1", "pubkey_b64": _b64(bytes(recipient_vk)), "balance": 0},
    ]
    cfg = build_facilitator_config(f=1, per_validator_timeout_s=2.0, genesis_accounts=genesis)
    return Facilitator(cfg)


@pytest.fixture(scope="module")
def client(facilitator):
    app = create_app(facilitator=facilitator)
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_settle_happy_path(client, sender_keys, recipient_keys):
    sk, vk = sender_keys
    claim = create_claim("sender-1", "recipient-1", 10, 0, vk, sk)

    resp = client.post("/settle", json={
        "sender": claim.sender,
        "recipient": claim.recipient,
        "amount": claim.amount,
        "nonce": claim.nonce,
        "sender_pubkey": _b64(bytes(claim.sender_pubkey)),
        "signature": _b64(claim.signature),
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["quorum_met"] is True
    assert data["success_count"] >= 3  # 2f+1 with f=1
    assert data["payment_proof"] is not None
    valid, detail = verify_payment_proof(data["payment_proof"], f=1)
    assert valid, detail


# ---------------------------------------------------------------------------
# Bad-signature → 400
# ---------------------------------------------------------------------------

def test_settle_invalid_signature(client, sender_keys):
    sk, vk = sender_keys
    claim = create_claim("sender-1", "recipient-1", 10, 0, vk, sk)

    resp = client.post("/settle", json={
        "sender": claim.sender,
        "recipient": claim.recipient,
        "amount": claim.amount,
        "nonce": claim.nonce,
        "sender_pubkey": _b64(bytes(claim.sender_pubkey)),
        "signature": _b64(b"\x00" * 64),  # garbage signature
    })

    assert resp.status_code == 400
    assert "signature" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Quorum not met (wrong nonce → all validators reject)
# ---------------------------------------------------------------------------

def test_settle_quorum_not_met_wrong_nonce(client, sender_keys):
    sk, vk = sender_keys
    # nonce=99 but expected nonce is 0 (or 1 after the happy-path test)
    claim = create_claim("sender-1", "recipient-1", 10, 99, vk, sk)

    resp = client.post("/settle", json={
        "sender": claim.sender,
        "recipient": claim.recipient,
        "amount": claim.amount,
        "nonce": claim.nonce,
        "sender_pubkey": _b64(bytes(claim.sender_pubkey)),
        "signature": _b64(claim.signature),
    })

    assert resp.status_code == 200  # HTTP succeeded; settlement did not
    data = resp.json()
    assert data["quorum_met"] is False
    assert data["success_count"] == 0
    assert data["payment_proof"] is None


# ---------------------------------------------------------------------------
# Timeout path — use a slow client that sleeps longer than the timeout
# ---------------------------------------------------------------------------

import time
from src.core.facilitator import FacilitatorConfig
from src.core.validator import Certificate, Rejection


class _SlowValidatorClient:
    """ValidatorClient that always sleeps well past the per-validator timeout."""

    def verify_and_certify(self, claim) -> Certificate | Rejection:
        time.sleep(0.3)
        raise RuntimeError("unreachable")  # should time out before here

    def settle(self, claim) -> None:
        pass


def test_settle_timeout_treated_as_dead_validators():
    """Validators that exceed per_validator_timeout_seconds count as dead → no quorum."""
    sk = SigningKey.generate()
    vk = sk.verify_key

    f = 1
    n = 3 * f + 1
    validators = [(f"validator-{i}", _SlowValidatorClient()) for i in range(n)]
    cfg = FacilitatorConfig(f=f, validators=validators, per_validator_timeout_seconds=0.05)
    fac = Facilitator(cfg)
    app = create_app(facilitator=fac)

    claim = create_claim("a", "b", 10, 0, vk, sk)

    with TestClient(app) as c:
        resp = c.post("/settle", json={
            "sender": claim.sender,
            "recipient": claim.recipient,
            "amount": claim.amount,
            "nonce": claim.nonce,
            "sender_pubkey": _b64(bytes(claim.sender_pubkey)),
            "signature": _b64(claim.signature),
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["quorum_met"] is False
    assert data["success_count"] == 0
