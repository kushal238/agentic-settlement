"""Single FastSet validator -- verifies claims and issues certificates."""

from dataclasses import dataclass

from nacl.signing import SigningKey, VerifyKey

from src.core.account import AccountStateStore
from src.core.claim import Claim
from src.core.crypto import sign, generate_keypair


@dataclass
class Certificate:
    """A validator's signature over a claim, attesting that it checked out."""
    claim: Claim
    validator_id: str
    validator_signature: bytes
    validator_pubkey: VerifyKey


@dataclass
class Rejection:
    claim: Claim
    validator_id: str
    reason: str


class Validator:
    def __init__(self, validator_id: str, state: AccountStateStore):
        self.validator_id = validator_id
        self.state = state
        self._signing_key, self.verify_key = generate_keypair()
        # Pending claims: at most one per sender account
        self._pending: dict[str, Claim] = {}

    def verify_and_certify(self, claim: Claim) -> Certificate | Rejection:
        """
        Independently verify a claim. If valid, sign it and return a certificate.
        If invalid, return a rejection with the reason.
        """
        # 1. Verify sender's signature
        if not claim.verify_signature():
            return Rejection(claim, self.validator_id, "invalid signature")

        # 2. Check sender account exists and pubkey matches
        sender_account = self.state.get_account(claim.sender)
        if sender_account is None:
            return Rejection(claim, self.validator_id, f"unknown sender: {claim.sender}")
        if claim.sender_pubkey != sender_account.owner:
            return Rejection(claim, self.validator_id, "sender pubkey mismatch")

        # 3. Check recipient account exists
        recipient_account = self.state.get_account(claim.recipient)
        if recipient_account is None:
            return Rejection(claim, self.validator_id, f"unknown recipient: {claim.recipient}")

        # 4. Check nonce matches expected
        if claim.nonce != sender_account.nonce:
            return Rejection(
                claim, self.validator_id,
                f"nonce mismatch: expected {sender_account.nonce}, got {claim.nonce}",
            )

        # 5. Check no pending claim for this sender
        if claim.sender in self._pending:
            return Rejection(claim, self.validator_id, "pending claim already exists for sender")

        # 6. Check amount is positive
        if claim.amount <= 0:
            return Rejection(claim, self.validator_id, "invalid amount: must be positive")

        # 7. Check sufficient balance
        if sender_account.balance < claim.amount:
            return Rejection(
                claim, self.validator_id,
                f"insufficient balance: has {sender_account.balance}, needs {claim.amount}",
            )

        # All checks passed -- sign the claim and mark as pending
        self._pending[claim.sender] = claim
        validator_signature = sign(claim.payload(), self._signing_key)

        return Certificate(
            claim=claim,
            validator_id=self.validator_id,
            validator_signature=validator_signature,
            validator_pubkey=self.verify_key,
        )

    def settle(self, claim: Claim) -> None:
        """
        Apply a certified claim to local state. Called after quorum is reached.
        Debits sender, credits recipient, increments nonce, clears pending.
        """
        sender_account = self.state.get_account(claim.sender)
        recipient_account = self.state.get_account(claim.recipient)

        sender_account.balance -= claim.amount
        recipient_account.balance += claim.amount
        sender_account.nonce += 1

        self._pending.pop(claim.sender, None)
