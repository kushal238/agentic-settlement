"""Tests for FastSet step 5 (Confirm) + step 6 (Presettle): quorum certs
broadcast back to validators, with a per-sender buffer that drains in nonce
order so validators that missed earlier rounds catch up automatically.
"""

import time
from typing import Any

import pytest

from src.core.account import AccountStateStore
from src.core.claim import Claim, create_claim
from src.core.crypto import generate_keypair
from src.core.facilitator import Facilitator, FacilitatorConfig
from src.core.quorum_proof import build_payment_proof
from src.core.validator import Validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_cluster(alice_balance: int = 100):
    """Build 4 validators (f=1) over a freshly-keyed Alice/Bob, peers wired."""
    alice_priv, alice_pub = generate_keypair()
    _, bob_pub = generate_keypair()
    validators = []
    for i in range(4):
        st = AccountStateStore()
        st.create_account("alice", alice_pub, balance=alice_balance)
        st.create_account("bob", bob_pub, balance=0)
        validators.append(Validator(f"V{i+1}", st, f=1))
    peers = {v.validator_id: v.verify_key for v in validators}
    for v in validators:
        v.set_peers(peers)
    return alice_priv, alice_pub, bob_pub, validators


def _facilitator(validators, timeout=5.0):
    cfg = FacilitatorConfig(
        f=1,
        validators=[(v.validator_id, v) for v in validators],
        per_validator_timeout_seconds=timeout,
    )
    return Facilitator(cfg)


def _proof_for(fac: Facilitator, claim: Claim) -> dict[str, Any]:
    """Submit a claim through the facilitator (but no settle) and serialize the resulting cert."""
    result = fac.submit_claim(claim)
    assert result.quorum_met, "test helper requires quorum"
    return build_payment_proof(result, f=1)


# ---------------------------------------------------------------------------
# Validator.confirm() unit-level behavior
# ---------------------------------------------------------------------------


def test_confirm_applies_when_nonce_matches_local_view():
    """After validation but before any settle/confirm, applying the cert via
    confirm advances state and clears the pending slot."""
    alice_priv, alice_pub, _bob_pub, validators = _fresh_cluster()
    fac = _facilitator(validators)
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    proof = _proof_for(fac, claim)  # signs + sets pending on each validator, no apply yet

    # Pick one validator and drive confirm directly.
    v = validators[0]
    assert "alice" in v._pending  # pending was set during verify_and_certify
    status = v.confirm(proof)

    assert status == "settled"
    assert v.state.get_balance("alice") == 70
    assert v.state.get_balance("bob") == 30
    assert v.state.get_nonce("alice") == 1
    assert "alice" not in v._pending  # pending slot was cleared


def test_confirm_drops_stale_cert():
    """Receiving a cert for an already-settled nonce is a no-op."""
    alice_priv, alice_pub, _bob_pub, validators = _fresh_cluster()
    fac = _facilitator(validators)
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    proof = _proof_for(fac, claim)

    # Apply once -- everyone goes to nonce=1.
    for v in validators:
        v.confirm(proof)
    for v in validators:
        assert v.state.get_nonce("alice") == 1

    # Replay the same proof: every validator should drop it.
    for v in validators:
        status = v.confirm(proof)
        assert status == "stale"
        assert v.state.get_balance("alice") == 70
        assert v.state.get_nonce("alice") == 1


