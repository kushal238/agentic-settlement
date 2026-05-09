"""GET /account/{account_id} -- read current account state.

Returns the account_id, pubkey, balance, and nonce. The agent CLI uses this
to discover its current nonce before constructing a claim, so it doesn't
have to guess-and-retry on nonce-mismatch rejections.

For demo simplicity this reads from the first validator in the registry.
In-process validators run from the same process and share creation/settle
paths via the facilitator, so they should agree. A production implementation
would do a quorum read across f+1 validators and reject divergent answers.
"""

import base64

from fastapi import APIRouter, HTTPException, Request

from src.facilitator_server.models import AccountStateOut

router = APIRouter()


def _b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


@router.get("/account/{account_id}", response_model=AccountStateOut)
async def get_account(account_id: str, request: Request) -> AccountStateOut:
    registry = request.app.state.debug_validators
    if not registry:
        raise HTTPException(status_code=503, detail="No validators registered")

    first_client = next(iter(registry.values()))
    account = first_client._validator.state.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id!r} not found")

    return AccountStateOut(
        account_id=account_id,
        pubkey_b64=_b64encode(account.owner.encode()),
        balance=account.balance,
        nonce=account.nonce,
    )
