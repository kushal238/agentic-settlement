"""Tests for the bootstrap endpoints used by the agent CLI:

  POST /debug/register-account
  GET  /account/{account_id}

These let an external client (with a self-generated keypair) join the system
without restarting servers, and let it discover its current nonce so it can
build claims that aren't immediately rejected.
"""

import base64

import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src.core.claim import create_claim
from src.facilitator_server.main import create_app
from src.facilitator_server.node_registry import build_facilitator_config


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


@pytest.fixture
def app():
    sk = SigningKey.generate()
    sk2 = SigningKey.generate()
    genesis = [
        {"account_id": "sender-1", "pubkey_b64": _b64(bytes(sk.verify_key)), "balance": 1000},
        {"account_id": "recipient-1", "pubkey_b64": _b64(bytes(sk2.verify_key)), "balance": 0},
    ]
    cfg, debug_registry = build_facilitator_config(
        f=1, per_validator_timeout_s=2.0, genesis_accounts=genesis
    )
    from src.core.facilitator import Facilitator
    return create_app(facilitator=Facilitator(cfg))


def _attach_debug_registry_via_lifespan():
    """create_app with an injected facilitator currently sets debug_validators
    to {} (only the genesis-loading branch builds it). These tests need the
    registry, so they build a fresh app whose lifespan loads from
    GENESIS_ACCOUNTS_PATH and populates debug_validators."""
    return create_app()


# ---------------------------------------------------------------------------
# GET /account
# ---------------------------------------------------------------------------

def test_get_account_returns_genesis_account_state(monkeypatch):
    """Genesis-loaded accounts are visible via GET /account.

    GENESIS_ACCOUNTS_PATH defaults to unset in tests (so lifespan creates an
    empty validator set), so we point it at the repo's genesis.json for this
    test specifically.
    """
    monkeypatch.setenv("GENESIS_ACCOUNTS_PATH", "genesis.json")
    # config caches at import time -- reload to pick up the env var.
    import importlib
    from src.facilitator_server import config as _cfg
    importlib.reload(_cfg)
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        resp = client.get("/account/agent-1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["account_id"] == "agent-1"
    assert body["balance"] == 10000  # from repo's genesis.json
    assert body["nonce"] == 0
    assert isinstance(body["pubkey_b64"], str)


def test_get_account_returns_404_for_unknown():
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        resp = client.get("/account/never-existed")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /debug/register-account
# ---------------------------------------------------------------------------

def test_register_account_creates_new():
    sk = SigningKey.generate()
    pk_b64 = _b64(bytes(sk.verify_key))
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        resp = client.post("/debug/register-account", json={
            "account_id": "fresh-agent",
            "pubkey_b64": pk_b64,
            "balance": 500,
        })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == {
        "account_id": "fresh-agent",
        "pubkey_b64": pk_b64,
        "balance": 500,
        "nonce": 0,
    }


def test_register_account_visible_via_get_immediately():
    """After registration, GET /account returns the new account's state."""
    sk = SigningKey.generate()
    pk_b64 = _b64(bytes(sk.verify_key))
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        client.post("/debug/register-account", json={
            "account_id": "fresh-agent-2",
            "pubkey_b64": pk_b64,
            "balance": 250,
        })
        resp = client.get("/account/fresh-agent-2")
    assert resp.status_code == 200
    assert resp.json()["balance"] == 250


def test_register_account_idempotent_on_same_pubkey():
    """Re-registering with the same pubkey returns 201 with the existing state.
    The balance from the second call is ignored -- this is a bootstrap, not a
    faucet."""
    sk = SigningKey.generate()
    pk_b64 = _b64(bytes(sk.verify_key))
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        first = client.post("/debug/register-account", json={
            "account_id": "idempotent-agent",
            "pubkey_b64": pk_b64,
            "balance": 100,
        })
        second = client.post("/debug/register-account", json={
            "account_id": "idempotent-agent",
            "pubkey_b64": pk_b64,
            "balance": 9999,  # ignored
        })
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["balance"] == 100  # not 9999


def test_register_account_conflict_on_different_pubkey():
    sk1 = SigningKey.generate()
    sk2 = SigningKey.generate()
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        first = client.post("/debug/register-account", json={
            "account_id": "conflict-agent",
            "pubkey_b64": _b64(bytes(sk1.verify_key)),
            "balance": 100,
        })
        second = client.post("/debug/register-account", json={
            "account_id": "conflict-agent",
            "pubkey_b64": _b64(bytes(sk2.verify_key)),
            "balance": 100,
        })
    assert first.status_code == 201
    assert second.status_code == 409


def test_register_account_rejects_invalid_pubkey():
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        resp = client.post("/debug/register-account", json={
            "account_id": "bad-key-agent",
            "pubkey_b64": "not-base64-and-not-32-bytes",
            "balance": 0,
        })
    assert resp.status_code == 400


def test_register_account_rejects_negative_balance():
    sk = SigningKey.generate()
    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        resp = client.post("/debug/register-account", json={
            "account_id": "neg-balance-agent",
            "pubkey_b64": _b64(bytes(sk.verify_key)),
            "balance": -1,
        })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Integration: register, settle, observe nonce increment
# ---------------------------------------------------------------------------

def test_register_then_settle_then_get_account_shows_nonce_incremented():
    """Full bootstrap path: agent generates a key, registers, settles a claim,
    then reads back the account and sees nonce=1."""
    sender_sk = SigningKey.generate()
    pk_b64 = _b64(bytes(sender_sk.verify_key))
    recipient_sk = SigningKey.generate()
    rcpt_pk_b64 = _b64(bytes(recipient_sk.verify_key))

    app = _attach_debug_registry_via_lifespan()
    with TestClient(app) as client:
        # Bootstrap both sides
        client.post("/debug/register-account", json={
            "account_id": "alice", "pubkey_b64": pk_b64, "balance": 100,
        })
        client.post("/debug/register-account", json={
            "account_id": "bob", "pubkey_b64": rcpt_pk_b64, "balance": 0,
        })

        # Discover current nonce (should be 0)
        before = client.get("/account/alice").json()
        assert before["nonce"] == 0

        # Build and settle a claim using that nonce
        claim = create_claim("alice", "bob", 10, before["nonce"], sender_sk.verify_key, sender_sk)
        settle_resp = client.post("/settle", json={
            "sender": claim.sender,
            "recipient": claim.recipient,
            "amount": claim.amount,
            "nonce": claim.nonce,
            "sender_pubkey": _b64(bytes(claim.sender_pubkey)),
            "signature": _b64(claim.signature),
        })
        assert settle_resp.status_code == 200
        assert settle_resp.json()["quorum_met"] is True

        # The settle background task runs after the response. Poll briefly for nonce update.
        import time
        for _ in range(20):
            after = client.get("/account/alice").json()
            if after["nonce"] == 1:
                break
            time.sleep(0.05)

    assert after["nonce"] == 1
    assert after["balance"] == 90
