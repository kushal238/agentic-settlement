#!/usr/bin/env python3
"""
Generate dev keypairs, write data/dev_genesis.json, and print a ready-to-import
Postman environment JSON to stdout.

Usage:
    python scripts/dev_setup.py > postman/dev.postman_environment.json

Then start the servers in two separate terminals:

    # Terminal 1 — Facilitator
    GENESIS_ACCOUNTS_PATH=data/dev_genesis.json \
    python -m src.facilitator_server.main

    # Terminal 2 — API Server
    PAYMENT_RECIPIENT=server-recipient \
    python -m src.api_server.main
"""

import base64
import json
import os
import sys

from nacl.signing import SigningKey


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def main() -> None:
    sender_sk = SigningKey.generate()
    recipient_sk = SigningKey.generate()

    sender_seed_b64   = b64url(bytes(sender_sk))
    sender_pubkey_b64  = b64url(bytes(sender_sk.verify_key))
    recipient_pubkey_b64 = b64url(bytes(recipient_sk.verify_key))

    # Write genesis file (seeded into every validator on startup)
    os.makedirs("data", exist_ok=True)
    genesis = [
        {"account_id": "sender-1",       "pubkey_b64": sender_pubkey_b64,    "balance": 1000},
        {"account_id": "server-recipient","pubkey_b64": recipient_pubkey_b64, "balance": 0},
    ]
    with open("data/dev_genesis.json", "w") as fh:
        json.dump(genesis, fh, indent=2)
    print("✓ Wrote data/dev_genesis.json", file=sys.stderr)
    print("✓ Sender seed and pubkey generated", file=sys.stderr)
    print("", file=sys.stderr)
    print("Start servers:", file=sys.stderr)
    print("  GENESIS_ACCOUNTS_PATH=data/dev_genesis.json python -m src.facilitator_server.main", file=sys.stderr)
    print("  PAYMENT_RECIPIENT=server-recipient python -m src.api_server.main", file=sys.stderr)
    print("", file=sys.stderr)
    print("FastAPI docs:", file=sys.stderr)
    print("  API Server:         http://localhost:8000/docs", file=sys.stderr)
    print("  Facilitator Server: http://localhost:8001/docs", file=sys.stderr)

    # Postman environment JSON — printed to stdout so caller can redirect to a file
    env = {
        "name": "agentic-settlement-dev",
        "_postman_variable_scope": "environment",
        "values": [
            {"key": "SENDER_SEED_B64",    "value": sender_seed_b64,    "type": "secret",  "enabled": True},
            {"key": "SENDER_PUBKEY_B64",  "value": sender_pubkey_b64,  "type": "default", "enabled": True},
            {"key": "SENDER_ID",          "value": "sender-1",         "type": "default", "enabled": True},
            {"key": "RECIPIENT_ID",       "value": "server-recipient", "type": "default", "enabled": True},
            {"key": "PAYMENT_AMOUNT",     "value": "10",               "type": "default", "enabled": True},
            {"key": "CURRENT_NONCE",      "value": "0",                "type": "default", "enabled": True},
        ],
    }
    print(json.dumps(env, indent=2))


if __name__ == "__main__":
    main()
