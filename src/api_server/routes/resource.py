"""GET /resource — x402 payment-gated endpoint.

Also emits structured lifecycle events to app.state.event_bus so observers
(e.g. the /events SSE endpoint, or the observer CLI subscribed to both
servers) see the request flow in real time. All events from one /resource
invocation share the same request_id (a UUID generated at entry) so they
can be grouped on the consumer side and joined with /settle events from
the facilitator on the same logical buy attempt.
"""

import base64
import json
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from src.api_server import config
from src.api_server.events import (
    PROOF_RECEIVED,
    PROOF_REJECTED,
    PROOF_VERIFIED,
    REQUIREMENTS_ISSUED,
    RESOURCE_RELEASED,
    RESOURCE_REQUESTED,
)
from src.api_server.payment_requirements import build_402_response
from src.core.eventbus import EventBus
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
async def get_resource(request: Request) -> Response:
    request_id = str(uuid.uuid4())
    bus: EventBus = request.app.state.event_bus

    def emit(event: dict) -> None:
        bus.publish({**event, "request_id": request_id, "ts_mono_ns": time.perf_counter_ns()})

    proof_header = request.headers.get("X-Payment-Proof")
    emit({"kind": RESOURCE_REQUESTED, "has_proof_header": proof_header is not None})

    # Step 2: no proof header → issue 402 with requirements
    if not proof_header:
        emit({"kind": REQUIREMENTS_ISSUED, "reason": "no_proof_header"})
        return build_402_response(payload_hint=VALUABLE_PAYLOAD)

    emit({"kind": PROOF_RECEIVED})

    # Step 8: parse client-supplied quorum proof
    try:
        proof_json = _b64decode(proof_header)
        proof_data = json.loads(proof_json)
    except Exception as exc:
        emit({"kind": PROOF_REJECTED, "reason": "malformed", "detail": str(exc)})
        return JSONResponse(status_code=400, content={"error": f"Malformed X-Payment-Proof: {exc}"})

    is_valid, detail = verify_payment_proof(proof_data, config.PAYMENT_BFT_F)
    if not is_valid:
        emit({"kind": PROOF_REJECTED, "reason": "invalid_proof", "detail": detail})
        emit({"kind": REQUIREMENTS_ISSUED, "reason": "invalid_proof"})
        return build_402_response(payload_hint=VALUABLE_PAYLOAD, detail=f"Invalid payment proof: {detail}")

    claim = proof_data.get("claim", {})
    if claim.get("recipient") != config.PAYMENT_RECIPIENT:
        emit({
            "kind": PROOF_REJECTED,
            "reason": "wrong_recipient",
            "expected": config.PAYMENT_RECIPIENT,
            "got": claim.get("recipient"),
        })
        emit({"kind": REQUIREMENTS_ISSUED, "reason": "wrong_recipient"})
        return build_402_response(
            payload_hint=VALUABLE_PAYLOAD,
            detail=f"Wrong recipient in proof; expected {config.PAYMENT_RECIPIENT!r}",
        )
    amount = int(claim.get("amount", 0))
    if amount < config.PAYMENT_AMOUNT:
        emit({
            "kind": PROOF_REJECTED,
            "reason": "insufficient_amount",
            "minimum": config.PAYMENT_AMOUNT,
            "got": amount,
        })
        emit({"kind": REQUIREMENTS_ISSUED, "reason": "insufficient_amount"})
        return build_402_response(
            payload_hint=VALUABLE_PAYLOAD,
            detail=f"Insufficient amount in proof; minimum is {config.PAYMENT_AMOUNT}",
        )

    quorum_size = proof_data["success_count"]
    emit({
        "kind": PROOF_VERIFIED,
        "quorum_size": quorum_size,
        "sender": claim.get("sender"),
        "recipient": claim.get("recipient"),
        "amount": amount,
    })

    # Step 11: release valuable information
    emit({"kind": RESOURCE_RELEASED})
    return JSONResponse(
        status_code=200,
        content={"data": VALUABLE_PAYLOAD},
        headers={
            "X-Payment-Verified": "true",
            "X-Payment-Quorum-Size": str(quorum_size),
        },
    )
