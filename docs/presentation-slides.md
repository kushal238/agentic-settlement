# Agentic Settlement: A Prototype FastSet Implementation
## CS521 Project Presentation

---

# Slide 1: Title

## Visual Aid (Slide Content)

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│           AGENTIC SETTLEMENT                            │
│   A Prototype Payment System for Autonomous Agents      │
│                                                         │
│         Based on the FastSet Protocol                   │
│                                                         │
│   ─────────────────────────────────────────────────     │
│                                                         │
│   [Your Name(s)]                                        │
│   CS521 - Spring 2026                                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Speaker Notes

> Welcome everyone. Today we're presenting Agentic Settlement — a prototype payment system designed for autonomous AI agents. Our implementation is based on the FastSet protocol, which enables fast, Byzantine fault-tolerant payment settlement. We'll walk through the protocol, our implementation, and future directions.

---

# Slide 2: Motivation — Why Agentic Payments?

## Visual Aid (Slide Content)

**The Problem: AI Agents Need to Transact**

```
┌──────────┐    "Buy me data"    ┌──────────┐
│  Agent A │ ─────────────────►  │  Agent B │
│ (Buyer)  │ ◄───────────────── │ (Seller) │
└──────────┘    "Pay me first"   └──────────┘
                    ???
```

**Key Requirements:**

- ⚡ **Fast** — Sub-second settlement (not blockchain minutes)
- 🛡️ **Fault-tolerant** — Handle crashes & malicious actors
- 🔐 **Cryptographically secure** — No trust assumptions
- 🤖 **Agent-friendly** — Programmatic, no human intervention

## Speaker Notes

> As AI agents become more autonomous, they need to exchange value — paying for API calls, data, compute resources. Traditional payment systems are too slow (blockchain confirmations) or require human approval. We need a system that's fast, secure, and fully automated. FastSet addresses this by achieving settlement in a single round-trip while tolerating Byzantine faults.

---

# Slide 3: BFT Refresher

## Visual Aid (Slide Content)

**Byzantine Fault Tolerance (BFT) Basics**

```
    Total Validators: n = 3f + 1
    Fault Tolerance:  up to f Byzantine faults
    Quorum Required:  2f + 1 valid signatures

    ┌─────────────────────────────────────────┐
    │  Example: f = 1                         │
    │  ─────────────────────────────────────  │
    │  n = 3(1) + 1 = 4 validators            │
    │  Quorum = 2(1) + 1 = 3 signatures       │
    │  Tolerates: 1 crash OR 1 malicious node │
    └─────────────────────────────────────────┘
```

**Why 3f + 1?**

| Validators | Respond | Faulty (max) | Honest (min) | Quorum Met? |
|------------|---------|--------------|--------------|-------------|
| 4          | 3       | 1            | 3            | ✓ (3 ≥ 3)   |
| 4          | 2       | 1            | 2            | ✗ (2 < 3)   |

## Speaker Notes

> Quick BFT refresher: Byzantine fault tolerance lets a distributed system reach agreement even when some nodes crash or act maliciously. The magic number is 3f+1 validators to tolerate f faults. With 4 validators, we can handle 1 bad actor and still get 3 honest signatures — that's our quorum. This is the foundation FastSet builds on.

---

# Slide 4: FastSet Protocol — The 7 Steps

## Visual Aid (Slide Content)

**FastSet Settlement Lifecycle**

| Step | Name | Description |
|------|------|-------------|
| 1 | **Claim Creation** | Client signs a payment claim |
| 2 | Verification | (Optional) External verifiers attest |
| 3 | **Validation** | Each validator checks the claim |
| 4 | **Validator Signature** | Validators sign if valid |
| 5 | **Quorum Assembly** | Facilitator collects 2f+1 certs |
| 6 | Pre-settlement | Broadcast proof, queue transactions |
| 7 | **Settlement** | Apply balance changes |

```
  ✅ Implemented: Steps 1, 3, 4, 5, 7
  🔜 Future Work: Steps 2, 6
```

## Speaker Notes

> FastSet defines 7 steps for settlement. Steps 1 through 5 handle claim creation, validation, and quorum assembly. Step 6 is pre-settlement for ordering, and step 7 applies the final balance changes. We've implemented steps 1, 3, 4, 5, and 7 — covering the core protocol. Steps 2 and 6 are future work.

---

# Slide 5: Our Implementation Scope

## Visual Aid (Slide Content)

**What We Built**

