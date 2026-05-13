"""Single FastSet validator -- verifies claims and issues certificates."""

import base64
from dataclasses import dataclass
from typing import Any

from nacl.signing import SigningKey, VerifyKey

from src.core.account import AccountStateStore
from src.core.claim import Claim
from src.core.crypto import sign, generate_keypair, verify


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


def _b64decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


class Validator:
    # Cap how many nonces ahead a single sender can buffer in _presettled.
    # Prevents a malformed or adversarial proof with a far-future nonce from
    # eating unbounded memory. Realistic gaps in operation are 0-2 (a few
    # missed rounds); 1024 is generous and well under any DoS concern.
    MAX_PRESETTLED_LOOKAHEAD = 1024

    def __init__(self, validator_id: str, state: AccountStateStore, f: int = 1):
        self.validator_id = validator_id
        self.state = state
        self._signing_key, self.verify_key = generate_keypair()
        self._pending: dict[str, Claim] = {}
        # Certs awaiting their nonce slot. Key (sender, nonce); value is the
        # already-quorum-verified claim. Step 6 (Presettle) of the FastSet
        # protocol -- buffers messages whose certs arrived before the
        # validator's local view caught up to that nonce.
        self._presettled: dict[tuple[str, int], Claim] = {}
        self._f = f
        # Peer pubkeys for verifying quorum certs in confirm(). Wired post-
        # construction (the validator set is circular at __init__ time).
        self._peers: dict[str, VerifyKey] | None = None
        self.faulty: bool = False  # set via debug endpoint to simulate Byzantine fault

    def set_peers(self, peers: dict[str, VerifyKey]) -> None:
        """Inject the known validator-set pubkeys used to verify quorum certs."""
        self._peers = dict(peers)

    def verify_and_certify(self, claim: Claim) -> Certificate | Rejection:
        if self.faulty:
            return Rejection(claim, self.validator_id, "injected fault (Byzantine)")

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
        Apply a certified claim to local state. Public entry kept for callers
        and tests that want to drive settlement directly without going through
        a quorum proof. The protocol path is confirm(); this is the unwrapped
        primitive.
        """
        self._apply(claim)

    def _apply(self, claim: Claim) -> None:
        """Debit sender, credit recipient, increment nonce, clear pending slot."""
        sender_account = self.state.get_account(claim.sender)
        recipient_account = self.state.get_account(claim.recipient)

        sender_account.balance -= claim.amount
        recipient_account.balance += claim.amount
        sender_account.nonce += 1

        self._pending.pop(claim.sender, None)

    def confirm(self, proof: dict[str, Any]) -> str:
        """
        Step 5+6 of FastSet: accept a quorum certificate, verify it, then
        either apply immediately (nonce matches local view), buffer in the
        presettled set (nonce ahead -- earlier messages still pending), or
        drop as stale (nonce already past).

        Returns one of: "settled", "buffered", "stale".
        Raises ValueError on a malformed or insufficiently-signed proof.

        Verification is stricter than the generic verify_payment_proof used
        by the resource server: every validator signature must come from a
        known peer in this validator's configured set, not just any key.
        """
        if self._peers is None:
            raise RuntimeError(
                "validator peers not configured; call set_peers() before confirm()"
            )

        claim = _claim_from_proof(proof)
        if not claim.verify_signature():
            raise ValueError("invalid sender signature in proof claim")

        self._verify_quorum_signatures(claim, proof)

        sender_account = self.state.get_account(claim.sender)
        if sender_account is None:
            # Accounts are genesis-seeded uniformly across validators today.
            # A missing account here means an upstream sync gap, not a normal
            # protocol case -- raise rather than silently buffering.
            raise ValueError(f"unknown sender in confirm: {claim.sender}")
        if self.state.get_account(claim.recipient) is None:
            raise ValueError(f"unknown recipient in confirm: {claim.recipient}")

        if claim.nonce < sender_account.nonce:
            return "stale"
        if claim.nonce > sender_account.nonce + self.MAX_PRESETTLED_LOOKAHEAD:
            # Defense in depth: a quorum-signed cert this far ahead would
            # require collusion beyond the BFT threshold, but a buggy client
            # or proof-serialization bug could still produce one. Refuse to
            # buffer rather than risk memory growth.
            raise ValueError(
                f"nonce too far ahead: {claim.nonce} > local "
                f"{sender_account.nonce} + {self.MAX_PRESETTLED_LOOKAHEAD}"
            )

        self._presettled[(claim.sender, claim.nonce)] = claim
        self._drain(claim.sender)

        # If our cert is still buffered after drain, an earlier nonce is missing.
        # Otherwise drain applied at least our own cert (we just inserted it at
        # a key >= local nonce, so the drain loop must have popped it).
        if (claim.sender, claim.nonce) in self._presettled:
            return "buffered"
        return "settled"

    def _drain(self, sender: str) -> None:
        """Pop presettled claims for sender in nonce order, applying each."""
        while True:
            account = self.state.get_account(sender)
            claim = self._presettled.pop((sender, account.nonce), None)
            if claim is None:
                return
            self._apply(claim)

    def _verify_quorum_signatures(self, claim: Claim, proof: dict[str, Any]) -> None:
        """Check that >=2f+1 distinct known peers signed claim.payload().

        Stops verifying once the threshold is reached -- extra certificates
        beyond quorum are irrelevant to validity and avoiding the work saves
        Ed25519 verifications on the hot path.
        """
        certs = proof.get("certificates")
        if not isinstance(certs, dict):
            raise ValueError("malformed proof: certificates must be a map")

        payload = claim.payload()
        threshold = 2 * self._f + 1
        valid_signers: set[str] = set()
        for vid, cert in certs.items():
            if len(valid_signers) >= threshold:
                break
            if not isinstance(cert, dict):
                raise ValueError(f"malformed certificate entry for {vid}")
            peer_vk = self._peers.get(vid) if self._peers else None  # type: ignore[union-attr]
            if peer_vk is None:
                raise ValueError(f"unknown validator in proof: {vid}")
            try:
                sig = _b64decode(cert["validator_signature"])
                cert_vk_bytes = _b64decode(cert["validator_pubkey"])
            except Exception as exc:
                raise ValueError(f"malformed certificate for {vid}: {exc}")
            if cert_vk_bytes != peer_vk.encode():
                raise ValueError(f"pubkey mismatch in cert for {vid}")
            if not verify(payload, sig, peer_vk):
                raise ValueError(f"invalid signature in cert for {vid}")
            valid_signers.add(vid)

        if len(valid_signers) < threshold:
            raise ValueError(
                f"insufficient signatures: {len(valid_signers)} < {threshold}"
            )


def _claim_from_proof(proof: dict[str, Any]) -> Claim:
    """Reconstruct a Claim from the on-the-wire proof dict."""
    try:
        claim_data = proof["claim"]
        return Claim(
            sender=claim_data["sender"],
            recipient=claim_data["recipient"],
            amount=int(claim_data["amount"]),
            nonce=int(claim_data["nonce"]),
            sender_pubkey=VerifyKey(_b64decode(claim_data["sender_pubkey"])),
            signature=_b64decode(claim_data["signature"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed proof claim: {exc}")
