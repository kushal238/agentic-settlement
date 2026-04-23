"""POST /settle — deserialize claim, run facilitator consensus, return QuorumResult."""

import base64
import logging

from fastapi import APIRouter, HTTPException, Request
from nacl.signing import VerifyKey

from src.core.claim import Claim
from src.core.facilitator import Facilitator, FacilitatorResult
from src.facilitator_server.models import (
    ClaimRequest,
    CertificateOut,
    FaultEventOut,
    QuorumResult,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _b64decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


def claim_from_request(req: ClaimRequest) -> Claim:
    sender_pubkey = VerifyKey(_b64decode(req.sender_pubkey))
    signature = _b64decode(req.signature)
    return Claim(
        sender=req.sender,
        recipient=req.recipient,
        amount=req.amount,
        nonce=req.nonce,
        sender_pubkey=sender_pubkey,
        signature=signature,
    )


def result_to_response(result: FacilitatorResult) -> QuorumResult:
    certs = {
        vid: CertificateOut(
            validator_id=cert.validator_id,
            validator_signature=_b64encode(cert.validator_signature),
            validator_pubkey=_b64encode(cert.validator_pubkey.encode()),
        )
        for vid, cert in result.certificates.items()
    }
    rejections = {vid: rej.reason for vid, rej in result.rejections.items()}
    faults = [
        FaultEventOut(kind=f.kind, validator_id=f.validator_id, detail=f.detail)
        for f in result.faults
    ]
    return QuorumResult(
        quorum_met=result.quorum_met,
        success_count=result.success_count,
        certificates=certs,
        rejections=rejections,
        dead=list(result.dead),
        faults=faults,
    )


@router.post("/settle", response_model=QuorumResult)
async def settle(claim_req: ClaimRequest, request: Request) -> QuorumResult:
    try:
        claim = claim_from_request(claim_req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Malformed claim data: {exc}") from exc

    if not claim.verify_signature():
        raise HTTPException(status_code=400, detail="Invalid sender signature")

    facilitator: Facilitator = request.app.state.facilitator
    result = facilitator.submit_and_settle(claim)
    return result_to_response(result)
