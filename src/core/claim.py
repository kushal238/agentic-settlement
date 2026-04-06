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

    def payload(self) -> bytes:
        """The canonical byte representation that gets signed."""
        return f"{self.sender}:{self.recipient}:{self.amount}:{self.nonce}".encode()

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
    # Build payload before we have the signature
    payload = f"{sender}:{recipient}:{amount}:{nonce}".encode()
    signature = sign(payload, sender_privkey)
    return Claim(
        sender=sender,
        recipient=recipient,
        amount=amount,
        nonce=nonce,
        sender_pubkey=sender_pubkey,
        signature=signature,
    )
