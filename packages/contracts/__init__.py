"""Re-exports for ``packages.contracts``.

Import from the package root in application code::

    from packages.contracts import ClinicalEvent, EventType, LoopState
"""

from packages.contracts.api import (
    ErrorResponse,
    EventAcceptedResponse,
    EvidenceSummary,
    FindingResponse,
    HealthResponse,
    IntentSummary,
    LoopDetailResponse,
    LoopSummary,
    TimelineEntry,
    TimelineResponse,
)
from packages.contracts.enums import (
    ACTIVE_LOOP_STATES,
    HIGH_RISK_STATES,
    TERMINAL_LOOP_STATES,
    TRUST_PRECEDENCE,
    AgentStepKind,
    EventType,
    FindingType,
    HandoffStatus,
    IntentType,
    LoopState,
    ReviewAction,
    StopReason,
    TrustLevel,
)
from packages.contracts.models import (
    ActorRef,
    AgentRun,
    AgentStep,
    ClinicalEvent,
    ClinicalIntent,
    EvidenceNode,
    Finding,
    HandoffReport,
    OpenLoop,
    ReviewDecision,
    ToolCall,
    TransitionResult,
    new_id,
    utcnow,
)

__all__ = [
    # enums
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
    # models
    "ActorRef",
    "ClinicalEvent",
    "ClinicalIntent",
    "OpenLoop",
    "EvidenceNode",
    "Finding",
    "ToolCall",
    "AgentStep",
    "AgentRun",
    "ReviewDecision",
    "HandoffReport",
    "TransitionResult",
    "new_id",
    "utcnow",
    # api
    "HealthResponse",
    "EventAcceptedResponse",
    "ErrorResponse",
    "EvidenceSummary",
    "IntentSummary",
    "TimelineEntry",
    "TimelineResponse",
    "LoopSummary",
    "LoopDetailResponse",
    "FindingResponse",
]
