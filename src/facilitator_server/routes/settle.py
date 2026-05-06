"""POST /settle — deserialize claim, run facilitator consensus, return QuorumResult.

Also emits structured lifecycle events to app.state.event_bus so observers
(e.g. the /events SSE endpoint) see the request flow in real time. All
events from one /settle invocation share the same request_id (a UUID
generated at entry) so they can be grouped on the consumer side.
"""

import base64
import logging
import time
import uuid
from typing import Callable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from nacl.signing import VerifyKey

from src.core.claim import Claim
from src.core.eventbus import EventBus
from src.core.facilitator import Facilitator, FacilitatorResult
from src.core.quorum_proof import build_payment_proof
from src.facilitator_server import config
from src.facilitator_server.events import (
    CLAIM_VERIFIED,
    FANOUT_STARTED,
    PROOF_ASSEMBLED,
    QUORUM_EVALUATED,
    SETTLE_BACKGROUND_DONE,
    SETTLE_RECEIVED,
)
from src.facilitator_server.models import (
    ClaimRequest,
    CertificateOut,
    FaultEventOut,
    PaymentProofOut,
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
    proof_build_start_ns = time.perf_counter_ns()
    payment_proof = None
    if result.quorum_met:
        payment_proof = PaymentProofOut(**build_payment_proof(result, config.BFT_F))
    proof_build_end_ns = time.perf_counter_ns()
    proof_build_us = (proof_build_end_ns - proof_build_start_ns) // 1000

    return QuorumResult(
        quorum_met=result.quorum_met,
        success_count=result.success_count,
        certificates=certs,
        rejections=rejections,
        dead=list(result.dead),
        faults=faults,
        payment_proof=payment_proof,
        settle_offsets_us=result.settle_offsets_us,
        proof_build_us=proof_build_us,
    )


def _settle_signers(
    facilitator: Facilitator,
    claim: Claim,
    signer_ids: set[str],
    emit: Callable[[dict], None],
) -> None:
    """Apply settle on every signing validator. Runs as a background task AFTER
    the HTTP response has been returned to the client, so the agent gets the
    proof as soon as quorum is mathematically met. Validator state convergence
    happens asynchronously. Emits SETTLE_BACKGROUND_DONE when finished."""
    t_start_ns = time.perf_counter_ns()
    for vid, client in facilitator._validators:
        if vid in signer_ids:
            client.settle(claim)
    emit({
        "kind": SETTLE_BACKGROUND_DONE,
        "signer_ids": sorted(signer_ids),
        "duration_us": (time.perf_counter_ns() - t_start_ns) // 1000,
    })


@router.post("/settle", response_model=QuorumResult)
def settle(claim_req: ClaimRequest, request: Request, background_tasks: BackgroundTasks) -> QuorumResult:
    """Sync route (def, not async def) so FastAPI runs it in its threadpool.
    This frees the asyncio event loop while submit_claim blocks on validator
    fan-out, so SSE subscribers on /events see events arrive in real time
    instead of in a single burst once the route returns."""
    request_id = str(uuid.uuid4())
    bus: EventBus = request.app.state.event_bus
    loop = request.app.state.event_loop
    publish = bus.make_threadsafe_publisher(loop)

    def emit(event: dict) -> None:
        publish({**event, "request_id": request_id, "ts_mono_ns": time.perf_counter_ns()})

    try:
        claim = claim_from_request(claim_req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Malformed claim data: {exc}") from exc

    emit({
        "kind": SETTLE_RECEIVED,
        "claim": {
            "sender": claim.sender,
            "recipient": claim.recipient,
            "amount": claim.amount,
            "nonce": claim.nonce,
        },
    })

    if not claim.verify_signature():
        raise HTTPException(status_code=400, detail="Invalid sender signature")
    emit({"kind": CLAIM_VERIFIED})

    facilitator: Facilitator = request.app.state.facilitator
    f = facilitator._f
    n = len(facilitator._validators)
    emit({
        "kind": FANOUT_STARTED,
        "f": f,
        "n": n,
        "quorum_threshold": 2 * f + 1,
    })

    # Phase 1: fan-out. submit_claim's on_event fires per-validator
    # VALIDATOR_RESPONDED events from worker threads as they complete; emit
    # enriches each with request_id + ts_mono_ns before publishing.
    result = facilitator.submit_claim(claim, on_event=emit)

    emit({
        "kind": QUORUM_EVALUATED,
        "quorum_met": result.quorum_met,
        "success_count": result.success_count,
        "rejection_count": len(result.rejections),
        "dead_count": len(result.dead),
        "fault_count": len(result.faults),
    })

    # Phase 2: build the response (and the proof, if quorum was met).
    response = result_to_response(result)

    if result.quorum_met:
        emit({
            "kind": PROOF_ASSEMBLED,
            "signature_count": result.success_count,
            "proof_build_us": response.proof_build_us,
        })

    # Phase 3: schedule settle to run AFTER the response is sent. The proof in
    # the response is mathematically final the moment quorum is reached;
    # settle is internal validator bookkeeping that the client does not need
    # to wait for. The background task emits SETTLE_BACKGROUND_DONE when done.
    if result.quorum_met:
        signer_ids = set(result.certificates.keys())
        background_tasks.add_task(_settle_signers, facilitator, claim, signer_ids, emit)

    return response
