"""Debug routes for classroom fault injection and runtime reconfiguration.

POST /debug/fault/{validator_id}    — mark a validator as Byzantine (always rejects)
DELETE /debug/fault/{validator_id}  — clear the fault, restore normal operation
GET  /debug/fault                   — list current fault state of all validators
POST /debug/reconfigure?f=N         — rebuild validator set with N=3f+1 nodes
POST /debug/register-account        — register a new account on every validator
                                       (bootstrap path for external clients
                                        that aren't in genesis)
"""

import base64

from fastapi import APIRouter, HTTPException, Query, Request
from nacl.signing import VerifyKey

from src.core.facilitator import Facilitator
from src.facilitator_server import config as cfg
from src.facilitator_server.models import AccountStateOut, RegisterAccountRequest
from src.facilitator_server.node_registry import build_facilitator_config, load_genesis_accounts

router = APIRouter(prefix="/debug", tags=["debug"])


@router.post("/fault/{validator_id}")
async def inject_fault(validator_id: str, request: Request) -> dict:
    registry = request.app.state.debug_validators
    if validator_id not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown validator: {validator_id!r}")
    registry[validator_id]._validator.faulty = True
    return {"validator_id": validator_id, "faulty": True}


@router.delete("/fault/{validator_id}")
async def clear_fault(validator_id: str, request: Request) -> dict:
    registry = request.app.state.debug_validators
    if validator_id not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown validator: {validator_id!r}")
    registry[validator_id]._validator.faulty = False
    return {"validator_id": validator_id, "faulty": False}


@router.get("/fault")
async def list_faults(request: Request) -> dict:
    registry = request.app.state.debug_validators
    return {
        vid: client._validator.faulty
        for vid, client in registry.items()
    }


def _b64decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


@router.post("/register-account", response_model=AccountStateOut, status_code=201)
async def register_account(req: RegisterAccountRequest, request: Request) -> AccountStateOut:
    """Register a new account on every validator.

    The genesis file is loaded once at startup; this endpoint is the only way
    for clients that aren't in genesis (e.g. an external agent CLI) to bring
    their own self-generated keypair into the system without restarting.

    Idempotent on (account_id, pubkey_b64): if the account already exists with
    the same pubkey, returns its current state unchanged. Returns 409 if the
    account exists with a different pubkey. The `balance` parameter is only
    honored on first registration -- subsequent calls with a different balance
    are ignored to keep this endpoint a pure bootstrap, not a faucet.
    """
    if req.balance < 0:
        raise HTTPException(status_code=400, detail="balance must be >= 0")
    try:
        pubkey_bytes = _b64decode(req.pubkey_b64)
        pubkey = VerifyKey(pubkey_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid pubkey: {exc}")

    registry = request.app.state.debug_validators
    if not registry:
        raise HTTPException(status_code=503, detail="No validators registered")

    # Two-phase: pre-check for conflicts across ALL validators before mutating
    # any of them, so a 409 leaves the system in a clean state.
    for vid, client in registry.items():
        existing = client._validator.state.get_account(req.account_id)
        if existing is not None and bytes(existing.owner) != pubkey_bytes:
            raise HTTPException(
                status_code=409,
                detail=f"Account {req.account_id!r} exists on {vid} with a different pubkey",
            )

    for client in registry.values():
        if client._validator.state.get_account(req.account_id) is None:
            client._validator.state.create_account(req.account_id, pubkey, req.balance)

    first_client = next(iter(registry.values()))
    account = first_client._validator.state.get_account(req.account_id)
    return AccountStateOut(
        account_id=req.account_id,
        pubkey_b64=req.pubkey_b64,
        balance=account.balance,
        nonce=account.nonce,
    )


@router.post("/reconfigure")
async def reconfigure(request: Request, f: int = Query(..., ge=1, le=5)) -> dict:
    """Rebuild the validator set with n=3f+1 nodes.  Resets all validator state and fault flags.
    Accepts f in [1, 5] giving n = 4, 7, 10, 13, 16.
    """
    genesis = load_genesis_accounts(cfg.GENESIS_ACCOUNTS_PATH)
    new_cfg, debug_registry = build_facilitator_config(
        f=f,
        per_validator_timeout_s=cfg.PER_VALIDATOR_TIMEOUT_S,
        genesis_accounts=genesis,
    )
    request.app.state.facilitator = Facilitator(new_cfg)
    request.app.state.debug_validators = debug_registry
    n = 3 * f + 1
    return {
        "f": f,
        "n": n,
        "quorum_threshold": 2 * f + 1,
        "validators": [f"validator-{i}" for i in range(n)],
    }
