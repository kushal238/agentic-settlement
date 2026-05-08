"""Benchmark end-to-end x402 settlement latency from an agent's perspective.

Measures wall-clock from "agent issues paid request" to "agent has the resource".
No phase decomposition, no chain receipt polling. One number per trial.

Usage:
    .venv/bin/python bench/x402/bench_x402.py --network base-sepolia --trials 30
    .venv/bin/python bench/x402/bench_x402.py --network base          --trials 20

Outputs:
    bench/x402/results/x402_<network>_<UTC-timestamp>.csv  (per-trial rows)
    Summary printed to stdout (cold first trial + p50/p95/p99/mean/stddev).
"""

import argparse
import asyncio
import csv
import os
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from x402 import x402Client
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client


# Same merchant, different chain — Sepolia for safety, mainnet for the headline.
URLS = {
    "base-sepolia": "https://x402.payai.network/api/base-sepolia/paid-content",
    "base":         "https://x402.payai.network/api/base/paid-content",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--network", choices=sorted(URLS), required=True)
    p.add_argument("--trials", type=int, default=30)
    p.add_argument("--jitter-ms", type=int, default=300,
                   help="approx delay between trials to avoid nonce/rate collisions")
    return p.parse_args()


async def run_trial(http: x402HttpxClient, url: str) -> tuple[int, float]:
    # perf_counter_ns: monotonic, immune to wall-clock adjustments — right tool for latency.
    t0 = time.perf_counter_ns()
    r = await http.get(url)
    await r.aread()  # don't stop the clock until the body is fully in hand.
    t1 = time.perf_counter_ns()
    return r.status_code, (t1 - t0) / 1e6


def summarize(results: list[tuple[int, int, float]]) -> None:
    if not results:
        print("no results")
        return
    # First trial pays TLS handshake + DNS + cold connection pool — report it, exclude from stats.
    cold = results[0]
    warm = [r for r in results[1:] if r[1] == 200]
    failures = [r for r in results if r[1] != 200]

    print()
    print(f"trials:   {len(results)}  (cold first trial reported separately)")
    print(f"failures: {len(failures)}  ({[r[1] for r in failures]})")
    print(f"cold (trial 0): status={cold[1]}  e2e_ms={cold[2]:.1f}")

    if not warm:
        print("no successful warm trials")
        return

    ms = [r[2] for r in warm]
    ms_sorted = sorted(ms)

    def pct(p: float) -> float:
        # nearest-rank percentile — simple, no interpolation games.
        k = max(0, min(len(ms_sorted) - 1, int(round(p / 100 * len(ms_sorted))) - 1))
        return ms_sorted[k]

    print(f"warm successes: n={len(warm)}")
    print(f"  mean   {statistics.mean(ms):8.1f} ms")
    print(f"  stddev {statistics.pstdev(ms):8.1f} ms")
    print(f"  min    {min(ms):8.1f} ms")
    print(f"  p50    {pct(50):8.1f} ms")
    print(f"  p95    {pct(95):8.1f} ms")
    print(f"  p99    {pct(99):8.1f} ms")
    print(f"  max    {max(ms):8.1f} ms")


def write_csv(network: str, results: list[tuple[int, int, float]]) -> Path:
    out_dir = Path(__file__).resolve().parent / "results"  # bench/x402/results/
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"x402_{network}_{ts}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trial_idx", "status", "e2e_ms"])
        w.writerows(results)
    return path


async def main() -> None:
    args = parse_args()
    load_dotenv()
    pk = os.environ.get("EVM_PRIVATE_KEY")
    if not pk:
        raise SystemExit("EVM_PRIVATE_KEY not set. See .env.example.")

    url = URLS[args.network]
    print(f"network: {args.network}")
    print(f"target:  {url}")
    print(f"trials:  {args.trials}")

    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(Account.from_key(pk)))

    results: list[tuple[int, int, float]] = []
    async with x402HttpxClient(client) as http:
        for i in range(args.trials):
            try:
                status, e2e_ms = await run_trial(http, url)
            except Exception as e:
                # Don't kill the run on a single failure — record and continue.
                print(f"  trial {i:3d}: ERROR {type(e).__name__}: {e}")
                results.append((i, -1, -1.0))
                continue
            print(f"  trial {i:3d}: status={status} e2e_ms={e2e_ms:8.1f}")
            results.append((i, status, e2e_ms))
            if i < args.trials - 1:
                # Small jitter so we don't slam the merchant or race nonces.
                jitter = (args.jitter_ms + random.randint(-50, 50)) / 1000
                await asyncio.sleep(max(0, jitter))

    path = write_csv(args.network, results)
    summarize(results)
    print(f"\nwrote: {path}")


if __name__ == "__main__":
    asyncio.run(main())
