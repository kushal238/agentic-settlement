# FastAPI Server Plan: x402 Agentic Payment Flow

## Overview

This document describes the design for two FastAPI servers that expose the existing
`agentic-settlement` core library over HTTP, implementing the
[x402 payment protocol](https://www.x402.org/) to gate access to valuable information
behind a cryptographic settlement flow.

```
┌─────────────┐   (1) GET /resource       ┌──────────────────┐
│             │ ──────────────────────────▶│                  │
│   Agent     │   (2) 402 + requirements   │   API Server     │
│  (client)   │ ◀──────────────────────── │  (resource srv)  │
│             │   (3) GET + Claim+Sig      │                  │
│             │ ──────────────────────────▶│                  │
└─────────────┘                            └────────┬─────────┘
                                                    │ (4) POST /settle  (signed Claim)
                                                    ▼
                                           ┌──────────────────┐
                                           │  Facilitator Srv │
                                           │                  │
                                           │  broadcasts to   │
                                           │  3f+1 validators │
                                           │  collects certs  │
                                           │  checks quorum   │
                                           └────────┬─────────┘
                                                    │ (5) QuorumResult
                                                    ▼
                                           ┌──────────────────┐
                                           │   API Server     │
                                           │  releases info   │─▶ (6) 200 + payload
                                           └──────────────────┘
```

---

## Service Boundaries

| Service | Role | Port (default) |
|---------|------|----------------|
| **API Server** | Receives agent requests; issues 402; verifies quorum certificate; serves valuable information | `8000` |
| **Facilitator Server** | Accepts signed claims; fans out to validators; assembles quorum certificate; returns result | `8001` |
| **Validators** (n = 3f+1) | In-process or remote; wrapped behind `ValidatorClient` interface already defined in `facilitator.py` | n/a (in-process for v1) |

---

## Directory Layout

```
agentic-settlement/
├── src/
│   ├── core/                         # existing (untouched)
│   │   ├── account.py
│   │   ├── claim.py
│   │   ├── crypto.py
│   │   ├── facilitator.py
│   │   └── validator.py
│   ├── api_server/
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI app entry point
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── resource.py           # GET /resource  (402 gate)
│   │   │   └── health.py             # GET /health
│   │   ├── models.py                 # Pydantic request/response models
│   │   ├── payment_requirements.py   # Builds 402 header+body
│   │   └── config.py                 # Env vars: price, facilitator URL, key paths
│   └── facilitator_server/
│       ├── __init__.py
│       ├── main.py                   # FastAPI app entry point
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── settle.py             # POST /settle
│       │   └── health.py             # GET /health
│       ├── models.py                 # Pydantic request/response models
│       ├── node_registry.py          # Loads validator set from config
│       └── config.py                 # Env vars: f, validator addresses, timeouts
├── docs/
│   ├── fastset-step-mapping.md
│   └── fastapi-server-plan.md        # this file
├── requirements.txt                  # add: fastapi, uvicorn, httpx, pydantic
└── tests/
    ├── test_api_server.py
    └── test_facilitator_server.py
```

---

## x402 Protocol Flow (Step by Step)

### Step 1 — Agent makes unauthenticated request

```
GET /resource HTTP/1.1
Host: api-server:8000
```

The agent does not yet include any payment headers.

---

### Step 2 — API Server responds with 402

The API server checks for the absence of a `X-Payment-Claim` header and returns:

```
HTTP/1.1 402 Payment Required
Content-Type: application/json
X-Payment-Version: 1
X-Payment-Recipient: <recipient_account_id>
X-Payment-Amount: <integer, e.g. 10>
X-Payment-Nonce: <current nonce hint, optional>
X-Payment-Payload-Hash: <sha256 of the valuable payload, so client can verify later>

{
  "payment_required": true,
  "version": "1",
  "recipient": "<account_id>",
  "amount": 10,
  "scheme": "fastset-ed25519",
  "instructions": "Attach X-Payment-Claim and X-Payment-Signature headers with your signed Claim."
}
```

The `X-Payment-Payload-Hash` lets the agent verify integrity of the information it
eventually receives without needing to trust the server blindly.

---

### Step 3 — Agent constructs and attaches a signed Claim

Using the `create_claim` factory from `src/core/claim.py`, the agent:

1. Builds a `Claim` with the correct `recipient`, `amount`, and its current `nonce`.
2. Signs the canonical length-prefixed payload with its Ed25519 signing key.
3. Encodes the claim fields as JSON / base64 and attaches them as headers:

```
GET /resource HTTP/1.1
Host: api-server:8000
X-Payment-Claim: <base64-encoded JSON claim fields>
X-Payment-Signature: <base64-encoded Ed25519 signature>
```

Alternatively, the claim + signature may be sent in the request body if the route
accepts POST (useful for large or complex payloads).

---

### Step 4 — API Server validates headers and forwards to Facilitator Server

The API server:

1. Parses and validates the `X-Payment-Claim` and `X-Payment-Signature` headers
   using `Claim.verify_signature()` (fast local check before network call).
2. If the local signature check fails → return `400 Bad Request`.
3. POSTs the serialized `Claim` to the Facilitator Server's `/settle` endpoint
   (using an async `httpx` client with a configurable timeout).

```
POST http://facilitator:8001/settle HTTP/1.1
Content-Type: application/json

{
  "sender": "...",
  "recipient": "...",
  "amount": 10,
  "nonce": 3,
  "sender_pubkey": "<base64>",
  "signature": "<base64>"
}
```

---

### Step 5 — Facilitator Server drives consensus

Inside the Facilitator Server:

1. Deserialize the JSON body into a `Claim` object (reconstructing the `VerifyKey`
   and signature bytes from base64).
2. Call `Facilitator.submit_and_settle(claim)` which:
   - Fans out `verify_and_certify` to all `3f+1` validators in parallel
     (`ThreadPoolExecutor`, per-validator timeout).
   - Calls `evaluate_round` to count valid `Certificate` objects and detect faults.
   - If quorum (`2f+1`) is met, calls `settle` on each signing validator.
3. Return a `QuorumResult` response.

```json
{
  "quorum_met": true,
  "success_count": 3,
  "certificates": {
    "validator-0": { "validator_id": "...", "validator_signature": "<base64>", ... },
    ...
  },
  "rejections": {},
  "dead": [],
  "faults": []
}
```

If `quorum_met` is `false`, the Facilitator Server returns `200` with the result
body (not a 4xx — the HTTP request succeeded; the settlement did not).

---

### Step 6 — API Server checks quorum and releases information

Back in the API Server:

1. Inspect the `QuorumResult` from the Facilitator Server.
2. **If `quorum_met` is `false`** → return `402 Payment Required` again (or `402`
   with a descriptive body explaining why settlement failed).
3. **If `quorum_met` is `true`**:
   - Retrieve the requested valuable information from the local store / database.
   - Return `200 OK` with the payload.

```
HTTP/1.1 200 OK
Content-Type: application/json
X-Payment-Settled: true
X-Payment-Quorum-Size: 3

{ "data": "<the valuable information>" }
```

---

## Data Models (Pydantic)

### `ClaimRequest` (API Server inbound / Facilitator Server inbound)

```python
class ClaimRequest(BaseModel):
    sender: str
    recipient: str
    amount: int
    nonce: int
    sender_pubkey: str   # base64-encoded Ed25519 VerifyKey
    signature: str       # base64-encoded Ed25519 signature
```

### `QuorumResult` (Facilitator Server outbound)

```python
class CertificateOut(BaseModel):
    validator_id: str
    validator_signature: str   # base64
    validator_pubkey: str      # base64

class FaultEventOut(BaseModel):
    kind: str
    validator_id: str
    detail: str

class QuorumResult(BaseModel):
    quorum_met: bool
    success_count: int
    certificates: dict[str, CertificateOut]
    rejections: dict[str, str]   # validator_id -> reason
    dead: list[str]              # validator_ids that timed out
    faults: list[FaultEventOut]
```

### `PaymentRequirements` (API Server 402 body)

```python
class PaymentRequirements(BaseModel):
    payment_required: bool = True
    version: str = "1"
    recipient: str
    amount: int
    scheme: str = "fastset-ed25519"
    instructions: str
```

---

## API Endpoints

### API Server (`src/api_server/`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/resource` | Main gated endpoint. Returns `402` if no claim; forwards to facilitator and returns `200` + data on quorum success. |
| `GET` | `/health` | Liveness check. |

#### `GET /resource` logic (pseudocode)

```
if X-Payment-Claim header absent:
    return 402 with PaymentRequirements

parse ClaimRequest from headers
if not claim.verify_signature():
    return 400 "Invalid signature"

result = await post_to_facilitator(claim)

if not result.quorum_met:
    return 402 with error detail from QuorumResult

return 200 with valuable_data
```

---

### Facilitator Server (`src/facilitator_server/`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/settle` | Accepts a `ClaimRequest`, runs `submit_and_settle`, returns `QuorumResult`. |
| `GET` | `/health` | Liveness check. |

---

## Configuration

### API Server (`src/api_server/config.py`)

| Variable | Description | Default |
|----------|-------------|---------|
| `API_PORT` | HTTP port | `8000` |
| `FACILITATOR_URL` | Base URL of facilitator server | `http://localhost:8001` |
| `FACILITATOR_TIMEOUT_S` | Total timeout for facilitator call | `10` |
| `PAYMENT_RECIPIENT` | Account ID the agent must pay | required |
| `PAYMENT_AMOUNT` | Price in token units | required |
| `API_SERVER_PRIVKEY_PATH` | Path to server Ed25519 signing key (optional; for future signed responses) | — |

### Facilitator Server (`src/facilitator_server/config.py`)

| Variable | Description | Default |
|----------|-------------|---------|
| `FACILITATOR_PORT` | HTTP port | `8001` |
| `BFT_F` | Fault tolerance `f` (n = 3f+1 validators will be created) | `1` |
| `PER_VALIDATOR_TIMEOUT_S` | Per-validator timeout passed to `FacilitatorConfig` | `2` |
| `VALIDATOR_SEED` | Optional seed for deterministic validator keypairs in dev | — |

---

## Serialization Strategy

The existing `Claim` dataclass uses PyNaCl `VerifyKey` and raw `bytes` for the
signature, neither of which is JSON-serializable. A thin adapter layer is needed:

- **Encoding**: `base64.urlsafe_b64encode(key.encode()).decode()` for keys and
  signatures going over the wire.
- **Decoding**: `VerifyKey(base64.urlsafe_b64decode(s))` when reconstructing inside
  the facilitator server.
- The canonical payload bytes used for signing are produced by
  `Claim.build_payload(...)`, which is deterministic — no re-serialization drift.

---

## Error Handling

| Scenario | HTTP Status | Response |
|----------|-------------|----------|
| No payment headers | `402` | `PaymentRequirements` body |
| Malformed claim JSON / headers | `400` | Error detail |
| Claim signature invalid (local check) | `400` | "Invalid sender signature" |
| Facilitator server unreachable | `503` | "Settlement service unavailable" |
| Facilitator timeout | `504` | "Settlement timed out" |
| Quorum not met (rejections) | `402` | QuorumResult detail |
| Quorum not met (Byzantine faults) | `402` | QuorumResult fault list |
| Internal server error | `500` | Generic error |

---

## Startup and Initialization

### Facilitator Server startup

On startup, the facilitator server:

1. Reads `BFT_F` to determine `n = 3f+1`.
2. Instantiates `n` `Validator` objects, each with its own `AccountStateStore`.
3. Pre-populates each store with a known set of sender/recipient accounts
   (loaded from a JSON fixture or environment-provided seed data).
4. Wraps each `Validator` in a thin `LocalValidatorClient` adapter that implements
   the `ValidatorClient` protocol from `facilitator.py`.
5. Constructs a `FacilitatorConfig` and a `Facilitator` instance, stored as
   application state on the FastAPI `app` object.

### API Server startup

1. Reads `FACILITATOR_URL`, `PAYMENT_RECIPIENT`, `PAYMENT_AMOUNT` from env.
2. Creates a shared `httpx.AsyncClient` instance (connection pooling).
3. Loads or defines the "valuable information" (could be a dict, file, or DB query).

---

## Dependencies to Add

```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
httpx>=0.27.0       # async HTTP client for API Server → Facilitator calls
pydantic>=2.0.0     # already implied by FastAPI
python-dotenv       # env var loading
```

---

## Testing Plan

| Test file | What it covers |
|-----------|---------------|
| `tests/test_api_server.py` | 402 on no headers; 400 on bad sig; 200 on valid flow (mock facilitator) |
| `tests/test_facilitator_server.py` | POST /settle happy path; quorum-not-met path; timeout path |
| `tests/test_integration.py` | Full end-to-end with both servers running via `httpx.AsyncClient` and `uvicorn` test fixtures |

---

## Phased Implementation Order

| Phase | Deliverable |
|-------|-------------|
| **1** | Pydantic models + serialization helpers (no HTTP yet) |
| **2** | Facilitator Server (`POST /settle` + `/health`) with in-process validators |
| **3** | API Server (`GET /resource` 402 gate + forward to facilitator) |
| **4** | Integration test with both servers |
| **5** | Config / env cleanup, logging, and error handling hardening |

---

## Open Questions / Future Work

- **Account bootstrapping**: How does the agent's account (with funded balance) get
  registered in each validator's state store before the first request? Options:
  admin API, genesis file, or pre-seeded fixture.
- **Nonce discovery**: The 402 response could include the agent's current nonce so it
  can build the correct `Claim` without a separate lookup call.
- **Quorum certificate object**: Currently `FacilitatorResult` holds a dict of
  per-validator `Certificate` objects. A future step (FastSet Step 5) would aggregate
  these into a single compact quorum proof.
- **Pre-settlement broadcast** (FastSet Step 6): Not yet implemented; validators that
  rejected are left divergent. A state-sync / reconciliation path is needed for
  production.
- **Remote validators**: `ValidatorClient` is a `Protocol` — swapping the in-process
  adapters for real HTTP clients is the path to a distributed validator network.
- **TLS / authentication**: The facilitator server endpoint should be reachable only
  by the API server in production (mutual TLS or shared secret header).
