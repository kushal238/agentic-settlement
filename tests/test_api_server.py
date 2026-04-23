"""Tests for the API Server HTTP layer (GET /resource, GET /health)."""

import base64
import json

from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src.api_server.main import create_app
from src.core.account import AccountStateStore
from src.core.claim import create_claim
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


def test_health():
    with TestClient(create_app()) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_no_headers_returns_402():
    with TestClient(create_app()) as client:
        resp = client.get("/resource")
    assert resp.status_code == 402
    body = resp.json()
    assert body["payment_required"] is True
    assert body["scheme"] == "fastset-ed25519"
    assert "X-Payment-Version" in resp.headers
    assert "X-Payment-Payload-Hash" in resp.headers


def test_malformed_proof_returns_400():
    with TestClient(create_app()) as client:
        resp = client.get("/resource", headers={"X-Payment-Proof": "not-base64-json"})
    assert resp.status_code == 400
    assert "Malformed X-Payment-Proof" in resp.json()["error"]


def test_valid_proof_returns_200():
    proof = _valid_payment_proof()
    with TestClient(create_app()) as client:
        resp = client.get("/resource", headers=_proof_header(proof))
    assert resp.status_code == 200
    assert resp.headers.get("X-Payment-Verified") == "true"
    assert "data" in resp.json()


def test_invalid_signature_in_proof_returns_402():
    proof = _valid_payment_proof()
    first_vid = next(iter(proof["certificates"].keys()))
    proof["certificates"][first_vid]["validator_signature"] = base64.urlsafe_b64encode(b"\x00" * 64).decode()
    with TestClient(create_app()) as client:
        resp = client.get("/resource", headers=_proof_header(proof))
    assert resp.status_code == 402
    assert "Invalid payment proof" in resp.json().get("detail", "")


def test_wrong_recipient_in_proof_returns_402():
    proof = _valid_payment_proof(recipient="wrong-recipient")
    with TestClient(create_app()) as client:
        resp = client.get("/resource", headers=_proof_header(proof))
    assert resp.status_code == 402
    assert "recipient" in resp.json().get("detail", "").lower()
