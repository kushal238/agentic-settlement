from pydantic import BaseModel


class ClaimRequest(BaseModel):
    sender: str
    recipient: str
    amount: int
    nonce: int
    sender_pubkey: str  # base64url-encoded Ed25519 VerifyKey
    signature: str      # base64url-encoded Ed25519 signature


class PaymentRequirements(BaseModel):
    payment_required: bool = True
    version: str = "1"
    recipient: str
    amount: int
    scheme: str = "fastset-ed25519"
    instructions: str


class CertificateOut(BaseModel):
    validator_id: str
    validator_signature: str
    validator_pubkey: str


class FaultEventOut(BaseModel):
    kind: str
    validator_id: str
    detail: str


class QuorumResult(BaseModel):
    """Mirror of facilitator_server QuorumResult — kept independent for service boundary."""
    quorum_met: bool
    success_count: int
    certificates: dict[str, CertificateOut]
    rejections: dict[str, str]
    dead: list[str]
    faults: list[FaultEventOut]
