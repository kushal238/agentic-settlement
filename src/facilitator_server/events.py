"""Event kind constants emitted by the facilitator server.

The bus instance itself lives on `app.state.event_bus`; these constants are
the vocabulary of structured events that subscribers (notably the observer
CLI) consume off /events SSE.

Per-validator outcomes are emitted by core (see Facilitator.submit_claim):
  VALIDATOR_RESPONDED  {validator_id, outcome, rt_us, reason}

Lifecycle events emitted by routes/settle.py wrap the surrounding flow:
  SETTLE_RECEIVED         claim arrived at /settle
  CLAIM_VERIFIED          sender-signature check passed
  FANOUT_STARTED          about to broadcast to validators
  QUORUM_EVALUATED        submit_claim returned; quorum decision made
  PROOF_ASSEMBLED         payment proof built (only if quorum_met)
  SETTLE_BACKGROUND_DONE  per-validator settle bookkeeping completed
                          (after HTTP response was already sent)

Every event carries `kind` and `ts_mono_ns` (monotonic ns for ordering).
Settle-flow lifecycle events also carry `request_id` (per-request UUID) so
observers can group events from the same request.
"""

VALIDATOR_RESPONDED = "VALIDATOR_RESPONDED"

SETTLE_RECEIVED = "SETTLE_RECEIVED"
CLAIM_VERIFIED = "CLAIM_VERIFIED"
FANOUT_STARTED = "FANOUT_STARTED"
QUORUM_EVALUATED = "QUORUM_EVALUATED"
PROOF_ASSEMBLED = "PROOF_ASSEMBLED"
SETTLE_BACKGROUND_DONE = "SETTLE_BACKGROUND_DONE"
