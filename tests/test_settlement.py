"""Tests for facilitator-driven settlement after quorum."""

import time

import pytest

from src.core.account import AccountStateStore
from src.core.claim import Claim, create_claim
from src.core.crypto import generate_keypair
from src.core.facilitator import Facilitator, FacilitatorConfig
from src.core.validator import Validator


def _four_validators(alice_balance: int = 100):
    alice_priv, alice_pub = generate_keypair()
    _, bob_pub = generate_keypair()
    validators = []
    for i in range(4):
        st = AccountStateStore()
        st.create_account("alice", alice_pub, balance=alice_balance)
        st.create_account("bob", bob_pub, balance=50)
        validators.append(Validator(f"V{i+1}", st))
    return alice_priv, alice_pub, validators


def _facilitator(validators, timeout=5.0):
    cfg = FacilitatorConfig(
        f=1,
        validators=[(v.validator_id, v) for v in validators],
        per_validator_timeout_seconds=timeout,
    )
    return Facilitator(cfg)


def test_submit_and_settle_updates_all_signers():
    alice_priv, alice_pub, validators = _four_validators()
    fac = _facilitator(validators)
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )

    result = fac.submit_and_settle(claim)

    assert result.quorum_met
    for v in validators:
        assert v.state.get_balance("alice") == 70
        assert v.state.get_balance("bob") == 80
        assert v.state.get_nonce("alice") == 1


def test_rejecting_validator_state_diverges():
    """Validators that rejected the claim must NOT be settled -- state divergence is intentional."""
    alice_priv, alice_pub, validators = _four_validators()
    # V4 sees a stale, low balance; it will reject the 30-token claim.
    bad_state = AccountStateStore()
    bad_state.create_account("alice", alice_pub, balance=5)
    bad_state.create_account("bob", generate_keypair()[1], balance=50)
    validators[3] = Validator("V4", bad_state)

    fac = _facilitator(validators)
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    result = fac.submit_and_settle(claim)

    assert result.quorum_met
    assert "V4" in result.rejections
    # V1..V3 advanced
    for v in validators[:3]:
        assert v.state.get_balance("alice") == 70
        assert v.state.get_nonce("alice") == 1
    # V4 stayed at its stale view
    assert validators[3].state.get_balance("alice") == 5
    assert validators[3].state.get_nonce("alice") == 0


def test_no_quorum_means_no_settlement():
    alice_priv, alice_pub, validators = _four_validators()
    # Two validators have a stale, low balance -- they reject. Quorum (3) cannot be reached.
    for i in (2, 3):
        bad_state = AccountStateStore()
        bad_state.create_account("alice", alice_pub, balance=5)
        bad_state.create_account("bob", generate_keypair()[1], balance=50)
        validators[i] = Validator(f"V{i+1}", bad_state)

    fac = _facilitator(validators)
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    result = fac.submit_and_settle(claim)

    assert not result.quorum_met
    # No validator should have moved
    assert validators[0].state.get_balance("alice") == 100
    assert validators[0].state.get_balance("bob") == 50
    assert validators[0].state.get_nonce("alice") == 0
    assert validators[1].state.get_balance("alice") == 100
    assert validators[1].state.get_nonce("alice") == 0


def test_sequential_transfers_through_facilitator():
    """Settle a claim, then submit a second claim with the incremented nonce."""
    alice_priv, alice_pub, validators = _four_validators()
    fac = _facilitator(validators)

    claim1 = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    r1 = fac.submit_and_settle(claim1)
    assert r1.quorum_met

    claim2 = create_claim(
        "alice", "bob", 20, nonce=1, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    r2 = fac.submit_and_settle(claim2)
    assert r2.quorum_met

    for v in validators:
        assert v.state.get_balance("alice") == 50
        assert v.state.get_balance("bob") == 100
        assert v.state.get_nonce("alice") == 2


def test_replay_after_settlement_is_rejected():
    """Once settled, resubmitting the same claim fails the nonce check on every validator."""
    alice_priv, alice_pub, validators = _four_validators()
    fac = _facilitator(validators)
    claim = create_claim(
        "alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv
    )
    fac.submit_and_settle(claim)

    replay = fac.submit_and_settle(claim)

    assert not replay.quorum_met
    assert replay.success_count == 0
    assert len(replay.rejections) == 4
    for rej in replay.rejections.values():
        assert "nonce mismatch" in rej.reason
    # State is unchanged by the replay attempt
    for v in validators:
        assert v.state.get_balance("alice") == 70


def test_dead_signer_is_not_settled():
    """A validator that times out during quorum assembly does not get settled."""
    alice_priv, alice_pub, validators = _four_validators()

    class SlowClient:
        def __init__(self, inner: Validator):
            self._inner = inner

        def verify_and_certify(self, claim: Claim):
            time.sleep(2.0)
            return self._inner.verify_and_certify(claim)

        def settle(self, claim: Claim) -> None:
            self._inner.settle(claim)

    slow_inner = validators[3]
    slow = SlowClient(slow_inner)
    cfg = FacilitatorConfig(
        f=1,
        validators=[
            (validators[0].validator_id, validators[0]),
            (validators[1].validator_id, validators[1]),
            (validators[2].validator_id, validators[2]),
            ("V4", slow),
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
    # V1..V3 settled
    for v in validators[:3]:
        assert v.state.get_balance("alice") == 70
        assert v.state.get_nonce("alice") == 1
    # V4's underlying validator did not settle
    assert slow_inner.state.get_balance("alice") == 100
    assert slow_inner.state.get_nonce("alice") == 0
