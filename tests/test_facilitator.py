"""Tests for facilitator quorum, timeouts, and duplicate / fault handling."""

import time

import pytest

from src.core.account import AccountStateStore
from src.core.claim import Claim, create_claim
from src.core.crypto import generate_keypair, sign
from src.core.facilitator import (
    Facilitator,
    FacilitatorConfig,
    evaluate_round,
)
from src.core.validator import Certificate, Validator, Rejection


def _three_validators():
    """Three independent validators with identical account views (f=1, n=3)."""
    alice_priv, alice_pub = generate_keypair()
    _, bob_pub = generate_keypair()
    validators = []
    for i in range(3):
        st = AccountStateStore()
        st.create_account("alice", alice_pub, balance=100)
        st.create_account("bob", bob_pub, balance=50)
        validators.append(Validator(f"V{i+1}", st))
    return alice_priv, alice_pub, validators


@pytest.fixture
def happy_cluster():
    alice_priv, alice_pub, validators = _three_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    cfg = FacilitatorConfig(
        f=1,
        validators=[(v.validator_id, v) for v in validators],
        per_validator_timeout_seconds=5.0,
    )
    return claim, Facilitator(cfg)


def test_quorum_three_certs_success(happy_cluster):
    claim, fac = happy_cluster
    result = fac.submit_claim(claim)
    assert result.quorum_met
    assert result.success_count == 3
    assert len(result.certificates) == 3
    assert not result.dead
    assert not result.faults


def test_quorum_fails_with_only_two_successes():
    alice_priv, alice_pub, validators = _three_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    # Third validator: alice broke — insufficient balance on its view
    bad_state = AccountStateStore()
    bad_state.create_account("alice", alice_pub, balance=5)
    bad_state.create_account("bob", generate_keypair()[1], balance=50)
    v_bad = Validator("V3", bad_state)

    cfg = FacilitatorConfig(
        f=1,
        validators=[
            (validators[0].validator_id, validators[0]),
            (validators[1].validator_id, validators[1]),
            (v_bad.validator_id, v_bad),
        ],
        per_validator_timeout_seconds=5.0,
    )
    fac = Facilitator(cfg)
    result = fac.submit_claim(claim)
    assert not result.quorum_met
    assert result.success_count == 2
    assert "V3" in result.rejections


def test_dead_validator_counts_as_missing():
    alice_priv, alice_pub, validators = _three_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )

    class SlowClient:
        def verify_and_certify(self, claim: Claim):
            time.sleep(2.0)
            return validators[2].verify_and_certify(claim)

    cfg = FacilitatorConfig(
        f=1,
        validators=[
            (validators[0].validator_id, validators[0]),
            (validators[1].validator_id, validators[1]),
            ("V3", SlowClient()),
        ],
        per_validator_timeout_seconds=0.2,
    )
    fac = Facilitator(cfg)
    result = fac.submit_claim(claim)
    assert not result.quorum_met
    assert "V3" in result.dead
    assert result.success_count == 2


def test_evaluate_round_identical_duplicate_ignored():
    alice_priv, alice_pub, validators = _three_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    c1 = validators[0].verify_and_certify(claim)
    assert isinstance(c1, Certificate)
    responses = {
        "V1": [c1, c1],
        "V2": [validators[1].verify_and_certify(claim)],
        "V3": [validators[2].verify_and_certify(claim)],
    }
    for k in responses:
        assert isinstance(responses[k][0], Certificate)
    r = evaluate_round(claim, 1, responses)
    assert r.quorum_met
    assert r.success_count == 3
    assert not any(f.kind == "duplicate_conflicting_cert" for f in r.faults)


def test_evaluate_round_conflicting_certs_same_validator():
    alice_priv, alice_pub, validators = _three_validators()
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
    assert isinstance(c2, Certificate) and isinstance(c3, Certificate)
    responses = {"V1": [cert_a, cert_b], "V2": [c2], "V3": [c3]}
    r = evaluate_round(claim, 1, responses)
    assert not r.quorum_met
    assert "V1" not in r.certificates
    assert any(f.kind == "duplicate_conflicting_cert" for f in r.faults)


def test_evaluate_round_invalid_validator_signature():
    alice_priv, alice_pub, validators = _three_validators()
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
    assert isinstance(c3, Certificate)
    responses = {
        "V1": [good],
        "V2": [bad_cert],
        "V3": [c3],
    }
    r = evaluate_round(claim, 1, responses)
    assert not r.quorum_met
    assert "V2" not in r.certificates
    assert any(f.kind == "invalid_validator_signature" for f in r.faults)


def test_equivocation_cert_and_rejection():
    alice_priv, alice_pub, validators = _three_validators()
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    cert = validators[0].verify_and_certify(claim)
    assert isinstance(cert, Certificate)
    rej = Rejection(claim, "V1", "forced")
    c2 = validators[1].verify_and_certify(claim)
    c3 = validators[2].verify_and_certify(claim)
    assert isinstance(c2, Certificate) and isinstance(c3, Certificate)
    r = evaluate_round(claim, 1, {"V1": [cert, rej], "V2": [c2], "V3": [c3]})
    assert not r.quorum_met
    assert any(f.kind == "equivocation" for f in r.faults)
