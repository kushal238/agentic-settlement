"""Debug routes for classroom fault injection and runtime reconfiguration.

POST /debug/fault/{validator_id}   — mark a validator as Byzantine (always rejects)
DELETE /debug/fault/{validator_id} — clear the fault, restore normal operation
GET  /debug/fault                  — list current fault state of all validators
POST /debug/reconfigure?f=N        — rebuild validator set with N=3f+1 nodes
"""

from fastapi import APIRouter, HTTPException, Query, Request

from src.core.facilitator import Facilitator
from src.facilitator_server import config as cfg
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