```
┌─────────────────────────────────────────────────────────┐
│                    src/core/                            │
├─────────────────────────────────────────────────────────┤
│  crypto.py     │  Ed25519 key generation & signing      │
│  claim.py      │  Transaction creation (Step 1)         │
│  account.py    │  Per-validator account state           │
│  validator.py  │  Validation + certification (Steps 3-4)│
│  facilitator.py│  Quorum assembly + settlement (5, 7)   │
└─────────────────────────────────────────────────────────┘
```

**Design Principle: Each Validator is Independent**

```
   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │   V1    │   │   V2    │   │   V3    │   │   V4    │
   │ ┌─────┐ │   │ ┌─────┐ │   │ ┌─────┐ │   │ ┌─────┐ │
   │ │State│ │   │ │State│ │   │ │State│ │   │ │State│ │
   │ └─────┘ │   │ └─────┘ │   │ └─────┘ │   │ └─────┘ │
   └─────────┘   └─────────┘   └─────────┘   └─────────┘
        │             │             │             │
        └─────────────┴──────┬──────┴─────────────┘
                             │
                      ┌──────▼──────┐
                      │ Facilitator │
                      └─────────────┘
```

## Speaker Notes

> Our implementation lives in the `src/core/` directory with 5 main modules. The key design principle is that each validator maintains its own independent state — there's no shared database. The facilitator coordinates communication but doesn't hold any state. This mirrors how FastSet works: validators are sovereign, and consensus emerges from quorum.

---

# Slide 6: Architecture — End-to-End Flow

## Visual Aid (Slide Content)

**Settlement Flow**

```
  ┌────────┐                              ┌────────────────┐
  │ Client │                              │   Validators   │
  │        │                              │  (V1, V2, V3,  │
  └───┬────┘                              │      V4)       │
      │                                   └───────┬────────┘
      │  1. create_claim(signed)                  │
      ▼                                           │
  ┌────────────┐  2. Fan out to all 3f+1          │
  │ Facilitator│ ─────────────────────────────────►
  │            │                                  │
  │            │  3. Each V: verify_and_certify() │
  │            │ ◄─────────────────────────────────
  │            │     [Certificate OR Rejection]   │
  │            │                                  │
  │            │  4. Count certs ≥ 2f+1?          │
  │            │     ───────────────────          │
  │            │         (evaluate_round)         │
  │            │                                  │
  │            │  5. If quorum: settle() on each  │
  │            │ ─────────────────────────────────►
  └────────────┘     signing validator            │
```

## Speaker Notes

> Here's the end-to-end flow. A client creates and signs a claim, then submits it to the facilitator. The facilitator fans out the claim to all 4 validators in parallel. Each validator independently verifies and either issues a certificate or rejects. The facilitator collects responses, checks if we have 3 or more certificates (quorum), and if so, tells each signing validator to apply the settlement. The whole process is one round-trip.

---

# Slide 7: Component — Cryptography (`crypto.py`)

## Visual Aid (Slide Content)

**Ed25519 Digital Signatures**

```python
# crypto.py - Core cryptographic primitives

def generate_keypair():
    """Generate Ed25519 signing + verify key pair."""
    signing_key = SigningKey.generate()
    return signing_key, signing_key.verify_key

def sign(message: bytes, signing_key) -> bytes:
    """Sign message, return 64-byte signature."""
    return signing_key.sign(message).signature

def verify(message, signature, verify_key) -> bool:
    """Verify signature. Returns True/False."""
    try:
        verify_key.verify(message, signature)
        return True
    except BadSignatureError:
        return False
```

**Why Ed25519?**
- Fast: ~70,000 signatures/sec
- Compact: 64-byte signatures, 32-byte keys
- Secure: No known practical attacks

## Speaker Notes

> Our crypto module wraps Ed25519 from the PyNaCl library. We have three functions: keypair generation, signing, and verification. Ed25519 is chosen because it's fast, compact, and battle-tested — it's what FastSet recommends. Every claim and certificate uses these primitives.

---

# Slide 8: Component — Claims (`claim.py`)

## Visual Aid (Slide Content)

**Claim = Signed Payment Intent**

