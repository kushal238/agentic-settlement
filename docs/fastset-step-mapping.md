# FastSet seven-step mapping (this codebase)

This document ties the [FastSet protocol lifecycle](https://docs.fast.xyz/advanced/fastset-protocol) (as described in public Fast documentation) to modules in **agentic-settlement**, and calls out what is implemented versus planned.

## Parameterization: `3f+1` validators, `2f+1` quorum

This project uses the standard FastSet/FastPay parameterization: **`n = 3f+1`** validators tolerating up to **`f`** Byzantine faults, with a quorum of **`2f+1`** valid certificates. The facilitator waits until every validator has either responded or timed out before evaluating quorum.

## The seven steps (Fast docs) and this repo

| Step | Name (Fast docs) | Implemented here | Notes / future work |
|------|-------------------|------------------|---------------------|
| 1 | Transaction / claim creation | [`create_claim`](../src/core/claim.py), [`Claim`](../src/core/claim.py) | Client signs a canonical payload (length-prefixed fields). Future: batch several claims in one transaction `⟨c₁, …, cₖ, nonce⟩` if required. |
| 2 | Verification (optional) | Not implemented | Future: optional verifiers sign the transaction; aggregate proofs; enforce verifier quorum before validators see the claim. |
| 3 | Validation | [`Validator.verify_and_certify`](../src/core/validator.py) | Checks sender signature, accounts, nonce, pending slot, amount, balance (mirrors the doc’s validation bullets). |
| 4 | Validator signature | [`Certificate`](../src/core/validator.py) | Each accepting validator signs the claim payload and records pending state for the sender. |
| 5 | Certificate / quorum assembly | [`Facilitator.submit_claim`](../src/core/facilitator.py), [`evaluate_round`](../src/core/facilitator.py) | Collects outcomes from **`3f+1`** endpoints, verifies validator signatures, handles duplicates/faults, requires **`2f+1`** valid certificates for quorum. Fast docs describe a **proxy** assembling one quorum proof; here the facilitator keeps a **set of per-validator certificates** (no aggregate signature) as a deliberate simplification. Future: optional aggregated certificate object. |
| 6 | Pre-settlement | Not implemented | Future: broadcast quorum proof to every validator; move the transaction into a **presettled** queue respecting nonce ordering across the pipeline. |
| 7 | Settlement | [`Validator.settle`](../src/core/validator.py), [`Facilitator.submit_and_settle`](../src/core/facilitator.py) | Applies balances and nonce, clears pending. The facilitator drives settlement on every signing validator once quorum is reached; validators that rejected or timed out are intentionally left divergent until a future sync path reconciles them. |

## End-to-end flow (target shape, f=1 so n=4)

The diagram below mirrors the layout of the [x402 flow diagram](https://github.com/x402-foundation/x402#typical-x402-flow) and shows the full intended pay-to-unlock path. Solid lanes that are implemented today: **Client**, **Facilitator**, **Validators**. The **Resource Server** lane and the x402 `402 Payment Required` / `X-PAYMENT` retry handshake are **planned** -- today the `Client` calls the `Facilitator` in-process.

```mermaid
sequenceDiagram
  autonumber
  participant C as Client (AI Agent)
  participant S as Resource Server
  participant F as Facilitator
  participant V as Validators (n = 3f+1)

  C->>S: GET /resource
  S-->>C: 402 Payment Required<br/>(price, recipient, facilitator)
  Note over C: Build & sign Claim<br/>(sender, recipient, amount, nonce)
  C->>F: submit_and_settle(claim)
  F->>V: verify_and_certify(claim) — fan-out to all 3f+1
  V-->>F: Certificates / Rejections
  Note over F: evaluate_round<br/>dedupe, detect faults,<br/>check quorum ≥ 2f+1
  F->>V: settle(claim) — signing validators only
  Note over V: non-signers (rejected / dead)<br/>diverge until future step-6 catch-up
  F-->>C: FacilitatorResult<br/>(quorum_met, certificates, rejections, dead, faults)
  C->>S: GET /resource<br/>X-PAYMENT: quorum proof
  S->>F: verify payment (optional)
  F-->>S: OK
  S-->>C: 200 OK + resource
```

Each validator's internal check inside `verify_and_certify` is: sender signature valid, sender pubkey matches account owner, nonce matches, no pending claim for this sender, amount positive, balance sufficient. Inside `settle`: debit sender, credit recipient, increment sender nonce, clear pending slot.

## References

- Fast documentation: [FastSet Protocol](https://docs.fast.xyz/advanced/fastset-protocol)
- Formal treatment: [FastSet whitepaper (arXiv)](https://arxiv.org/abs/2506.23395)
