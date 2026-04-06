"""Ed25519 key management, signing, and verification."""

from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError


def generate_keypair() -> tuple[SigningKey, VerifyKey]:
    """Generate an Ed25519 signing (private) and verify (public) key pair."""
    signing_key = SigningKey.generate()
    return signing_key, signing_key.verify_key


def sign(message: bytes, signing_key: SigningKey) -> bytes:
    """Sign a message and return the signature bytes (not the signed message)."""
    signed = signing_key.sign(message)
    return signed.signature


def verify(message: bytes, signature: bytes, verify_key: VerifyKey) -> bool:
    """Verify a signature against a message and public key. Returns True/False."""
    try:
        verify_key.verify(message, signature)
        return True
    except BadSignatureError:
        return False
