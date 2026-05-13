"""Facilitator: broadcast a claim to 3f+1 validators, collect outcomes, check quorum (2f+1)."""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from src.core.claim import Claim
from src.core.crypto import verify
from src.core.validator import Certificate, Rejection


def _cert_norm_key(cert: Certificate) -> tuple[bytes, bytes, bytes]:
    return (cert.claim.payload(), cert.validator_signature, cert.validator_pubkey.encode())


def _rejection_key(r: Rejection) -> tuple[bytes, str]:
    return (r.claim.payload(), r.reason)


@runtime_checkable
class ValidatorClient(Protocol):
    def verify_and_certify(self, claim: Claim) -> Certificate | Rejection:
        ...

    def settle(self, claim: Claim) -> None:
        ...

    def confirm(self, proof: dict) -> str:
        ...


@dataclass
class FaultEvent:
    kind: str
    validator_id: str
    detail: str = ""


@dataclass
class FacilitatorResult:
    claim: Claim
    quorum_met: bool
    success_count: int
    certificates: dict[str, Certificate]
    rejections: dict[str, Rejection]
    dead: set[str]
    faults: list[FaultEvent] = field(default_factory=list)
    # Per-validator settle wall-clock offsets in microseconds, relative to start
    # of the settle phase (NOT request entry). Empty when quorum not met.
    settle_offsets_us: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass
class FacilitatorConfig:
    """n = 3f+1 validators; quorum is 2f+1 valid certificates.

    With 3f+1 validators the system tolerates up to f Byzantine faults,
    which is the BFT threshold used in FastSet/FastPay.
    """

    f: int
    validators: list[tuple[str, ValidatorClient]]
    per_validator_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.f < 1:
            raise ValueError("f must be at least 1")
        n = 3 * self.f + 1
        if len(self.validators) != n:
            raise ValueError(f"expected {n} validators (3f+1), got {len(self.validators)}")


def evaluate_round(
    claim: Claim,
    f: int,
    responses_per_id: Mapping[str, Sequence[Certificate | Rejection]],
) -> FacilitatorResult:
    """
    Apply duplicate/missing rules and quorum counting over collected responses.
    Empty list for a validator id means dead (no response).
    Expected keys: exactly 3f+1 validator ids.
    """
    if f < 1:
        raise ValueError("f must be at least 1")
    n = 3 * f + 1
    if len(responses_per_id) != n:
        raise ValueError(f"expected {n} validator entries (3f+1), got {len(responses_per_id)}")

    quorum_threshold = 2 * f + 1
    certificates: dict[str, Certificate] = {}
    rejections: dict[str, Rejection] = {}
    dead: set[str] = set()
    faults: list[FaultEvent] = []

    for vid, seq in responses_per_id.items():
        msgs = list(seq)
        if len(msgs) == 0:
            dead.add(vid)
            continue

        certs = [m for m in msgs if isinstance(m, Certificate)]
        rejs = [m for m in msgs if isinstance(m, Rejection)]

        if certs and rejs:
            faults.append(
                FaultEvent(
                    "equivocation",
                    vid,
                    "both certificate and rejection in same round",
                )
            )
            continue

        if rejs:
            uniq = {_rejection_key(r): r for r in rejs}
            if len(uniq) > 1:
                faults.append(
                    FaultEvent(
                        "conflicting_rejections",
                        vid,
                        "multiple distinct rejections",
                    )
                )
                continue
            rejections[vid] = next(iter(uniq.values()))
            continue

        # certificates only
        assert certs
        validated: dict[tuple[bytes, bytes, bytes], Certificate] = {}
        faulted = False
        for c in certs:
            if c.validator_id != vid:
                faults.append(
                    FaultEvent(
                        "validator_id_mismatch",
                        vid,
                        f"certificate validator_id {c.validator_id!r} != {vid!r}",
                    )
                )
                faulted = True
                break
            if c.claim.payload() != claim.payload():
                faults.append(
                    FaultEvent(
                        "claim_mismatch_in_certificate",
                        vid,
                        "certificate claim payload does not match round claim",
                    )
                )
                faulted = True
                break
            if not verify(c.claim.payload(), c.validator_signature, c.validator_pubkey):
                faults.append(
                    FaultEvent(
                        "invalid_validator_signature",
                        vid,
                        "validator signature verification failed",
                    )
                )
                faulted = True
                break
            k = _cert_norm_key(c)
            if k in validated:
                continue
            if validated and k not in validated:
                faults.append(
                    FaultEvent(
                        "duplicate_conflicting_cert",
                        vid,
                        "multiple distinct certificates for same round",
                    )
                )
                faulted = True
                break
            validated[k] = c

        if faulted:
            continue

        if len(validated) == 1:
            certificates[vid] = next(iter(validated.values()))

    success_count = len(certificates)
    quorum_met = success_count >= quorum_threshold

    return FacilitatorResult(
        claim=claim,
        quorum_met=quorum_met,
        success_count=success_count,
        certificates=certificates,
        rejections=rejections,
        dead=dead,
        faults=faults,
    )


