"""Local Ed25519 keypair persistence for the agent CLI.

The wallet lives at $WALLET_PATH (default ~/.agentic-settlement/agent_key.json),
not inside the repo, so it survives across runs and isn't accidentally
committed. The format is plain JSON -- this is a demo system controlling demo
balances; if/when the keys protect anything real, layer Fernet+passphrase on
top of load_or_generate.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from nacl.signing import SigningKey, VerifyKey


DEFAULT_WALLET_PATH = Path.home() / ".agentic-settlement" / "agent_key.json"


def _b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


def _b64decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


@dataclass
class Wallet:
    account_id: str
    signing_key: SigningKey

    @property
    def verify_key(self) -> VerifyKey:
        return self.signing_key.verify_key

    @property
    def pubkey_b64(self) -> str:
        return _b64encode(bytes(self.verify_key))

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "pubkey_b64": self.pubkey_b64,
            "private_key_b64": _b64encode(bytes(self.signing_key)),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Wallet":
        sk_bytes = _b64decode(data["private_key_b64"])
        return cls(account_id=data["account_id"], signing_key=SigningKey(sk_bytes))


def wallet_path() -> Path:
    """Resolve the wallet file path. Honors $AGENTIC_WALLET_PATH override for
    tests and for users who want to keep multiple agent identities."""
    override = os.getenv("AGENTIC_WALLET_PATH")
    if override:
        return Path(override)
    return DEFAULT_WALLET_PATH


def load_or_generate(path: Path | None = None, account_id: str | None = None) -> tuple[Wallet, bool]:
    """Return (wallet, was_generated).

    If `path` exists, load and return the wallet (was_generated=False).
    Otherwise generate a fresh keypair, persist it, and return it (was_generated=True).

    `account_id` is honored only on generation. If omitted, a random
    `agent-{8 hex}` is used. Real agents shouldn't pick their own pretty
    names; the option is for demo readability.
    """
    p = path or wallet_path()
    if p.exists():
        return Wallet.from_dict(json.loads(p.read_text())), False

    sk = SigningKey.generate()
    aid = account_id or f"agent-{secrets.token_hex(4)}"
    wallet = Wallet(account_id=aid, signing_key=sk)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(wallet.to_dict(), indent=2))
    return wallet, True
