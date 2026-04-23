"""Build the 402 Payment Required response headers and body."""

import hashlib
import json

from fastapi.responses import JSONResponse

from src.api_server import config
from src.api_server.models import PaymentRequirements


def build_402_response(payload_hint: dict | None = None, detail: str | None = None) -> JSONResponse:
    """Return a 402 response with PaymentRequirements body and x402 headers.

    payload_hint: if provided, its SHA-256 hash is advertised so the agent can
    verify integrity of what it eventually receives.
    """
    body = PaymentRequirements(
        recipient=config.PAYMENT_RECIPIENT,
        amount=config.PAYMENT_AMOUNT,
        instructions=(
            "Settle via facilitator POST /settle, then retry with "
            "X-Payment-Proof (base64url JSON quorum proof)."
        ),
    )
    headers: dict[str, str] = {
        "X-Payment-Version": "1",
        "X-Payment-Recipient": config.PAYMENT_RECIPIENT,
        "X-Payment-Amount": str(config.PAYMENT_AMOUNT),
    }
    if payload_hint is not None:
        payload_bytes = json.dumps(payload_hint, sort_keys=True).encode()
        headers["X-Payment-Payload-Hash"] = hashlib.sha256(payload_bytes).hexdigest()

    content = body.model_dump()
    if detail:
        content["detail"] = detail

    return JSONResponse(status_code=402, content=content, headers=headers)