```python
# claim.py - Transaction structure

@dataclass(frozen=True)
class Claim:
    sender: str          # "alice"
    recipient: str       # "bob"  
    amount: int          # 30
    nonce: int           # 0 (replay protection)
    sender_pubkey: VerifyKey
    signature: bytes     # Ed25519 signature

    def payload(self) -> bytes:
        """Canonical bytes: '5:alice|3:bob|2:30|1:0'"""
        parts = [sender, recipient, str(amount), str(nonce)]
        return "|".join(f"{len(p)}:{p}" for p in parts).encode()

    def verify_signature(self) -> bool:
        return verify(self.payload(), self.signature, 
                      self.sender_pubkey)
```

**Key Properties:**
- **Immutable** (`frozen=True`) — can't be tampered
- **Self-verifying** — contains pubkey + signature
- **Nonce** — prevents replay attacks

## Speaker Notes

> A Claim represents a payment intent. It has sender, recipient, amount, and a nonce for replay protection. The payload method creates a canonical byte representation using length-prefixed fields — this prevents delimiter injection attacks. The claim is frozen (immutable) and self-verifying: anyone can check the signature against the embedded public key. This is FastSet Step 1.

---

# Slide 9: Component — Account State (`account.py`)

## Visual Aid (Slide Content)

**Per-Validator Account Storage**

```python
# account.py - Each validator's local state

@dataclass
class Account:
    owner: VerifyKey    # Who can spend
    balance: int        # Current balance
    nonce: int = 0      # Next expected nonce

class AccountStateStore:
    """Tracks accounts for ONE validator. No shared state."""
    
    def __init__(self):
        self._accounts: dict[str, Account] = {}

    def create_account(self, account_id, owner, balance):
        self._accounts[account_id] = Account(owner, balance)

    def get_account(self, account_id) -> Account | None:
        return self._accounts.get(account_id)
```

**Important:** Each validator has its **own** `AccountStateStore`
- No shared database
- State can diverge (intentionally!)
- Consensus via quorum, not synchronization

## Speaker Notes

> The account module is simple but important. Each account tracks an owner public key, balance, and nonce. Critically, every validator maintains its own AccountStateStore — there's no shared database. This means validators can have slightly different views of the world. That's okay! We don't need perfect synchronization; we need quorum agreement. If 3 out of 4 agree, we proceed.

---

# Slide 10: Component — Validator (`validator.py`)

## Visual Aid (Slide Content)

**The 7-Point Validation Checklist**

```python
# validator.py - verify_and_certify() logic

def verify_and_certify(self, claim) -> Certificate | Rejection:
    # 1. Verify sender's signature
    if not claim.verify_signature():
        return Rejection("invalid signature")
    
    # 2. Sender account exists + pubkey matches
    if sender_account is None or claim.sender_pubkey != sender_account.owner:
        return Rejection("unknown/mismatched sender")
    
    # 3. Recipient account exists
    if recipient_account is None:
        return Rejection("unknown recipient")
    
    # 4. Nonce matches (replay protection)
    if claim.nonce != sender_account.nonce:
        return Rejection("nonce mismatch")
    
    # 5. No pending claim for sender (one-at-a-time)
    if claim.sender in self._pending:
        return Rejection("pending claim exists")
    
    # 6. Amount is positive
    # 7. Sufficient balance
    if sender_account.balance < claim.amount:
        return Rejection("insufficient balance")
    
    # ALL PASSED → Sign and return Certificate
    self._pending[claim.sender] = claim
    return Certificate(claim, self.validator_id, 
                       sign(claim.payload(), self._signing_key))
```

## Speaker Notes

> This is the heart of validation — FastSet Steps 3 and 4. Each validator independently runs 7 checks: signature valid? Sender known? Recipient known? Correct nonce? No pending claim? Positive amount? Sufficient balance? If all pass, the validator signs the claim and returns a Certificate. If any fail, it returns a Rejection with the reason. This is deterministic — same input, same output.

---

# Slide 11: Component — Facilitator (`facilitator.py`)

## Visual Aid (Slide Content)

**Fan-Out and Quorum Assembly**

```python
# facilitator.py - submit_claim() core logic

def submit_claim(self, claim) -> FacilitatorResult:
    """Fan out to 3f+1 validators, collect responses."""
    
    with ThreadPoolExecutor(max_workers=4) as pool:
        # Parallel calls to all validators
        futures = {pool.submit(v.verify_and_certify, claim): vid 
                   for vid, v in self._validators}
        
        for future in futures:
            try:
                responses[vid] = future.result(timeout=self._timeout)
            except TimeoutError:
                responses[vid] = []  # Mark as dead
    
    return evaluate_round(claim, f, responses)

def evaluate_round(claim, f, responses) -> FacilitatorResult:
    """Count valid certs, check quorum (2f+1)."""
    quorum_threshold = 2 * f + 1  # = 3 when f=1
    
    # Filter: valid signature? correct claim? no equivocation?
    certificates = {vid: cert for ...valid certs...}
    
    quorum_met = len(certificates) >= quorum_threshold
    return FacilitatorResult(quorum_met, certificates, ...)
```

