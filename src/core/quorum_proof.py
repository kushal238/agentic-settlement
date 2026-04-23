"""Build and verify transferable quorum proofs for paid resource access."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from nacl.signing import VerifyKey

from src.core.claim import Claim
from src.core.crypto import verify
from src.core.facilitator import FacilitatorResult


def _b64decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


def build_payment_proof(result: FacilitatorResult, f: int) -> dict[str, Any]:
    """Serialize a facilitator result into a client-relayable proof object."""
    claim_payload = result.claim.payload()
    claim_digest = hashlib.sha256(claim_payload).hexdigest()
    certificates = {
        validator_id: {
            "validator_id": cert.validator_id,
            "validator_signature": _b64encode(cert.validator_signature),
            "validator_pubkey": _b64encode(cert.validator_pubkey.encode()),
        }
        for validator_id, cert in result.certificates.items()
    }
    return {
        "claim": {
            "sender": result.claim.sender,
            "recipient": result.claim.recipient,
            "amount": result.claim.amount,
            "nonce": result.claim.nonce,
            "sender_pubkey": _b64encode(result.claim.sender_pubkey.encode()),
            "signature": _b64encode(result.claim.signature),
        },
        "claim_digest": claim_digest,
        "success_count": result.success_count,
        "quorum_threshold": (2 * f) + 1,
        "certificates": certificates,
    }


def verify_payment_proof(proof: dict[str, Any], f: int) -> tuple[bool, str]:
    """Verify quorum proof integrity and validator certificate signatures."""
    try:
        claim_data = proof["claim"]
        claim = Claim(
            sender=claim_data["sender"],
            recipient=claim_data["recipient"],
            amount=int(claim_data["amount"]),
            nonce=int(claim_data["nonce"]),
            sender_pubkey=VerifyKey(_b64decode(claim_data["sender_pubkey"])),
            signature=_b64decode(claim_data["signature"]),
        )
        if not claim.verify_signature():
            return False, "invalid sender signature in proof claim"
    except Exception as exc:  # pragma: no cover - guarded by API tests
        return False, f"malformed proof claim: {exc}"

    payload = claim.payload()
    expected_digest = hashlib.sha256(payload).hexdigest()
    if proof.get("claim_digest") != expected_digest:
        return False, "claim digest mismatch"

    certificates = proof.get("certificates", {})
    if not isinstance(certificates, dict):
        return False, "certificates must be a map"

    seen_signers: set[str] = set()
    for validator_id, cert in certificates.items():
        try:
            if cert["validator_id"] != validator_id:
                return False, "validator id mismatch inside certificate"
            signer_id = cert["validator_id"]
            if signer_id in seen_signers:
                return False, "duplicate signer in certificates"
            seen_signers.add(signer_id)
            signature = _b64decode(cert["validator_signature"])
            pubkey = VerifyKey(_b64decode(cert["validator_pubkey"]))
        except Exception as exc:  # pragma: no cover - guarded by API tests
            return False, f"malformed validator certificate: {exc}"
        if not verify(payload, signature, pubkey):
            return False, f"invalid validator signature for {signer_id}"

    success_count = int(proof.get("success_count", -1))
    if success_count != len(certificates):
        return False, "success_count does not match certificates count"

    quorum_threshold = int(proof.get("quorum_threshold", -1))
    expected_threshold = (2 * f) + 1
    if quorum_threshold != expected_threshold:
        return False, "unexpected quorum threshold"
    if success_count < quorum_threshold:
        return False, "insufficient signatures for quorum"

    return True, ""
