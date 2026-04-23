"""Tests for facilitator quorum, timeouts, and duplicate / fault handling."""

import time

import pytest

from src.core.account import AccountStateStore
from src.core.claim import Claim, create_claim
from src.core.crypto import generate_keypair, sign
from src.core.facilitator import (
    Facilitator,
    FacilitatorConfig,
    FacilitatorResult,
    evaluate_round,
)
from src.core.quorum_proof import build_payment_proof, verify_payment_proof
from src.core.validator import Certificate, Validator, Rejection


def _four_validators():
    """Four independent validators with identical account views (f=1, n=3f+1=4)."""
    alice_priv, alice_pub = generate_keypair()
    _, bob_pub = generate_keypair()
    validators = []
    for i in range(4):
        st = AccountStateStore()
        st.create_account("alice", alice_pub, balance=100)
        st.create_account("bob", bob_pub, balance=50)
        validators.append(Validator(f"V{i+1}", st))
    return alice_priv, alice_pub, validators


@pytest.fixture
def happy_cluster():
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    cfg = FacilitatorConfig(
        f=1,
        validators=[(v.validator_id, v) for v in validators],
        per_validator_timeout_seconds=5.0,
    )
    return claim, Facilitator(cfg)


def test_quorum_all_certs_success(happy_cluster):
    claim, fac = happy_cluster
    result = fac.submit_claim(claim)
    assert result.quorum_met
    assert result.success_count == 4
    assert len(result.certificates) == 4
    assert not result.dead
    assert not result.faults


def test_quorum_fails_when_two_validators_reject():
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    # Two validators have a stale view of alice's balance — they will reject.
    bad_validators = []
    for vid in ("V3", "V4"):
        bad_state = AccountStateStore()
        bad_state.create_account("alice", alice_pub, balance=5)
        bad_state.create_account("bob", generate_keypair()[1], balance=50)
        bad_validators.append(Validator(vid, bad_state))

    cfg = FacilitatorConfig(
        f=1,
        validators=[
            (validators[0].validator_id, validators[0]),
            (validators[1].validator_id, validators[1]),
            (bad_validators[0].validator_id, bad_validators[0]),
            (bad_validators[1].validator_id, bad_validators[1]),
        ],
        per_validator_timeout_seconds=5.0,
    )
    fac = Facilitator(cfg)
    result = fac.submit_claim(claim)
    assert not result.quorum_met
    assert result.success_count == 2
    assert "V3" in result.rejections
    assert "V4" in result.rejections


def test_one_dead_validator_still_reaches_quorum():
    """BFT f=1: one crashed validator is tolerated. 3 successes meets quorum of 2f+1=3."""
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )

    class SlowClient:
        def verify_and_certify(self, claim: Claim):
            time.sleep(2.0)
            return validators[3].verify_and_certify(claim)

    cfg = FacilitatorConfig(
        f=1,
        validators=[
            (validators[0].validator_id, validators[0]),
            (validators[1].validator_id, validators[1]),
            (validators[2].validator_id, validators[2]),
            ("V4", SlowClient()),
        ],
        per_validator_timeout_seconds=0.2,
    )
    fac = Facilitator(cfg)
    result = fac.submit_claim(claim)
    assert result.quorum_met
    assert result.success_count == 3
    assert "V4" in result.dead


def test_two_dead_validators_fail_quorum():
    """BFT f=1: two crashed validators exceed fault tolerance; quorum must fail."""
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )

    class SlowClient:
        def __init__(self, inner: Validator):
            self._inner = inner

        def verify_and_certify(self, claim: Claim):
            time.sleep(2.0)
            return self._inner.verify_and_certify(claim)

    cfg = FacilitatorConfig(
        f=1,
        validators=[
            (validators[0].validator_id, validators[0]),
            (validators[1].validator_id, validators[1]),
            ("V3", SlowClient(validators[2])),
            ("V4", SlowClient(validators[3])),
        ],
        per_validator_timeout_seconds=0.2,
    )
    fac = Facilitator(cfg)
    result = fac.submit_claim(claim)
    assert not result.quorum_met
    assert result.success_count == 2
    assert result.dead == {"V3", "V4"}


def test_evaluate_round_identical_duplicate_ignored():
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    c1 = validators[0].verify_and_certify(claim)
    assert isinstance(c1, Certificate)
    responses = {
        "V1": [c1, c1],
        "V2": [validators[1].verify_and_certify(claim)],
        "V3": [validators[2].verify_and_certify(claim)],
        "V4": [validators[3].verify_and_certify(claim)],
    }
    for k in responses:
        assert isinstance(responses[k][0], Certificate)
    r = evaluate_round(claim, 1, responses)
    assert r.quorum_met
    assert r.success_count == 4
    assert not any(f.kind == "duplicate_conflicting_cert" for f in r.faults)