## Speaker Notes

> The facilitator implements Step 5: quorum assembly. It fans out the claim to all 4 validators in parallel using a thread pool. Each validator has a timeout — if it doesn't respond, it's marked as dead. Then `evaluate_round` counts valid certificates, checking for Byzantine misbehavior like equivocation (sending both accept and reject). If we have 3+ valid certs, quorum is met and we can proceed to settlement.

---

# Slide 12: Fault Detection & Byzantine Tolerance

## Visual Aid (Slide Content)

**Faults We Detect and Tolerate**

| Fault Type | Detection | Handling |
|------------|-----------|----------|
| **Timeout/Crash** | No response within timeout | Mark as `dead`, exclude from quorum |
| **Equivocation** | Cert AND Reject from same V | Flag as fault, exclude validator |
| **Invalid Signature** | Signature verification fails | Flag as fault, exclude validator |
| **Conflicting Certs** | Multiple different certs | Flag as fault, exclude validator |
| **ID Mismatch** | Cert's V_id ≠ expected | Flag as fault, exclude validator |

**Example: 1 Byzantine + 3 Honest = Quorum Still Met**

```
    V1: ✓ Certificate     ─┐
    V2: ✓ Certificate      ├─► 3 valid certs = Quorum ✓
    V3: ✓ Certificate     ─┘
    V4: ✗ Equivocation    ──► Excluded (fault logged)
```

## Speaker Notes

> Our implementation detects several Byzantine behaviors. Timeouts mean the validator is dead. Equivocation means sending conflicting responses — a clear protocol violation. We also catch forged signatures and ID mismatches. The key insight: we don't need to punish bad actors, just exclude them. As long as we have 3 honest validators, we reach quorum. The faults are logged for auditing.

---

# Slide 13: Settlement (`validator.settle()`)

## Visual Aid (Slide Content)

**Applying the Transaction (Step 7)**

```python
# validator.py - settle() after quorum

def settle(self, claim) -> None:
    """Apply certified claim to local state."""
    sender = self.state.get_account(claim.sender)
    recipient = self.state.get_account(claim.recipient)
    
    # Debit sender, credit recipient
    sender.balance -= claim.amount
    recipient.balance += claim.amount
    
    # Increment nonce (prevents replay)
    sender.nonce += 1
    
    # Clear pending slot
    self._pending.pop(claim.sender, None)
```

**Only Signing Validators Are Settled**

```
    ┌─────────────────────────────────────────┐
    │  Quorum Met (V1, V2, V3 signed)         │
    │  ───────────────────────────────────    │
    │  V1: settle() ✓   (balance updated)     │
    │  V2: settle() ✓   (balance updated)     │
    │  V3: settle() ✓   (balance updated)     │
    │  V4: [rejected]   (state diverges)      │
    └─────────────────────────────────────────┘
```

## Speaker Notes

> Settlement is FastSet Step 7. Once quorum is reached, the facilitator calls `settle()` on each validator that issued a certificate. Settlement is simple: debit sender, credit recipient, increment nonce, clear the pending slot. Importantly, validators that rejected or timed out are NOT settled — their state intentionally diverges. They'll need to catch up through a separate sync mechanism, which is part of future work.

---

# Slide 14: Test Results — Proving Correctness

## Visual Aid (Slide Content)

**Key Test Scenarios**

| Test | Scenario | Expected | Result |
|------|----------|----------|--------|
| `test_quorum_all_certs_success` | All 4 validators accept | Quorum ✓, 4 certs | ✅ |
| `test_quorum_fails_when_two_reject` | 2 validators reject | Quorum ✗, 2 certs | ✅ |
| `test_one_dead_still_reaches_quorum` | 1 timeout | Quorum ✓, 3 certs | ✅ |
| `test_two_dead_fail_quorum` | 2 timeouts | Quorum ✗ | ✅ |
| `test_byzantine_equivocation_tolerated` | V1 sends cert+reject | V1 excluded, 3 certs | ✅ |
| `test_replay_after_settlement_rejected` | Same claim twice | Nonce mismatch | ✅ |

