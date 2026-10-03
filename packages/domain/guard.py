from __future__ import annotations

from dataclasses import dataclass
from packages.contracts import ActorRef, EvidenceNode, LoopState, TrustLevel
from packages.domain.errors import GuardViolation, TrustEscalationDenied
from packages.domain.state_machine import validate_transition


@dataclass(frozen=True)
class CandidateStateChange:
    current_state: LoopState
    requested_state: LoopState
    evidence_ids: tuple[str, ...] = ()
    evidence: tuple[EvidenceNode, ...] = ()


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    requires_review: bool = False
    reason: str = ""


class Guard:
    @staticmethod
    def apply(candidate_state_change: CandidateStateChange, reviewer: ActorRef | None = None) -> GuardResult:
        for node in candidate_state_change.evidence:
            if node.trust_level is TrustLevel.PATIENT_REPORTED and candidate_state_change.requested_state in {LoopState.RESOLVED, LoopState.ACKNOWLEDGED}:
                raise TrustEscalationDenied("patient-reported evidence cannot be promoted by the guard")
        result = validate_transition(candidate_state_change.current_state, candidate_state_change.requested_state, candidate_state_change.evidence_ids, reviewer is not None)
        if not result.allowed:
            return GuardResult(False, result.requires_review, result.reason)
        return GuardResult(True, result.requires_review, result.reason)
