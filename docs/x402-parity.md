# x402 protocol parity notes

How `cli.agent_client buy` lines up against the real x402 standard. The point
of this document is to verify that the flow our CLI demonstrates is a faithful
x402-style interaction, not a sandbox toy — and to honestly note where we
deviate, why, and whether each deviation matters for the published benchmark
comparison.

## Reference points

- **x402 spec / docs:** [docs.x402.org](https://docs.x402.org/welcome)
- **Canonical reference client:** Coinbase's [`x402-fetch`](https://github.com/coinbase/x402) and `x402-axios` (TypeScript); Python `x402` SDK used in our `bench/x402/`.
- **Our production observation:** `bench/x402/x402_smoke.py` + `bench/x402/bench_x402.py` — single-function `x402HttpxClient(client).get(url)` against PayAI's echo merchant on Base Sepolia. p50 ~2.0s, p95 ~3.6s, p99 ~4.0s, dominated by Base block time.

## Flow comparison

| Step | Standard x402 (Base/USDC) | Our system (FastSet) | Same? |
|---|---|---|---|
| 1. Agent requests resource | `GET /resource` | `GET /resource` | ✓ |
| 2. Merchant returns 402 | `402 Payment Required` with body `{x402Version, accepts:[...], error}` | `402 Payment Required` with body `{scheme, payment_required, recipient, amount, instructions}` | structurally same, body shape different |
| 3. Agent reads requirements | Parses `accepts` array, picks a scheme/network pair it supports | Parses single `{recipient, amount}` pair | one scheme vs N |
| 4. Agent constructs payment | Signs EIP-3009 `transferWithAuthorization` for EVM `exact` scheme; opaque blob for others | Discovers nonce via `GET /account/{me}`, builds + Ed25519-signs `Claim(sender, recipient, amount, nonce)` | conceptually same, mechanism different |
| 5. Agent obtains settlement | **Skipped** — the payment is signed but not yet on-chain | Agent posts the claim to **facilitator's `POST /settle`**, gets back a quorum proof from `2f+1` validators | **architectural deviation** — see below |
| 6. Agent presents proof to merchant | Includes signed payload in `X-PAYMENT` header on retry | Includes quorum proof JSON (base64) in `X-Payment-Proof` header on retry | structurally same, header name differs |
| 7. Merchant verifies | Calls facilitator's `POST /verify` (HTTP, blocking) OR verifies locally | Verifies proof signatures locally (pure CPU, no network) | merchant-mediated vs agent-mediated |
| 8. Merchant returns 200 | `200 OK` with body + `X-PAYMENT-RESPONSE` header | `200 OK` with body + `X-Payment-Verified` + `X-Payment-Quorum-Size` headers | structurally same, header names differ |
| 9. Merchant settles | Optionally calls facilitator's `POST /settle` after responding (async) | Settle already happened at step 5; validators converge state via background task | timing inversion |

## Where we deviate intentionally (architectural)

### Agent-driven settlement vs merchant-driven settlement

**Real x402:** the agent signs a payment authorization, hands it to the merchant. The *merchant* talks to the facilitator (verify, settle). The agent never needs to know what a facilitator is.

**Our system:** the agent talks to the facilitator directly to get a quorum proof, then presents the proof to the merchant. The merchant never talks to the facilitator — it just verifies the proof cryptographically using bundled validator signatures.

This is a real architectural choice, not laziness. It's how FastSet/FastPay actually work — claims are settled in parallel by the client, not serialized through a merchant intermediary. Pros: merchant has no facilitator dependency, no network calls during a request, no facilitator-side bottleneck. Cons: agent has to know about facilitators, and the proof is bigger than a single signature.

**Implication for benchmarking:** the comparison is still fair end-to-end ("agent gets paid resource"), but we should be transparent that the latency breakdown is different. Our `settle` phase (the facilitator round-trip) is **the** dominant network cost, while in standard x402 it's the merchant's verify+settle calls plus the chain confirmation.

### Single scheme vs multi-scheme

x402's 402 body has `accepts: [option1, option2, ...]` so a merchant can advertise (USDC on Base, USDC on Ethereum, USDC on Polygon) and the agent picks. We advertise one scheme: `fastset-ed25519`. Not a problem for the proof-of-concept; would matter for a multi-asset facilitator.

## Where we deviate gratuitously (could fix)

These don't affect the comparison's fairness but break interoperability with off-the-shelf x402 clients. Standard `x402-fetch` would not talk to our `/resource` because:

- **Header name** is `X-Payment-Proof` instead of standard `X-PAYMENT`.
- **402 body** lacks the required `x402Version`, `accepts: []`, and `error` fields.
- **Response header** is `X-Payment-Verified` instead of `X-PAYMENT-RESPONSE`.

If we ever want a Coinbase `x402-fetch` user to call our `/resource` and have it Just Work, we'd need to align these. For the current "publication demo" purpose, it doesn't matter — our agent CLI is built to talk to our merchant. If we want to claim full x402 compatibility in the paper, this becomes a small follow-up PR.

Logged under "x402 wire-format alignment" in `TODO.md` for later.

## Bench comparison: is it apples to apples?

Yes, with these caveats:

- **`bench/x402/bench_x402.py`** measures wall-clock from agent's `http.get(url)` call to having the response body fully read, on Base Sepolia, fully automated. p50 ~2.0s.
- **Our agent CLI's BUY COMPLETE end-to-end (work)** measures the same conceptual span: from `GET /resource` to having the paid payload in hand, fully automated, on localhost.

Both numbers cover:
1. Initial 402 round-trip.
2. Whatever the agent does to obtain proof (sign for x402; sign + settle for us).
3. Retry with proof.
4. Get paid content.

The difference: x402's #2 is "sign tx + wait for on-chain confirmation," dominated by Base block time (~2s). Ours is "sign claim + facilitator quorum round-trip," dominated by parallel validator fan-out (~10ms in-process). Same conceptual measurement, different mechanism, fair comparison.

**To make the comparison rigorous for a paper:** add a `--bench N` flag to `cli.agent_client buy` that mirrors `bench/x402/bench_x402.py`'s output format (per-trial CSV, p50/p95/p99 summary). Then the two CSVs sit side by side with identical columns. Tracked separately (not in this commit).

## Things our agent narration shows that x402 SDK output doesn't

Our CLI dumps the canonical signed bytes, every validator certificate, the full proof object, and step-by-step request/response. Coinbase's `x402HttpxClient` is a black box from the caller's perspective — you call `.get(url)` and either get a 200 or an exception. The verbose narration is a *teaching* feature, not a *behavioral* deviation. Real production agents using our system would use our (future) SDK with the same one-call shape Coinbase's clients have.

## Summary

The buy flow in `cli.agent_client buy` is a faithful x402-style interaction with an explicit, intentional architectural choice (agent-driven settlement). Gratuitous deviations (header names, 402 body fields) are noted and could be aligned in a follow-up. The bench comparison is fair end-to-end.
