"""Tests for the core building block: one validator, one claim."""

import pytest

from src.core.crypto import generate_keypair, sign
from src.core.account import AccountStateStore
from src.core.claim import Claim, create_claim
from src.core.validator import Validator, Certificate, Rejection


@pytest.fixture
def setup():
    """Create Alice (100 tokens), Bob (50 tokens), and a single validator."""
    alice_priv, alice_pub = generate_keypair()
    bob_priv, bob_pub = generate_keypair()

    state = AccountStateStore()
    state.create_account("alice", alice_pub, balance=100)
    state.create_account("bob", bob_pub, balance=50)

    validator = Validator("V1", state)

    return alice_priv, alice_pub, bob_priv, bob_pub, validator


def test_valid_claim_returns_certificate(setup):
    alice_priv, alice_pub, bob_priv, bob_pub, validator = setup

    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Certificate)
    assert result.validator_id == "V1"


def test_insufficient_balance_rejected(setup):
    alice_priv, alice_pub, _, _, validator = setup

    claim = create_claim("alice", "bob", 200, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "insufficient balance" in result.reason


def test_wrong_nonce_rejected(setup):
    alice_priv, alice_pub, _, _, validator = setup

    claim = create_claim("alice", "bob", 30, nonce=5, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "nonce mismatch" in result.reason


def test_bad_signature_rejected(setup):
    _, alice_pub, bob_priv, _, validator = setup

    # Sign with Bob's key but claim to be Alice
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=bob_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "invalid signature" in result.reason


def test_pending_slot_blocks_second_claim(setup):
    alice_priv, alice_pub, _, _, validator = setup

    claim1 = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    claim2 = create_claim("alice", "bob", 20, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)

    result1 = validator.verify_and_certify(claim1)
    result2 = validator.verify_and_certify(claim2)

    assert isinstance(result1, Certificate)
    assert isinstance(result2, Rejection)
    assert "pending" in result2.reason


def test_unknown_sender_rejected(setup):
    _, _, bob_priv, bob_pub, validator = setup

    claim = create_claim("charlie", "bob", 10, nonce=0, sender_pubkey=bob_pub, sender_privkey=bob_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "unknown sender" in result.reason


def test_unknown_recipient_rejected(setup):
    alice_priv, alice_pub, _, _, validator = setup

    claim = create_claim("alice", "charlie", 10, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "unknown recipient" in result.reason


def test_pubkey_mismatch_rejected(setup):
    alice_priv, alice_pub, bob_priv, bob_pub, validator = setup

    # Sign with Bob's key AND use Bob's pubkey, but claim sender is "alice"
    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=bob_pub, sender_privkey=bob_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "pubkey mismatch" in result.reason


def test_negative_amount_rejected(setup):
    alice_priv, alice_pub, _, _, validator = setup

    claim = create_claim("alice", "bob", -10, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "must be positive" in result.reason


def test_zero_amount_rejected(setup):
    alice_priv, alice_pub, _, _, validator = setup

    claim = create_claim("alice", "bob", 0, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result = validator.verify_and_certify(claim)

    assert isinstance(result, Rejection)
    assert "must be positive" in result.reason


def test_settle_updates_balances(setup):
    alice_priv, alice_pub, _, _, validator = setup

    claim = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result = validator.verify_and_certify(claim)
    assert isinstance(result, Certificate)

    validator.settle(claim)

    assert validator.state.get_balance("alice") == 70
    assert validator.state.get_balance("bob") == 80
    assert validator.state.get_nonce("alice") == 1


def test_sequential_transfers_work(setup):
    alice_priv, alice_pub, _, _, validator = setup

    # First transfer: Alice -> Bob, 30 tokens
    claim1 = create_claim("alice", "bob", 30, nonce=0, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result1 = validator.verify_and_certify(claim1)
    assert isinstance(result1, Certificate)
    validator.settle(claim1)

    # Second transfer: Alice -> Bob, 20 tokens (nonce incremented)
    claim2 = create_claim("alice", "bob", 20, nonce=1, sender_pubkey=alice_pub, sender_privkey=alice_priv)
    result2 = validator.verify_and_certify(claim2)
    assert isinstance(result2, Certificate)
    validator.settle(claim2)

    assert validator.state.get_balance("alice") == 50
    assert validator.state.get_balance("bob") == 100
    assert validator.state.get_nonce("alice") == 2
