"""Generate a fresh dev EVM keypair for the x402 latency benchmark.

Prints the address and private key. Copy the key into .env as
EVM_PRIVATE_KEY=0x... before running the smoke test or bench.

This is a throwaway dev wallet. Do NOT reuse with mainnet funds beyond
the small float needed for the benchmark.
"""

from eth_account import Account


def main() -> None:
    # secrets.token_bytes(32) under the hood -> secp256k1 private key -> address.
    acct = Account.create()
    print("address:    ", acct.address)
    print("private_key:", acct.key.hex())
    print()
    print("Next: add this to .env as")
    print(f"  EVM_PRIVATE_KEY={acct.key.hex()}")
    print()
    print("Then fund Base Sepolia USDC at https://faucet.circle.com")
    print(f"  (paste address: {acct.address})")


if __name__ == "__main__":
    main()
