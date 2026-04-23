"""Tests for the API Server HTTP layer (GET /resource, GET /health)."""

import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src.api_server.main import create_app
from src.core.claim import create_claim


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


def _make_claim_headers(claim, sig_override: bytes | None = None) -> dict[str, str]:
    """Encode a Claim into the two x402 payment headers."""
    claim_fields = {
        "sender": claim.sender,
        "recipient": claim.recipient,
        "amount": claim.amount,
        "nonce": claim.nonce,
        "sender_pubkey": _b64(bytes(claim.sender_pubkey)),
    }
    sig_bytes = sig_override if sig_override is not None else claim.signature
    return {
        "X-Payment-Claim": base64.urlsafe_b64encode(json.dumps(claim_fields).encode()).decode(),
        "X-Payment-Signature": _b64(sig_bytes),
    }


# ---------------------------------------------------------------------------
# Mock transport — intercepts all outbound httpx requests
# ---------------------------------------------------------------------------

class _MockFacilitatorTransport(httpx.AsyncBaseTransport):
    def __init__(self, response_json: dict, status_code: int = 200) -> None:
        self._response_json = response_json
        self._status_code = status_code

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self._status_code, json=self._response_json, request=request)


def _quorum_response(met: bool, success_count: int = 3) -> dict:
    return {
        "quorum_met": met,
        "success_count": success_count if met else 0,
        "certificates": {},
        "rejections": {} if met else {"validator-0": "nonce mismatch"},
        "dead": [],
        "faults": [],
    }


def _make_client(facilitator_response: dict, facilitator_status: int = 200) -> TestClient:
    transport = _MockFacilitatorTransport(facilitator_response, facilitator_status)
    mock_http = httpx.AsyncClient(transport=transport)
    app = create_app(http_client=mock_http)
    # Pre-seed state so the route can access http_client without requiring the
    # lifespan context manager to run (which only fires inside `with TestClient`).
    app.state.http_client = mock_http
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sender_keys():
    sk = SigningKey.generate()
    return sk, sk.verify_key


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health():
    client = _make_client(_quorum_response(True))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# 402 on no payment headers
# ---------------------------------------------------------------------------

def test_no_headers_returns_402():
    client = _make_client(_quorum_response(True))
    resp = client.get("/resource")
    assert resp.status_code == 402
    body = resp.json()
    assert body["payment_required"] is True
    assert body["scheme"] == "fastset-ed25519"
    assert "X-Payment-Version" in resp.headers
    assert "X-Payment-Payload-Hash" in resp.headers  # payload hash advertised


def test_missing_signature_header_returns_402(sender_keys):
    sk, vk = sender_keys
    claim = create_claim("agent-1", "server-recipient", 10, 0, vk, sk)
    headers = _make_claim_headers(claim)
    client = _make_client(_quorum_response(True))

    resp = client.get("/resource", headers={"X-Payment-Claim": headers["X-Payment-Claim"]})
    assert resp.status_code == 402


# ---------------------------------------------------------------------------
# 400 on bad signature
# ---------------------------------------------------------------------------

def test_bad_signature_returns_400(sender_keys):
    sk, vk = sender_keys
    claim = create_claim("agent-1", "server-recipient", 10, 0, vk, sk)
    bad_headers = _make_claim_headers(claim, sig_override=b"\xff" * 64)

    client = _make_client(_quorum_response(True))
    resp = client.get("/resource", headers=bad_headers)
    assert resp.status_code == 400
    assert "signature" in resp.json()["error"].lower()


# ---------------------------------------------------------------------------
# 400 on wrong recipient
# ---------------------------------------------------------------------------

def test_wrong_recipient_returns_400(sender_keys):
    sk, vk = sender_keys
    # Route's PAYMENT_RECIPIENT default is "server-recipient"; use something else
    claim = create_claim("agent-1", "wrong-recipient", 10, 0, vk, sk)
    headers = _make_claim_headers(claim)

    client = _make_client(_quorum_response(True))
    resp = client.get("/resource", headers=headers)
    assert resp.status_code == 400
    assert "recipient" in resp.json()["error"].lower()


# ---------------------------------------------------------------------------
# 200 on valid flow (mock facilitator returns quorum_met=True)
# ---------------------------------------------------------------------------

def test_valid_payment_returns_200(sender_keys):
    sk, vk = sender_keys
    claim = create_claim("agent-1", "server-recipient", 10, 0, vk, sk)
    headers = _make_claim_headers(claim)

    client = _make_client(_quorum_response(True))
    resp = client.get("/resource", headers=headers)

    assert resp.status_code == 200
    assert resp.headers.get("X-Payment-Settled") == "true"
    assert "data" in resp.json()


# ---------------------------------------------------------------------------
# 402 when facilitator says quorum not met
# ---------------------------------------------------------------------------

def test_quorum_not_met_returns_402(sender_keys):
    sk, vk = sender_keys
    claim = create_claim("agent-1", "server-recipient", 10, 0, vk, sk)
    headers = _make_claim_headers(claim)

    client = _make_client(_quorum_response(False))
    resp = client.get("/resource", headers=headers)
    assert resp.status_code == 402
    assert "Quorum not reached" in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# 503 when facilitator is unreachable
# ---------------------------------------------------------------------------

class _ConnectErrorTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)


def test_facilitator_unreachable_returns_503(sender_keys):
    sk, vk = sender_keys
    claim = create_claim("agent-1", "server-recipient", 10, 0, vk, sk)
    headers = _make_claim_headers(claim)

    mock_http = httpx.AsyncClient(transport=_ConnectErrorTransport())
    app = create_app(http_client=mock_http)
    with TestClient(app) as client:
        resp = client.get("/resource", headers=headers)

    assert resp.status_code == 503
    assert "unavailable" in resp.json()["error"].lower()
