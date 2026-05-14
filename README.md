# agentic-settlement

A full-stack simulator for **BFT micropayment settlement** between
autonomous AI agents, bridging the **x402** HTTP payment-required protocol
and the **FastSet** weak-consensus settlement layer.

When an agent asks for a paid resource, the server replies with
`402 Payment Required`. The agent signs a claim, hands it to a
**facilitator** that fans it out to `n = 3f+1` validators, collects a
`2f+1` quorum certificate, and presents that certificate back to the  
server, which verifies it **offline** and returns the resource. No
inter-validator chatter, no global ordering, no L1 round-trip.

The repo contains:

- A **pure-Python BFT core** (signing, validation, quorum assembly,
fault detection, transferable proofs).
- Two **FastAPI services** running the live protocol (a facilitator with
in-process validators, and an x402-gated resource server).
- A **React/TypeScript observer** that doubles as an in-browser agent,
for visualizing every step of a run.
- A **terminal agent CLI** that speaks the same protocol from the command
line — useful for automation and benchmarking.

## Prerequisites

- **Python ≥ 3.11**
- **Node.js ≥ 20** (for the dashboard)
- macOS or Linux. Windows works under WSL but is untested.

## One-time setup

```bash
git clone https://github.com/kushal238/agentic-settlement.git
cd agentic-settlement

# Python deps in a venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Frontend deps
(cd frontend && npm install)
```

The repo ships with a `genesis.json` seeding two accounts. Each validator
loads it on startup — no migrations, no external DB.

---

## Run the visual dashboard

Start all three services (facilitator on `:8001`, API server on `:8000`,
dashboard on `:5173`) under one shell:

```bash
./start.sh
```

Then open **[http://localhost:5173](http://localhost:5173)** in your browser. `Ctrl+C` in the
terminal stops all three.

The dashboard plays two roles at once: it **is** the agent (it holds an
Ed25519 keypair in-browser, signs real claims, and submits them to the
live facilitator), and it **observes** what happens (animated topology,
per-validator state cards, a scrubbable microsecond timeline, and a
swimlane sequence view).

Things you can do from the UI:

- Hit **Run** on the **Happy Path** scenario for a clean end-to-end
settlement, then scrub the timeline to inspect each step.
- Switch scenarios (Replay Attack / Insufficient Balance / Invalid
Recipient) to watch every validator reject and quorum fail.
- Use the **Byzantine toggle** on individual validators to fault them
manually and see the cluster still reach quorum (`f=1`: tolerate 1
faulty; `f=2`: tolerate 2; etc.).
- Use the `f` selector to reconfigure the cluster on the fly
(`n ∈ {4, 7, 10, 13, 16}`).

---

## Use the agent CLI

The CLI behaves as a real customer agent — it holds its own Ed25519
keypair, signs claims, and runs the full x402 buy flow end-to-end against
the **same live servers** the dashboard uses. Useful for terminal users,
scripting, and benchmarking.

Make sure the servers are running first (`./start.sh` or just the two
Python services).

```bash
# One-time identity setup. Creates ~/.agentic-settlement/agent_key.json
# and registers the agent's account on every validator.
python -m cli.agent_client setup

# Buy the protected resource. Prints a verbose step-by-step trace
# (request bodies, canonical signed bytes, every validator certificate)
# plus a per-phase timing breakdown at the end.
python -m cli.agent_client buy

# Same flow, but with a pause between phases for classroom walkthroughs.
# (Wall-clock numbers under --step no longer represent agent latency.)
python -m cli.agent_client buy --step
```

A successful `buy` ends with a block like:

```
BUY COMPLETE   paid 10 to server-recipient   quorum 4/3
  end-to-end (work):     13ms
  wall-clock:            15ms
  per-phase breakdown:
    ask      1ms
    nonce    0ms
    sign     0ms
    settle   7ms
    encode   0ms
    redeem   5ms
    verify   0ms
```

---

## Further reading

- `[docs/fastset-step-mapping.md](docs/fastset-step-mapping.md)` — every
FastSet protocol step mapped to a file/function in this repo, with a
Mermaid sequence diagram of the end-to-end flow.
- `[docs/x402-parity.md](docs/x402-parity.md)` — parity notes vs the
upstream x402 spec.
- Run the test suite (100 tests, ~10s): `python -m pytest -q`
- Run the latency-vs-cluster-size benchmark:
`python -m bench.x402.bench_scaling --fs 1,2,3,4,5 --trials 50`
- [FastSet whitepaper (arXiv 2506.23395)](https://arxiv.org/abs/2506.23395)
- [FastPay (Baudet et al., AFT 2020)](https://arxiv.org/abs/2003.11506)

