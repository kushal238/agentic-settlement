"""Customer agent CLI for the agentic-settlement system.

Subcommands:
  setup   -- generate keypair if needed, register with facilitator, exit.

Run `python -m cli.agent_client setup --help` for flags.

Design notes:
  - Speaks only HTTP. Knows nothing about validators internally.
  - Verbose by default for teaching; --quiet for piping.
  - do_bootstrap() takes injected httpx.Client objects so tests can drive
    it against in-process apps via httpx.ASGITransport.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from cli.wallet import Wallet, load_or_generate, wallet_path


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

    def ok(self, text: str) -> None:
        self.line(self._styled(f"✓ {text}", COLOR_CODES["ok"]))

    def fail(self, text: str) -> None:
        self.line(self._styled(f"✗ {text}", COLOR_CODES["error"]))


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

    /debug/register-account is idempotent on (account_id, pubkey), so re-running
    against an already-known account is a quick no-op on the validator side.
    Returns 409 only if the account_id already exists with a different pubkey,
    which we surface as a fatal error -- the agent's identity is its key.
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    use_color = (not args.no_color) and sys.stderr.isatty()

    wallet_n = Narrator("wallet",    use_color=use_color, quiet=args.quiet)
    boot_n   = Narrator("bootstrap", use_color=use_color, quiet=args.quiet)

    # ---- wallet
    path = wallet_path()
    wallet, was_generated = load_or_generate(path, account_id=args.account_id)
    if was_generated:
        wallet_n.line(f"generated keypair, account_id={wallet.account_id}")
        wallet_n.line(f"saved to {path}")
    else:
        wallet_n.line(f"loaded key from {path}")
        wallet_n.line(f"account_id={wallet.account_id}")

    # ---- HTTP client (only need facilitator for bootstrap)
    facilitator_client = httpx.Client(base_url=args.facilitator_url, timeout=10.0)

    try:
        do_bootstrap(facilitator_client, wallet,
                     initial_balance=args.initial_balance, narrator=boot_n)
        if args.cmd == "setup":
            boot_n.ok("setup complete")
            return 0
    finally:
        facilitator_client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
