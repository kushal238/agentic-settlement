"""Claim construction and serialization."""

from dataclasses import dataclass
from nacl.signing import SigningKey, VerifyKey

from src.core.crypto import sign, verify


@dataclass(frozen=True)
class Claim:
    sender: str
    recipient: str
    amount: int
    nonce: int
    sender_pubkey: VerifyKey
    signature: bytes

    @staticmethod
    def build_payload(sender: str, recipient: str, amount: int, nonce: int) -> bytes:
        """The canonical byte representation that gets signed.
        Uses length-prefixed fields to prevent delimiter collisions."""
        parts = [sender, recipient, str(amount), str(nonce)]
        return "|".join(f"{len(p)}:{p}" for p in parts).encode()

    def payload(self) -> bytes:
        return Claim.build_payload(self.sender, self.recipient, self.amount, self.nonce)

    def verify_signature(self) -> bool:
        """Check that the sender actually signed this claim."""
        return verify(self.payload(), self.signature, self.sender_pubkey)


def create_claim(
    sender: str,
    recipient: str,
    amount: int,
    nonce: int,
    sender_pubkey: VerifyKey,
    sender_privkey: SigningKey,
) -> Claim:
    """Construct and sign a claim."""
    payload = Claim.build_payload(sender, recipient, amount, nonce)
    signature = sign(payload, sender_privkey)
    return Claim(
        sender=sender,
        recipient=recipient,
        amount=amount,
        nonce=nonce,
        sender_pubkey=sender_pubkey,
        signature=signature,
    )
