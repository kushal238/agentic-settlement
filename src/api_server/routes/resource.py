"""GET /resource — x402 payment-gated endpoint."""

import base64
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.api_server import config
from src.api_server.payment_requirements import build_402_response
from src.core.quorum_proof import verify_payment_proof

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
    proof_header = request.headers.get("X-Payment-Proof")

    # Step 2: no proof header → issue 402 with requirements
    if not proof_header:
        return build_402_response(payload_hint=VALUABLE_PAYLOAD)

    # Step 8: parse client-supplied quorum proof
    try:
        proof_json = _b64decode(proof_header)
        proof_data = json.loads(proof_json)
    except Exception as exc:
        return JSONResponse(status_code=400, content={"error": f"Malformed X-Payment-Proof: {exc}"})

    is_valid, detail = verify_payment_proof(proof_data, config.PAYMENT_BFT_F)
    if not is_valid:
        return build_402_response(payload_hint=VALUABLE_PAYLOAD, detail=f"Invalid payment proof: {detail}")

    claim = proof_data.get("claim", {})
    if claim.get("recipient") != config.PAYMENT_RECIPIENT:
        return build_402_response(
            payload_hint=VALUABLE_PAYLOAD,
            detail=f"Wrong recipient in proof; expected {config.PAYMENT_RECIPIENT!r}",
        )
    if int(claim.get("amount", 0)) < config.PAYMENT_AMOUNT:
        return build_402_response(
            payload_hint=VALUABLE_PAYLOAD,
            detail=f"Insufficient amount in proof; minimum is {config.PAYMENT_AMOUNT}",
        )

    # Step 11: release valuable information
    return JSONResponse(
        status_code=200,
        content={"data": VALUABLE_PAYLOAD},
        headers={
            "X-Payment-Verified": "true",
            "X-Payment-Quorum-Size": str(proof_data["success_count"]),
        },
    )
