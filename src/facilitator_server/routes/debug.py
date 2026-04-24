"""Debug routes for classroom fault injection.

POST /debug/fault/{validator_id}   — mark a validator as Byzantine (always rejects)
DELETE /debug/fault/{validator_id} — clear the fault, restore normal operation
GET  /debug/fault                  — list current fault state of all validators
"""

from fastapi import APIRouter, HTTPException, Request

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
