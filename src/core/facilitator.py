"""Facilitator: broadcast a claim to 3f+1 validators, collect outcomes, check quorum (2f+1)."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence, runtime_checkable

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

    def submit_claim(self, claim: Claim) -> FacilitatorResult:
        """Fan out to all 3f+1 validators; wait until each responds or times out; then evaluate quorum."""

        def call_one(vid: str, client: ValidatorClient) -> tuple[str, list[Certificate | Rejection]]:
            try:
                out = client.verify_and_certify(claim)
                return vid, [out]
            except Exception:
                return vid, []

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
                except Exception:
                    responses[vid] = []

        for vid, _ in self._validators:
            responses.setdefault(vid, [])

        return evaluate_round(claim, self._f, responses)

    def submit_and_settle(self, claim: Claim) -> FacilitatorResult:
        """Submit a claim; if quorum is reached, drive settlement on every signing validator.

        Validators that rejected or timed out are intentionally not settled -- their state
        diverges from the quorum view until they catch up through a separate sync path.
        """
        result = self.submit_claim(claim)
        if not result.quorum_met:
            return result

        signer_ids = set(result.certificates.keys())
        for vid, client in self._validators:
            if vid in signer_ids:
                client.settle(claim)
        return result