def test_confirm_buffers_then_drains_in_nonce_order():
    """A validator that's behind by two messages can receive certs out-of-order
    and still converge once the missing cert arrives.
    """
    alice_priv, alice_pub, bob_pub, validators = _fresh_cluster(alice_balance=100)
    fac = _facilitator(validators)

    claim1 = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    proof1 = _proof_for(fac, claim1)
    # Apply on cluster so we can build proof2 against nonce=1.
    for v in validators:
        v.confirm(proof1)

    claim2 = create_claim("alice", "bob", 20, nonce=1, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    proof2 = _proof_for(fac, claim2)

    # Build a fresh "behind" validator: still at genesis (nonce=0).
    behind_state = AccountStateStore()
    behind_state.create_account("alice", alice_pub, balance=100)
    behind_state.create_account("bob", bob_pub, balance=0)
    behind = Validator("V_behind", behind_state, f=1)
    behind.set_peers({v.validator_id: v.verify_key for v in validators})

    # Deliver proof2 (nonce=1) first -- should buffer (local nonce is 0).
    status2 = behind.confirm(proof2)
    assert status2 == "buffered"
    assert behind.state.get_nonce("alice") == 0
    assert behind.state.get_balance("alice") == 100

    # Deliver proof1 (nonce=0) -- applies, then drain picks up the buffered proof2.
    status1 = behind.confirm(proof1)
    assert status1 == "settled"
    assert behind.state.get_nonce("alice") == 2
    assert behind.state.get_balance("alice") == 50  # 100 - 30 - 20
    assert behind.state.get_balance("bob") == 50


def test_confirm_rejects_proof_with_insufficient_signatures():
    """A proof carrying only f signatures (below 2f+1=3) must be rejected."""
    alice_priv, alice_pub, _bob_pub, validators = _fresh_cluster()
    fac = _facilitator(validators)
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    proof = _proof_for(fac, claim)

    # Strip down to one cert (success_count=1, < threshold=3).
    only_one = next(iter(proof["certificates"].items()))
    tampered = dict(proof)
    tampered["certificates"] = {only_one[0]: only_one[1]}
    tampered["success_count"] = 1

    with pytest.raises(ValueError, match="insufficient signatures"):
        validators[0].confirm(tampered)


def test_confirm_rejects_proof_with_unknown_signer():
    """A cert signed by a key that isn't in the local peer set must be rejected."""
    alice_priv, alice_pub, _bob_pub, validators = _fresh_cluster()
    fac = _facilitator(validators)
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    proof = _proof_for(fac, claim)

    # Inject a fake validator id that the peer set doesn't know about.
    bogus = {
        "validator_id": "V_bogus",
        "validator_signature": next(iter(proof["certificates"].values()))["validator_signature"],
        "validator_pubkey": next(iter(proof["certificates"].values()))["validator_pubkey"],
    }
    tampered = dict(proof)
    tampered["certificates"] = {"V_bogus": bogus, **proof["certificates"]}

    with pytest.raises(ValueError, match="unknown validator"):
        validators[0].confirm(tampered)


def test_confirm_rejects_nonce_too_far_ahead():
    """A proof whose nonce is more than MAX_PRESETTLED_LOOKAHEAD past the local
    view must be rejected -- this caps memory growth from malformed or
    maliciously-crafted far-future certs.
    """
    alice_priv, alice_pub, _bob_pub, validators = _fresh_cluster()
    fac = _facilitator(validators)
    # Build a claim whose nonce is way ahead of any validator's local view (0).
    far = Validator.MAX_PRESETTLED_LOOKAHEAD + 10
    claim = create_claim(
        "alice", "bob", 1, nonce=far, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    # We need a real quorum cert over this claim; fan out via submit_claim --
    # validators will reject on nonce mismatch, so we build the proof manually
    # by collecting forged-but-signed certs from each validator's signing key
    # over the claim payload directly.
    from src.core.crypto import sign as _sign
    import base64

    payload = claim.payload()
    certs = {}
    for v in validators:
        sig = _sign(payload, v._signing_key)
        certs[v.validator_id] = {
            "validator_id": v.validator_id,
            "validator_signature": base64.urlsafe_b64encode(sig).decode(),
            "validator_pubkey": base64.urlsafe_b64encode(v.verify_key.encode()).decode(),
        }
    proof = {
        "claim": {
            "sender": claim.sender,
            "recipient": claim.recipient,
            "amount": claim.amount,
            "nonce": claim.nonce,
            "sender_pubkey": base64.urlsafe_b64encode(claim.sender_pubkey.encode()).decode(),
            "signature": base64.urlsafe_b64encode(claim.signature).decode(),
        },
        "certificates": certs,
    }

    with pytest.raises(ValueError, match="nonce too far ahead"):
        validators[0].confirm(proof)
    # Buffer must remain empty -- nothing was stored.
    assert validators[0]._presettled == {}


def test_confirm_without_peers_raises():
    """A validator with no peer set wired cannot verify quorum certs."""
    alice_priv, alice_pub, _bob_pub, validators = _fresh_cluster()
    fac = _facilitator(validators)
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    proof = _proof_for(fac, claim)

    bare = Validator("V_bare", AccountStateStore(), f=1)
    with pytest.raises(RuntimeError, match="peers not configured"):
        bare.confirm(proof)


# ---------------------------------------------------------------------------
# End-to-end: facilitator broadcast brings a non-signer back online
# ---------------------------------------------------------------------------


def test_facilitator_broadcast_catches_up_a_timed_out_validator():
    """V4 is slow enough to time out during validation but reachable for confirm.
    The cert from V1..V3 should flow to V4 and bring it up to date.
    """
    alice_priv, alice_pub, _bob_pub, validators = _fresh_cluster()

    class FlakyClient:
        """Slow on verify_and_certify (times out), responsive on confirm."""
        def __init__(self, inner: Validator):
            self._inner = inner

        def verify_and_certify(self, claim):
            time.sleep(2.0)
            raise RuntimeError("unreachable")

        def settle(self, claim) -> None:
            self._inner.settle(claim)

        def confirm(self, proof) -> str:
            return self._inner.confirm(proof)

    flaky_inner = validators[3]
    flaky = FlakyClient(flaky_inner)
    cfg = FacilitatorConfig(
        f=1,
        validators=[
            (validators[0].validator_id, validators[0]),
            (validators[1].validator_id, validators[1]),
            (validators[2].validator_id, validators[2]),
            ("V4", flaky),
        ],
        per_validator_timeout_seconds=0.2,
    )
    fac = Facilitator(cfg)
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )

    result = fac.submit_and_settle(claim)

    assert result.quorum_met
    assert "V4" in result.dead
    # All four validators -- including the one that timed out -- converged via confirm.
    for v in validators:
        assert v.state.get_balance("alice") == 70
        assert v.state.get_nonce("alice") == 1
