from pydantic import BaseModel


class ClaimRequest(BaseModel):
    sender: str
    recipient: str
    amount: int
    nonce: int
    sender_pubkey: str  # base64url-encoded Ed25519 VerifyKey (32 bytes)
    signature: str      # base64url-encoded Ed25519 signature (64 bytes)


class CertificateOut(BaseModel):
    validator_id: str
    validator_signature: str  # base64url
    validator_pubkey: str     # base64url


class PaymentProofOut(BaseModel):
    claim: ClaimRequest
    claim_digest: str
    success_count: int
    quorum_threshold: int
    certificates: dict[str, CertificateOut]


class FaultEventOut(BaseModel):
    kind: str
    validator_id: str
    detail: str


class QuorumResult(BaseModel):
    quorum_met: bool
    success_count: int
    certificates: dict[str, CertificateOut]
    rejections: dict[str, str]   # validator_id -> reason string
    dead: list[str]
    faults: list[FaultEventOut]
    payment_proof: PaymentProofOut | None = None
