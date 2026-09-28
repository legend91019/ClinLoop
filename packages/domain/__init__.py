"""Re-exports for ``packages.domain``."""

from packages.domain.errors import (
    ClinLoopDomainError,
    EvidenceRequired,
    GuardViolation,
    InvalidTransition,
    ReviewRequired,
    TrustEscalationDenied,
)
from packages.domain.state_machine import (
    can_transition,
    next_states,
    validate_transition,
)
from packages.domain.transition_policy import (
    ALLOWED_TRANSITIONS,
    EVIDENCE_REQUIRED_TARGETS,
    REVIEW_REQUIRED_TARGETS,
    SYSTEM_DRIVEN_EDGES,
    allowed_targets,
    is_edge_allowed,
    is_system_driven,
    is_terminal,
    required_review_for,
    requires_evidence_for,
)

__all__ = [
    # errors
    "ClinLoopDomainError",
    "InvalidTransition",
    "GuardViolation",
    "EvidenceRequired",
    "ReviewRequired",
    "TrustEscalationDenied",
    # state machine
    "validate_transition",
    "can_transition",
    "next_states",
    # policy
    "ALLOWED_TRANSITIONS",
    "REVIEW_REQUIRED_TARGETS",
    "EVIDENCE_REQUIRED_TARGETS",
    "SYSTEM_DRIVEN_EDGES",
    "allowed_targets",
    "is_edge_allowed",
    "required_review_for",
    "requires_evidence_for",
    "is_system_driven",
    "is_terminal",
]