**Test Command:**
```bash
pytest tests/ -v
```

## Speaker Notes

> We have comprehensive tests covering happy paths and failure modes. All 4 accept? Quorum met. 2 reject? Quorum fails. 1 timeout? Still works — that's fault tolerance. 2 timeouts? Fails as expected. Byzantine equivocation? Detected and excluded. Replay attack? Blocked by nonce. These tests validate that our implementation matches FastSet's guarantees.

---

# Slide 15: Future Work — Pre-Settlement (Step 6)

## Visual Aid (Slide Content)

**Current Gap: No Pre-Settlement Phase**

```
  Current Implementation:
  ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ Validate │ ──►│  Quorum  │ ──►│  Settle  │
  │ (3,4)    │    │   (5)    │    │   (7)    │
  └──────────┘    └──────────┘    └──────────┘
                        │
                        ▼
               Missing: Step 6!
```

**What Pre-Settlement Adds:**

```
  With Pre-Settlement:
  ┌──────────┐    ┌──────────┐    ┌─────────────┐    ┌──────────┐
  │ Validate │ ──►│  Quorum  │ ──►│Pre-Settle   │ ──►│  Settle  │
  │ (3,4)    │    │   (5)    │    │Broadcast to │    │   (7)    │
  └──────────┘    └──────────┘    │ALL validators│    └──────────┘
                                  └─────────────┘
```

**Benefits:**
- Divergent validators can catch up
- Proper nonce ordering across pipeline
- Foundation for high-throughput batching

## Speaker Notes

> Our main future work is implementing Step 6: pre-settlement. Currently, we go straight from quorum to settlement, which means validators that rejected stay divergent. Pre-settlement would broadcast the quorum proof to ALL validators, letting them sync up before settlement. This also enables proper nonce ordering when multiple claims are in flight, which is critical for high-throughput scenarios.

---

# Slide 16: Conclusion

## Visual Aid (Slide Content)

**What We Built**

```
┌─────────────────────────────────────────────────────────┐
│  Agentic Settlement: FastSet Steps 1, 3, 4, 5, 7       │
├─────────────────────────────────────────────────────────┤
│  ✓ Ed25519 cryptographic primitives                     │
│  ✓ Signed, immutable claims with replay protection      │
│  ✓ Independent per-validator state                      │
│  ✓ 7-point validation checklist                         │
│  ✓ Parallel fan-out with timeout handling               │
│  ✓ Byzantine fault detection (equivocation, forgery)    │
│  ✓ Quorum-based settlement (2f+1 threshold)             │
│  ✓ Comprehensive test suite                             │
└─────────────────────────────────────────────────────────┘
```

**Key Takeaway:**

> Fast, fault-tolerant settlement in **one round-trip**
> — no blockchain, no waiting, just math.

**GitHub:** `[your-repo-link]`

## Speaker Notes

> To summarize: we built a working prototype of the FastSet protocol for agentic payments. We implemented claim creation, validation, quorum assembly, and settlement — the core steps needed for single-round-trip settlement. Our implementation handles Byzantine faults, prevents replay attacks, and is backed by a comprehensive test suite. The key insight is that you don't need a blockchain for fast, secure payments — just BFT consensus and good cryptography. Questions?

---

# Appendix: Code Repository Structure

```
agentic-settlement/
├── src/
│   └── core/
│       ├── crypto.py        # Ed25519 primitives
│       ├── claim.py         # Claim dataclass + creation
│       ├── account.py       # Account state store
│       ├── validator.py     # Validation + certification
│       └── facilitator.py   # Quorum assembly + settlement
├── tests/
│   ├── test_facilitator.py  # Quorum & fault tests
│   ├── test_settlement.py   # End-to-end settlement tests
│   └── test_single_validator.py
└── docs/
    ├── fastset-step-mapping.md
    └── presentation-slides.md  # This file
```

---

# Appendix: Quick Reference — Key Data Structures

```python
# The core types at a glance

Claim(sender, recipient, amount, nonce, sender_pubkey, signature)
    # A signed payment intent

Account(owner: VerifyKey, balance: int, nonce: int)
    # Per-validator account state

Certificate(claim, validator_id, validator_signature, validator_pubkey)
    # A validator's approval

Rejection(claim, validator_id, reason: str)
    # A validator's denial

FacilitatorResult(quorum_met, certificates, rejections, dead, faults)
    # Outcome of a settlement attempt
```
