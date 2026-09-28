"""Domain errors for the clinical workflow.

Policy rejections are *not* exceptions — they come back as
``TransitionResult(allowed=False)`` so the API can answer with a
structured 409/403. Exceptions below are reserved for programming errors
and impossible states.
"""

from __future__ import annotations

from packages.contracts.enums import LoopState

__all__ = [
    "ClinLoopDomainError",
    "InvalidTransition",
    "GuardViolation",
    "EvidenceRequired",
    "ReviewRequired",
    "TrustEscalationDenied",
]


class ClinLoopDomainError(Exception):
    """Base class for every domain-level error."""


class InvalidTransition(ClinLoopDomainError):
    """Raised when a transition is not merely unapproved but *structurally*
    impossible, e.g. ``RESULT_AVAILABLE -> RESOLVED``.

    This is a hard error because it indicates the caller does not
    understand the state machine.
    """

    def __init__(self, current: LoopState, requested: LoopState, reason: str = "") -> None:
        self.current = current
        self.requested = requested
        self.reason = reason or f"{current} cannot transition to {requested}"
        super().__init__(self.reason)


class GuardViolation(ClinLoopDomainError):
    """Raised when a deterministic guard blocks a change outright."""


class EvidenceRequired(ClinLoopDomainError):
    """Raised when a transition needs supporting evidence that was absent."""


class ReviewRequired(ClinLoopDomainError):
    """Raised when a high-risk change is attempted without a reviewer."""


class TrustEscalationDenied(GuardViolation):
    """Raised when evidence trust would be raised beyond what is justified.

    In particular: patient-reported evidence can never become
    ``SYSTEM_VERIFIED``.
    """
