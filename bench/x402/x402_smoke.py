"""Single real x402 paid request — proves the SDK + wallet + facilitator flow works.

Hits the PayAI echo merchant on Base Sepolia. Expected: HTTP 200 + paid content.
The merchant refunds the payment, so this is effectively free over many runs.

Usage:
    .venv/bin/python bench/x402/x402_smoke.py
"""

import asyncio
import os

from dotenv import load_dotenv
from eth_account import Account
from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client


# PayAI echo merchant: charges, settles, then immediately refunds.
URL = "https://x402.payai.network/api/base-sepolia/paid-content"


async def main() -> None:
    load_dotenv()
    pk = os.environ.get("EVM_PRIVATE_KEY")
    if not pk:
        raise SystemExit("EVM_PRIVATE_KEY not set. See .env.example.")

    # x402Client is the protocol brain: it knows how to read 402 challenges
    # and dispatch to a registered "mechanism" (chain + scheme) to sign payment.
    client = x402Client()

    # Register: when a 402 says "pay USDC on EVM via the 'exact' scheme",
    # use this Eth account to sign EIP-3009 transferWithAuthorization payloads.
    register_exact_evm_client(client, EthAccountSigner(Account.from_key(pk)))

    # x402HttpxClient wraps httpx so a normal-looking GET transparently:
    #   1) sends the request, 2) catches 402, 3) signs payment, 4) retries with X-PAYMENT.
    async with x402HttpxClient(client) as http:
        r = await http.get(URL)
        await r.aread()
        print(f"status: {r.status_code}")
        print(f"body:   {r.text[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
