"""GET /resource — x402 payment-gated endpoint."""

import base64
import json
import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from nacl.signing import VerifyKey

from src.api_server import config
from src.api_server.models import ClaimRequest, QuorumResult
from src.api_server.payment_requirements import build_402_response
from src.core.claim import Claim

logger = logging.getLogger(__name__)
router = APIRouter()

# The valuable information released after successful payment.
VALUABLE_PAYLOAD = {
    "data": "This is the valuable information you paid for.",
    "insight": "FastSet achieves BFT settlement with 3f+1 validators and 2f+1 quorum.",
}


def _b64decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


@router.get("/resource")
async def get_resource(request: Request) -> JSONResponse:
    claim_header = request.headers.get("X-Payment-Claim")
    sig_header = request.headers.get("X-Payment-Signature")

    # Step 2: no payment headers → issue 402 with requirements
    if not claim_header or not sig_header:
        return build_402_response(payload_hint=VALUABLE_PAYLOAD)

    # Step 3 (server-side): parse claim fields from base64-encoded JSON header
    try:
        claim_json = _b64decode(claim_header)
        claim_data = json.loads(claim_json)
        claim_req = ClaimRequest(
            sender=claim_data["sender"],
            recipient=claim_data["recipient"],
            amount=int(claim_data["amount"]),
            nonce=int(claim_data["nonce"]),
            sender_pubkey=claim_data["sender_pubkey"],
            signature=sig_header,
        )
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": f"Malformed X-Payment-Claim: {exc}"})

    # Validate recipient and amount match what this server expects
    if claim_req.recipient != config.PAYMENT_RECIPIENT:
        return JSONResponse(
            status_code=400,
            content={"error": f"Wrong recipient; expected {config.PAYMENT_RECIPIENT!r}"},
        )
    if claim_req.amount < config.PAYMENT_AMOUNT:
        return JSONResponse(
            status_code=400,
            content={"error": f"Insufficient amount; minimum is {config.PAYMENT_AMOUNT}"},
        )

    # Step 4: local signature check before the network call
    try:
        pubkey = VerifyKey(_b64decode(claim_req.sender_pubkey))
        sig_bytes = _b64decode(claim_req.signature)
        claim = Claim(
            sender=claim_req.sender,
            recipient=claim_req.recipient,
            amount=claim_req.amount,
            nonce=claim_req.nonce,
            sender_pubkey=pubkey,
            signature=sig_bytes,
        )
        if not claim.verify_signature():
            return JSONResponse(status_code=400, content={"error": "Invalid sender signature"})
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": f"Signature verification error: {exc}"})

    # Step 4 (cont.): forward serialized claim to facilitator
    http_client: httpx.AsyncClient = request.app.state.http_client
    try:
        resp = await http_client.post(
            f"{config.FACILITATOR_URL}/settle",
            json=claim_req.model_dump(),
            timeout=config.FACILITATOR_TIMEOUT_S,
        )
    except httpx.ConnectError:
        return JSONResponse(status_code=503, content={"error": "Settlement service unavailable"})
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": "Settlement timed out"})

    if resp.status_code != 200:
        logger.warning("Facilitator returned %s: %s", resp.status_code, resp.text)
        return JSONResponse(
            status_code=502,
            content={"error": "Facilitator returned unexpected status", "detail": resp.text},
        )

    # Steps 5–6: check quorum result
    result_data = resp.json()
    quorum = QuorumResult(**result_data)

    if not quorum.quorum_met:
        return build_402_response(
            detail=f"Quorum not reached ({quorum.success_count} certificates, "
                   f"{len(quorum.rejections)} rejections, {len(quorum.dead)} dead validators)",
        )

    # Step 6: release valuable information
    return JSONResponse(
        status_code=200,
        content={"data": VALUABLE_PAYLOAD},
        headers={
            "X-Payment-Settled": "true",
            "X-Payment-Quorum-Size": str(quorum.success_count),
        },
    )