class Facilitator:
    def __init__(self, config: FacilitatorConfig):
        self._config = config
        self._f = config.f
        self._validators = list(config.validators)
        self._timeout = config.per_validator_timeout_seconds

    def submit_claim(
        self,
        claim: Claim,
        on_event: Callable[[dict], None] | None = None,
    ) -> FacilitatorResult:
        """Fan out to all 3f+1 validators; wait until each responds or times out; then evaluate quorum.

        If on_event is provided it is invoked once per validator outcome with:
          {"kind": "VALIDATOR_RESPONDED", "validator_id": str,
           "outcome": "cert" | "rejection" | "exception" | "timeout",
           "rt_us": int, "reason": str | None}

        Success / rejection / exception events fire from the validator's worker
        thread the instant it returns (true completion time). Timeout events
        fire from the orchestrator thread when the per-validator wait expires.

        Callers driving on_event from a thread-unsafe consumer (e.g.
        asyncio.Queue) MUST pass a thread-safe wrapper -- see
        EventBus.make_threadsafe_publisher.
        """
        t0_ns = time.perf_counter_ns()

        def emit(event: dict) -> None:
            if on_event is not None:
                on_event(event)

        def call_one(vid: str, client: ValidatorClient) -> tuple[str, list[Certificate | Rejection]]:
            try:
                out = client.verify_and_certify(claim)
            except Exception as exc:
                emit({
                    "kind": "VALIDATOR_RESPONDED",
                    "validator_id": vid,
                    "outcome": "exception",
                    "rt_us": (time.perf_counter_ns() - t0_ns) // 1000,
                    "reason": repr(exc),
                })
                return vid, []
            outcome = "cert" if isinstance(out, Certificate) else "rejection"
            reason = getattr(out, "reason", None) if outcome == "rejection" else None
            emit({
                "kind": "VALIDATOR_RESPONDED",
                "validator_id": vid,
                "outcome": outcome,
                "rt_us": (time.perf_counter_ns() - t0_ns) // 1000,
                "reason": reason,
            })
            return vid, [out]

        responses: dict[str, list[Certificate | Rejection]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self._validators)) as pool:
            future_map = {
                pool.submit(call_one, vid, client): vid for vid, client in self._validators
            }
            for fut in future_map:
                vid = future_map[fut]
                try:
                    v_id, msgs = fut.result(timeout=self._timeout)
                    responses[v_id] = msgs
                except concurrent.futures.TimeoutError:
                    responses[vid] = []
                    emit({
                        "kind": "VALIDATOR_RESPONDED",
                        "validator_id": vid,
                        "outcome": "timeout",
                        "rt_us": (time.perf_counter_ns() - t0_ns) // 1000,
                        "reason": None,
                    })
                except Exception as exc:
                    responses[vid] = []
                    emit({
                        "kind": "VALIDATOR_RESPONDED",
                        "validator_id": vid,
                        "outcome": "exception",
                        "rt_us": (time.perf_counter_ns() - t0_ns) // 1000,
                        "reason": repr(exc),
                    })

        for vid, _ in self._validators:
            responses.setdefault(vid, [])

        return evaluate_round(claim, self._f, responses)

    def submit_and_settle(self, claim: Claim) -> FacilitatorResult:
        """Submit a claim; on quorum, broadcast the certificate to ALL validators.

        Implements steps 5 (Confirm) + 6 (Presettle) + 7 (Settle) of FastSet:
        we build the quorum proof and hand it to every validator -- signers
        and non-signers alike. Validators that rejected or timed out during
        validation catch up here, restoring the invariant that once 2f+1
        honest validators have signed, every honest validator eventually
        applies the message. Non-signers that are behind on prior nonces
        buffer the cert and drain in order.
        """
        from src.core.quorum_proof import build_payment_proof  # lazy: quorum_proof imports FacilitatorResult

        result = self.submit_claim(claim)
        if not result.quorum_met:
            return result

        proof = build_payment_proof(result, self._f)
        settle_phase_start_ns = time.perf_counter_ns()
        offsets: dict[str, tuple[int, int]] = {}
        for vid, client in self._validators:
            t_start_ns = time.perf_counter_ns()
            try:
                client.confirm(proof)
            except Exception:
                # Confirm failures on individual validators are isolated --
                # the certificate is still valid; the rest of the cluster
                # converges. A future fault event channel could surface this.
                pass
            t_end_ns = time.perf_counter_ns()
            offsets[vid] = (
                (t_start_ns - settle_phase_start_ns) // 1000,
                (t_end_ns - settle_phase_start_ns) // 1000,
            )
        result.settle_offsets_us = offsets
        return result
