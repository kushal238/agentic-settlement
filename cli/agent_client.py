"""Customer agent CLI for the agentic-settlement system.

Subcommands:
  setup   -- generate keypair if needed, register with facilitator, exit.
  buy     -- bootstrap if needed, then run the full x402 buy flow narrated
             step by step against the live api_server and facilitator.

Run `python -m cli.agent_client buy --help` for flags.

Design notes:
  - Speaks only HTTP. Knows nothing about validators internally.
  - Verbose by default for teaching; --quiet for piping.
  - run_buy() takes injected httpx.Client objects so tests can drive it
    against in-process apps via httpx.ASGITransport.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

from cli.wallet import Wallet, load_or_generate, wallet_path
from src.core.claim import create_claim


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

COLOR_CODES = {
    "wallet":    "35",  # magenta
    "bootstrap": "36",  # cyan
    "buy":       "34",  # blue
    "error":     "31",  # red
    "ok":        "32",  # green
    "dim":       "2",
    "bold":      "1",
}


def _b64decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode()


class Narrator:
    """Per-phase logger. Each phase (wallet/bootstrap/buy) has its own tag."""

    TAG_WIDTH = 13

    def __init__(self, prefix: str, *, use_color: bool, quiet: bool, stream=sys.stderr):
        self.prefix = prefix
        self.use_color = use_color
        self.quiet = quiet
        self.stream = stream

    def _styled(self, text: str, code: str) -> str:
        if not self.use_color:
            return text
        return f"\033[{code}m{text}\033[0m"

    def _tag(self) -> str:
        return self._styled(f"[{self.prefix}]", COLOR_CODES.get(self.prefix, "37"))

    def line(self, text: str = "") -> None:
        if self.quiet:
            return
        print(f"{self._tag():<{self.TAG_WIDTH + 9}} {text}", file=self.stream, flush=True)

    def section_break(self) -> None:
        self.line(self._styled("─" * 73, "2"))

    def step(self, n: int, total: int, description: str) -> None:
        self.line()
        self.line(self._styled(f"STEP {n}/{total}: {description}", "1"))

    def kv(self, key: str, value: Any) -> None:
        self.line(f"  {key:<22} {value}")

    def kv_block(self, header: str, kvs: dict) -> None:
        self.line(header)
        for k, v in kvs.items():
            self.line(f"    {k:<10} {v}")

    def request(self, method: str, url: str, *, body_summary: str | None = None) -> None:
        arrow = self._styled("→", "2")
        self.line(f"  {arrow} {method} {url}")
        if body_summary is not None:
            self.line(f"    body: {body_summary}")

    def response(self, status: int, reason: str, *, ms: int | None = None) -> None:
        arrow = self._styled("←", "2")
        suffix = f"  (took {ms}ms)" if ms is not None else ""
        self.line(f"  {arrow} {status} {reason}{suffix}")

    def headers(self, headers: dict[str, str], *, only_prefix: str | None = None) -> None:
        self.line("    headers:")
        for k, v in headers.items():
            if only_prefix and not k.lower().startswith(only_prefix.lower()):
                continue
            self.line(f"      {k:<22} {v}")

    def body(self, label: str, body: dict | str) -> None:
        self.line(f"    {label}")
        if isinstance(body, str):
            self.line(f"      {body}")
            return
        self._render_json(body, indent=6)

    def _render_json(self, obj: Any, indent: int) -> None:
        pad = " " * indent
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    self.line(f"{pad}{k}:")
                    self._render_json(v, indent + 2)
                else:
                    self.line(f"{pad}{k}: {v}")
        elif isinstance(obj, list):
            for item in obj:
                self.line(f"{pad}- {item}")
        else:
            self.line(f"{pad}{obj}")

    def hex_dump(self, label: str, data: bytes) -> None:
        self.line(f"  {label} ({len(data)} bytes, hex):")
        for i in range(0, len(data), 16):
            chunk = data[i:i + 16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            self.line(f"    {hex_part}")

    def ok(self, text: str) -> None:
        self.line(self._styled(f"  ✓ {text}", COLOR_CODES["ok"]))

    def fail(self, text: str) -> None:
        self.line(self._styled(f"  ✗ {text}", COLOR_CODES["error"]))


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BuyResult:
    success: bool
    payload: dict | None = None
    quorum_size: int | None = None
    elapsed_ms: int | None = None
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Bootstrap (account registration)
# ---------------------------------------------------------------------------

def do_bootstrap(
    facilitator_client: httpx.Client,
    wallet: Wallet,
    *,
    initial_balance: int = 10000,
    narrator: Narrator,
) -> dict:
    """Register the agent's account if not already present, then return its
    current state ({account_id, pubkey_b64, balance, nonce}).

    register-account is idempotent on (account_id, pubkey), so re-running the
    agent against an already-known account is a quick no-op on the validator
    side.
    """
    narrator.line(
        f"POST /debug/register-account  account_id={wallet.account_id}  "
        f"balance={initial_balance}"
    )
    resp = facilitator_client.post("/debug/register-account", json={
        "account_id": wallet.account_id,
        "pubkey_b64": wallet.pubkey_b64,
        "balance": initial_balance,
    })
    if resp.status_code not in (200, 201):
        narrator.fail(f"register-account failed: {resp.status_code} {resp.text}")
        raise SystemExit(2)
    body = resp.json()
    narrator.line(
        f"← {resp.status_code}  balance={body['balance']}  nonce={body['nonce']}"
    )
    return body


# ---------------------------------------------------------------------------
# Buy flow -- narrated step by step
# ---------------------------------------------------------------------------

def run_buy(
    *,
    api_client: httpx.Client,
    facilitator_client: httpx.Client,
    wallet: Wallet,
    api_url_for_display: str,
    facilitator_url_for_display: str,
    narrator: Narrator,
) -> BuyResult:
    t_start = time.perf_counter_ns()
    narrator.section_break()

    # ------------------------------------------------------------- step 1
    narrator.step(1, 7, "Initial request — discover payment requirements")
    narrator.request("GET", f"{api_url_for_display}/resource")
    resp = api_client.get("/resource")
    narrator.response(resp.status_code, resp.reason_phrase)
    if resp.status_code != 402:
        narrator.fail(f"expected 402 Payment Required, got {resp.status_code}")
        return BuyResult(success=False, failure_reason=f"unexpected status {resp.status_code}")
    narrator.headers(dict(resp.headers), only_prefix="X-Payment")
    requirements = resp.json()
    narrator.body("body:", requirements)
    advertised_hash = resp.headers.get("X-Payment-Payload-Hash", "")
    pay_recipient = requirements["recipient"]
    pay_amount = int(requirements["amount"])

    # ------------------------------------------------------------- step 2
    narrator.step(2, 7, "Discover my current nonce")
    narrator.request("GET", f"{facilitator_url_for_display}/account/{wallet.account_id}")
    resp = facilitator_client.get(f"/account/{wallet.account_id}")
    narrator.response(resp.status_code, resp.reason_phrase)
    if resp.status_code != 200:
        narrator.fail(f"failed to read account: {resp.status_code} {resp.text}")
        return BuyResult(success=False, failure_reason=f"account read failed: {resp.status_code}")
    account = resp.json()
    narrator.kv("account_id:", account["account_id"])
    narrator.kv("pubkey_b64:", account["pubkey_b64"])
    narrator.kv("balance:",    account["balance"])
    narrator.kv("nonce:",      account["nonce"])
    nonce = account["nonce"]

    # ------------------------------------------------------------- step 3
    narrator.step(3, 7, "Build and sign claim")
    claim = create_claim(
        wallet.account_id, pay_recipient, pay_amount, nonce,
        wallet.verify_key, wallet.signing_key,
    )
    narrator.line("  claim:")
    narrator.line(f"    sender:    {claim.sender}")
    narrator.line(f"    recipient: {claim.recipient}")
    narrator.line(f"    amount:    {claim.amount}")
    narrator.line(f"    nonce:     {claim.nonce}")
    narrator.hex_dump("canonical payload", claim.payload())
    narrator.kv("sender_pubkey:", f"{wallet.pubkey_b64}  (32 bytes)")
    narrator.kv("signature:",     f"{_b64encode(claim.signature)}  (64 bytes)")

    # ------------------------------------------------------------- step 4
    narrator.step(4, 7, "Submit claim to facilitator for quorum settlement")
    settle_body = {
        "sender":        claim.sender,
        "recipient":     claim.recipient,
        "amount":        claim.amount,
        "nonce":         claim.nonce,
        "sender_pubkey": wallet.pubkey_b64,
        "signature":     _b64encode(claim.signature),
    }
    narrator.request("POST", f"{facilitator_url_for_display}/settle",
                     body_summary="{ sender, recipient, amount, nonce, sender_pubkey, signature }")
    t0 = time.perf_counter_ns()
    resp = facilitator_client.post("/settle", json=settle_body)
    settle_ms = (time.perf_counter_ns() - t0) // 1_000_000
    narrator.response(resp.status_code, resp.reason_phrase, ms=settle_ms)
    if resp.status_code != 200:
        narrator.fail(f"/settle returned {resp.status_code}: {resp.text}")
        return BuyResult(success=False, failure_reason=f"/settle failed: {resp.status_code}")

    settle_result = resp.json()
    narrator.kv("quorum_met:",       settle_result["quorum_met"])
    narrator.kv("success_count:",    settle_result["success_count"])
    quorum_threshold = (
        settle_result["payment_proof"]["quorum_threshold"]
        if settle_result.get("payment_proof") else "n/a"
    )
    narrator.kv("quorum_threshold:", quorum_threshold)
    narrator.kv("rejections:",       settle_result["rejections"] or "{}")
    narrator.kv("dead:",             settle_result["dead"] or "[]")
    narrator.kv("faults:",           settle_result["faults"] or "[]")

    if not settle_result["quorum_met"]:
        narrator.fail("quorum not met -- cannot acquire resource")
        return BuyResult(success=False, failure_reason="quorum not met")

    narrator.line("  certificates:")
    for vid, cert in settle_result["certificates"].items():
        narrator.line(f"    [{vid}]")
        narrator.line(f"      pubkey:    {cert['validator_pubkey']}  (32 bytes)")
        narrator.line(f"      signature: {cert['validator_signature']}  (64 bytes)")

    proof = settle_result["payment_proof"]
    narrator.line("  payment_proof (assembled by facilitator):")
    narrator.kv("  claim_digest:",     proof["claim_digest"])
    narrator.kv("  success_count:",    proof["success_count"])
    narrator.kv("  quorum_threshold:", proof["quorum_threshold"])

    # ------------------------------------------------------------- step 5
    narrator.step(5, 7, "Encode proof for the X-Payment-Proof header")
    proof_json = json.dumps(proof)
    proof_b64 = _b64encode(proof_json.encode())
    narrator.kv("serialized JSON:", f"{len(proof_json)} bytes")
    narrator.kv("base64 header:",   f"{len(proof_b64)} bytes")
    preview = proof_b64[:128] + ("..." if len(proof_b64) > 128 else "")
    narrator.line(f"  preview: {preview}")

    # ------------------------------------------------------------- step 6
    narrator.step(6, 7, "Retry GET /resource with the proof")
    narrator.request("GET", f"{api_url_for_display}/resource")
    narrator.line(f"    X-Payment-Proof: <{len(proof_b64)} bytes, see step 5>")
    t0 = time.perf_counter_ns()
    resp = api_client.get("/resource", headers={"X-Payment-Proof": proof_b64})
    retry_ms = (time.perf_counter_ns() - t0) // 1_000_000
    narrator.response(resp.status_code, resp.reason_phrase, ms=retry_ms)
    if resp.status_code != 200:
        narrator.fail(f"/resource returned {resp.status_code}: {resp.text}")
        return BuyResult(success=False, failure_reason=f"/resource retry failed: {resp.status_code}")
    narrator.headers(dict(resp.headers), only_prefix="X-Payment")
    paid = resp.json()
    narrator.body("body:", paid)

    # ------------------------------------------------------------- step 7
    narrator.step(7, 7, "Verify payload integrity against advertised hash")
    payload_to_hash = paid["data"]
    computed_hash = hashlib.sha256(json.dumps(payload_to_hash, sort_keys=True).encode()).hexdigest()
    narrator.kv("computed sha256:",  computed_hash)
    narrator.kv("hash from step 1:", advertised_hash)
    if computed_hash == advertised_hash:
        narrator.ok("payload matches advertised hint -- server didn't substitute the goods")
    else:
        narrator.fail("payload hash MISMATCH -- server returned different content than advertised")
        return BuyResult(success=False, failure_reason="payload hash mismatch")

    # -------------------------------------------------------------------
    elapsed_ms = (time.perf_counter_ns() - t_start) // 1_000_000
    quorum_size = settle_result["success_count"]
    narrator.line()
    narrator.section_break()
    narrator.line(narrator._styled(
        f"BUY COMPLETE   paid {pay_amount} to {pay_recipient}   "
        f"quorum {quorum_size}/{quorum_threshold}   end-to-end: {elapsed_ms}ms",
        COLOR_CODES["ok"],
    ))

    return BuyResult(
        success=True,
        payload=paid,
        quorum_size=quorum_size,
        elapsed_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli.agent_client",
        description="Customer agent CLI for the agentic-settlement system.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-url", default="http://localhost:8000",
                        help="Base URL of api_server (default: http://localhost:8000)")
    common.add_argument("--facilitator-url", default="http://localhost:8001",
                        help="Base URL of facilitator_server (default: http://localhost:8001)")
    common.add_argument("--as", dest="account_id", default=None,
                        help="Override the agent account_id used on first run")
    common.add_argument("--initial-balance", type=int, default=10000,
                        help="Initial balance to seed the account with (only on first registration)")
    common.add_argument("--quiet", action="store_true", help="Suppress narration; print only result line")
    common.add_argument("--no-color", action="store_true", help="Disable ANSI color codes")

    sub.add_parser("setup", parents=[common],
                   help="Generate keypair if needed and register with facilitator. Then exit.")
    sub.add_parser("buy", parents=[common],
                   help="Bootstrap if needed, then run the full x402 buy flow.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    use_color = (not args.no_color) and sys.stderr.isatty()

    wallet_n = Narrator("wallet",    use_color=use_color, quiet=args.quiet)
    boot_n   = Narrator("bootstrap", use_color=use_color, quiet=args.quiet)
    buy_n    = Narrator("buy",       use_color=use_color, quiet=args.quiet)

    # ---- wallet
    path = wallet_path()
    wallet, was_generated = load_or_generate(path, account_id=args.account_id)
    if was_generated:
        wallet_n.line(f"generated keypair, account_id={wallet.account_id}")
        wallet_n.line(f"saved to {path}")
    else:
        wallet_n.line(f"loaded key from {path}")
        wallet_n.line(f"account_id={wallet.account_id}")

    # ---- HTTP clients
    api_client = httpx.Client(base_url=args.api_url, timeout=10.0)
    facilitator_client = httpx.Client(base_url=args.facilitator_url, timeout=10.0)

    try:
        # ---- bootstrap
        do_bootstrap(facilitator_client, wallet,
                     initial_balance=args.initial_balance, narrator=boot_n)

        if args.cmd == "setup":
            return 0

        # ---- buy
        result = run_buy(
            api_client=api_client,
            facilitator_client=facilitator_client,
            wallet=wallet,
            api_url_for_display=args.api_url,
            facilitator_url_for_display=args.facilitator_url,
            narrator=buy_n,
        )
        return 0 if result.success else 1
    finally:
        api_client.close()
        facilitator_client.close()


if __name__ == "__main__":
    raise SystemExit(main())
