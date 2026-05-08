"""Event kind constants emitted by the API server.

The bus instance itself lives on `app.state.event_bus`; these constants are
the vocabulary of structured events that subscribers (notably the observer
CLI) consume off /events SSE.

Lifecycle events emitted by routes/resource.py:
  RESOURCE_REQUESTED     GET /resource arrived (with `has_proof_header`)
  REQUIREMENTS_ISSUED    returning 402 (with `reason`: no_proof_header /
                         invalid_proof / wrong_recipient / insufficient_amount)
  PROOF_RECEIVED         X-Payment-Proof header present, about to verify
  PROOF_REJECTED         verification failed (with structured `reason` and
                         `detail`)
  PROOF_VERIFIED         verification succeeded (with `quorum_size`)
  RESOURCE_RELEASED      returning 200 with the paid payload

Every event carries `kind`, `request_id` (per-request UUID), and
`ts_mono_ns` (monotonic ns for ordering).
"""

RESOURCE_REQUESTED = "RESOURCE_REQUESTED"
REQUIREMENTS_ISSUED = "REQUIREMENTS_ISSUED"
PROOF_RECEIVED = "PROOF_RECEIVED"
PROOF_REJECTED = "PROOF_REJECTED"
PROOF_VERIFIED = "PROOF_VERIFIED"
RESOURCE_RELEASED = "RESOURCE_RELEASED"
