"""Build in-process validators and wire them into a FacilitatorConfig."""

import base64
import json
import os

from nacl.signing import VerifyKey

from src.core.account import AccountStateStore
from src.core.facilitator import FacilitatorConfig, ValidatorClient
from src.core.validator import Certificate, Rejection, Validator
from src.core.claim import Claim


def _b64decode(s: str) -> bytes:
    """Decode a base64url string, tolerating missing padding."""
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


class LocalValidatorClient:
    """In-process adapter implementing ValidatorClient over a Validator instance."""

    def __init__(self, validator: Validator) -> None:
        self._validator = validator

    def verify_and_certify(self, claim: Claim) -> Certificate | Rejection:
        return self._validator.verify_and_certify(claim)

    def settle(self, claim: Claim) -> None:
        self._validator.settle(claim)


def load_genesis_accounts(path: str | None) -> list[dict]:
    """Load account seed data from a JSON file; returns empty list if path is None or missing."""
    if path and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return []


def build_facilitator_config(
    f: int,
    per_validator_timeout_s: float,
    genesis_accounts: list[dict],
) -> FacilitatorConfig:
    """Instantiate n=3f+1 validators, each seeded with the same genesis accounts.

    Each entry in genesis_accounts must have keys:
      account_id (str), pubkey_b64 (base64url VerifyKey), balance (int).
    """
    n = 3 * f + 1
    validators: list[tuple[str, ValidatorClient]] = []

    for i in range(n):
        vid = f"validator-{i}"
        store = AccountStateStore()
        for acct in genesis_accounts:
            owner = VerifyKey(_b64decode(acct["pubkey_b64"]))
            store.create_account(acct["account_id"], owner, int(acct["balance"]))
        validators.append((vid, LocalValidatorClient(Validator(vid, store))))

    return FacilitatorConfig(
        f=f,
        validators=validators,
        per_validator_timeout_seconds=per_validator_timeout_s,
    )