def test_byzantine_conflicting_certs_tolerated():
    """One validator returns two conflicting certs; the other three are honest. Quorum reached."""
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    sk1, vk1 = generate_keypair()
    sk2, vk2 = generate_keypair()
    payload = claim.payload()
    cert_a = Certificate(
        claim=claim,
        validator_id="V1",
        validator_signature=sign(payload, sk1),
        validator_pubkey=vk1,
    )
    cert_b = Certificate(
        claim=claim,
        validator_id="V1",
        validator_signature=sign(payload, sk2),
        validator_pubkey=vk2,
    )
    c2 = validators[1].verify_and_certify(claim)
    c3 = validators[2].verify_and_certify(claim)
    c4 = validators[3].verify_and_certify(claim)
    assert isinstance(c2, Certificate) and isinstance(c3, Certificate) and isinstance(c4, Certificate)
    responses = {"V1": [cert_a, cert_b], "V2": [c2], "V3": [c3], "V4": [c4]}
    r = evaluate_round(claim, 1, responses)
    assert r.quorum_met
    assert r.success_count == 3
    assert "V1" not in r.certificates
    assert any(f.kind == "duplicate_conflicting_cert" for f in r.faults)


def test_byzantine_invalid_signature_tolerated():
    """One validator submits a forged signature; the other three are honest. Quorum reached."""
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    good = validators[0].verify_and_certify(claim)
    assert isinstance(good, Certificate)
    bad_cert = Certificate(
        claim=claim,
        validator_id="V2",
        validator_signature=b"\x00" * 64,
        validator_pubkey=good.validator_pubkey,
    )
    c3 = validators[2].verify_and_certify(claim)
    c4 = validators[3].verify_and_certify(claim)
    assert isinstance(c3, Certificate) and isinstance(c4, Certificate)
    responses = {
        "V1": [good],
        "V2": [bad_cert],
        "V3": [c3],
        "V4": [c4],
    }
    r = evaluate_round(claim, 1, responses)
    assert r.quorum_met
    assert r.success_count == 3
    assert "V2" not in r.certificates
    assert any(f.kind == "invalid_validator_signature" for f in r.faults)


def test_byzantine_equivocation_tolerated():
    """One validator sends both a cert and a rejection; the other three are honest. Quorum reached."""
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    cert = validators[0].verify_and_certify(claim)
    assert isinstance(cert, Certificate)
    rej = Rejection(claim, "V1", "forced")
    c2 = validators[1].verify_and_certify(claim)
    c3 = validators[2].verify_and_certify(claim)
    c4 = validators[3].verify_and_certify(claim)
    assert isinstance(c2, Certificate) and isinstance(c3, Certificate) and isinstance(c4, Certificate)
    r = evaluate_round(claim, 1, {"V1": [cert, rej], "V2": [c2], "V3": [c3], "V4": [c4]})
    assert r.quorum_met
    assert r.success_count == 3
    assert "V1" not in r.certificates
    assert any(f.kind == "equivocation" for f in r.faults)


def test_payment_proof_rejects_duplicate_signer_certificate():
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    cert = validators[0].verify_and_certify(claim)
    assert isinstance(cert, Certificate)
    result = FacilitatorResult(
        claim=claim,
        quorum_met=True,
        success_count=3,
        certificates={"V1": cert, "V2": cert, "V3": cert},
        rejections={},
        dead=set(),
        faults=[],
    )
    proof = build_payment_proof(result, f=1)
    valid, detail = verify_payment_proof(proof, f=1)
    assert not valid
    assert "validator id mismatch" in detail


def test_payment_proof_rejects_claim_digest_mismatch():
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    certificates = {}
    for v in validators[:3]:
        cert = v.verify_and_certify(claim)
        assert isinstance(cert, Certificate)
        certificates[v.validator_id] = cert
    result = FacilitatorResult(
        claim=claim,
        quorum_met=True,
        success_count=3,
        certificates=certificates,
        rejections={},
        dead=set(),
        faults=[],
    )
    proof = build_payment_proof(result, f=1)
    proof["claim_digest"] = "0" * 64
    valid, detail = verify_payment_proof(proof, f=1)
    assert not valid
    assert "digest mismatch" in detail


def test_payment_proof_rejects_insufficient_signatures():
    alice_priv, alice_pub, validators = _four_validators()
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    cert = validators[0].verify_and_certify(claim)
    assert isinstance(cert, Certificate)
    result = FacilitatorResult(
        claim=claim,
        quorum_met=False,
        success_count=1,
        certificates={"V1": cert},
        rejections={},
        dead=set(),
        faults=[],
    )
    proof = build_payment_proof(result, f=1)
    valid, detail = verify_payment_proof(proof, f=1)
    assert not valid
    assert "insufficient signatures" in detail
