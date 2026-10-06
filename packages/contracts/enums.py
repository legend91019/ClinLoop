"""Frozen enumerations for the ClinLoop clinical workflow domain.

These values are part of the **public contract** shared by the API, the
worker, the MCP server, the doctor console and the evaluation harness.
Adding a member is backwards compatible; renaming or removing one is a
breaking change and must go through a contract PR.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "EventType",
    "LoopState",
    "FindingType",
    "TrustLevel",
    "IntentType",
    "ReviewAction",
    "HandoffStatus",
    "StopReason",
    "AgentStepKind",
    "TERMINAL_LOOP_STATES",
    "ACTIVE_LOOP_STATES",
    "HIGH_RISK_STATES",
    "TRUST_PRECEDENCE",
]


class EventType(StrEnum):
    """Clinical event types ingested by the workflow (≥6 required by the spec)."""

    NOTE_CREATED = "NOTE_CREATED"
    ORDER_UPDATED = "ORDER_UPDATED"
    LAB_RESULT_CREATED = "LAB_RESULT_CREATED"
    CONSULT_NOTE_CREATED = "CONSULT_NOTE_CREATED"
    PROGRESS_NOTE_CREATED = "PROGRESS_NOTE_CREATED"
    HANDOFF_STARTED = "HANDOFF_STARTED"
    PATIENT_EVIDENCE_SUBMITTED = "PATIENT_EVIDENCE_SUBMITTED"


class LoopState(StrEnum):
    """Lifecycle of an Open Loop.

    Happy path::

        CREATED -> PLANNED -> ORDERED/ACTION_REQUESTED -> IN_PROGRESS
        -> RESULT_AVAILABLE -> ACKNOWLEDGED -> RESOLVED

    Exception / waiting states are reachable from most active states.
    """

    # --- happy path ---
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    ORDERED = "ORDERED"
    ACTION_REQUESTED = "ACTION_REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    RESULT_AVAILABLE = "RESULT_AVAILABLE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"

    # --- exception / waiting ---
    WAITING_EVENT = "WAITING_EVENT"
    OVERDUE = "OVERDUE"
    ORPHANED = "ORPHANED"
    CONFLICTED = "CONFLICTED"
    STALE = "STALE"
    PENDING_REVIEW = "PENDING_REVIEW"

    # --- closed without resolution ---
    CANCELLED = "CANCELLED"


class FindingType(StrEnum):
    """Workflow gap taxonomy (≥4 classes required by the spec).

    Each member names a break in the Plan -> Order -> Execution -> Result
    -> Response -> Handoff chain.
    """

    # Plan -> Order
    INTENT_WITHOUT_PLAN = "INTENT_WITHOUT_PLAN"
    PLAN_WITHOUT_ORDER = "PLAN_WITHOUT_ORDER"
    # Order -> Execution
    ORDER_WITHOUT_EXECUTION = "ORDER_WITHOUT_EXECUTION"
    # Execution/Result -> Response
    RESULT_WITHOUT_ACKNOWLEDGEMENT = "RESULT_WITHOUT_ACKNOWLEDGEMENT"
    UNACKNOWLEDGED_CRITICAL_RESULT = "UNACKNOWLEDGED_CRITICAL_RESULT"
    # Evidence -> Handoff
    UNRESOLVED_HIGH_PRIORITY_LOOP = "UNRESOLVED_HIGH_PRIORITY_LOOP"
    LOOP_MISSING_FROM_HANDOFF = "LOOP_MISSING_FROM_HANDOFF"
    # Consistency
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    STALE_LOOP = "STALE_LOOP"
    ORPHANED_LOOP = "ORPHANED_LOOP"


class TrustLevel(StrEnum):
    """Provenance trust of an EvidenceNode.

    ``PATIENT_REPORTED`` must stay at ``PENDING_VERIFICATION`` and can
    never be promoted to ``SYSTEM_VERIFIED``.
    """

    SYSTEM_VERIFIED = "SYSTEM_VERIFIED"
    CLINICIAN_CONFIRMED = "CLINICIAN_CONFIRMED"
    PATIENT_REPORTED = "PATIENT_REPORTED"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    UNVERIFIED = "UNVERIFIED"


class IntentType(StrEnum):
    """Deliberately finite clinical-intent taxonomy for the MVP."""

    FOLLOW_RESULT = "FOLLOW_RESULT"
    FOLLOW_CONSULT = "FOLLOW_CONSULT"
    EXECUTE_ORDER = "EXECUTE_ORDER"
    UPDATE_PLAN = "UPDATE_PLAN"


class ReviewAction(StrEnum):
    """Clinician decision recorded against a Finding."""

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    EDIT = "EDIT"


class HandoffStatus(StrEnum):
    """Lifecycle of a HandoffReport."""

    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    SEALED = "SEALED"


class StopReason(StrEnum):
    """Why an AgentRun stopped. No other values are permitted."""

    WAITING_EXTERNAL_EVENT = "WAITING_EXTERNAL_EVENT"
    REQUIRES_CLINICIAN_REVIEW = "REQUIRES_CLINICIAN_REVIEW"
    SUFFICIENT_EVIDENCE = "SUFFICIENT_EVIDENCE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CONFLICTED_EVIDENCE = "CONFLICTED_EVIDENCE"
    MODEL_ERROR = "MODEL_ERROR"


class AgentStepKind(StrEnum):
    """The five-step reasoning loop of the Workflow Agent."""

    OBSERVE = "OBSERVE"
    REASON = "REASON"
    PLAN = "PLAN"
    ACT = "ACT"
    VERIFY = "VERIFY"


#: Loop states from which no further automatic transition may occur.
TERMINAL_LOOP_STATES: frozenset[LoopState] = frozenset({LoopState.RESOLVED, LoopState.CANCELLED})

#: Loop states that still represent open clinical work.
ACTIVE_LOOP_STATES: frozenset[LoopState] = frozenset(
    s for s in LoopState if s not in TERMINAL_LOOP_STATES
)

#: States whose entry changes clinical accountability and therefore always
#: requires an explicit clinician review before it is persisted.
HIGH_RISK_STATES: frozenset[LoopState] = frozenset(
    {
        LoopState.RESOLVED,
        LoopState.CANCELLED,
        LoopState.CONFLICTED,
        LoopState.PENDING_REVIEW,
    }
)

#: Relative trust ordering. A transition may never *raise* trust above the
#: strongest evidence that supports it — in particular patient-reported
#: evidence can never reach ``SYSTEM_VERIFIED``.
TRUST_PRECEDENCE: dict[TrustLevel, int] = {
    TrustLevel.UNVERIFIED: 0,
    TrustLevel.PENDING_VERIFICATION: 1,
    TrustLevel.PATIENT_REPORTED: 1,
    TrustLevel.SYSTEM_VERIFIED: 2,
    TrustLevel.CLINICIAN_CONFIRMED: 3,
}
