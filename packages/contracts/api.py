"""API request/response DTOs.

Route handlers must never return SQLAlchemy objects directly (spec §4,
task 4). Every payload crossing the HTTP boundary is defined here and is
a plain, JSON-serialisable Pydantic model.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from packages.contracts.enums import EventType, FindingType, LoopState, ReviewAction, TrustLevel
from packages.contracts.models import (
    ActorRef,
    AwareDatetime,
    NonEmptyStr,
    StrictModel,
)

__all__ = [
    "HealthResponse",
    "EventAcceptedResponse",
    "EvidenceSummary",
    "IntentSummary",
    "TimelineEntry",
    "TimelineResponse",
    "LoopSummary",
    "LoopDetailResponse",
    "FindingResponse",
    "ErrorResponse",
    "ReviewRequest",
    "ReviewResponse",
    "HandoffResponse",
]


class HealthResponse(StrictModel):
    """``GET /healthz`` payload."""

    status: str = "ok"
    version: str = "0.1.0"


class EventAcceptedResponse(StrictModel):
    """202 response for ``POST /api/v1/events``."""

    event_id: NonEmptyStr
    accepted: bool = True
    duplicate: bool = False


class ErrorResponse(StrictModel):
    """Uniform error envelope."""

    detail: str
    code: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class EvidenceSummary(StrictModel):
    """Compact evidence projection embedded in loop/timeline responses."""

    evidence_id: NonEmptyStr
    source_type: NonEmptyStr
    source_id: NonEmptyStr
    observed_at: AwareDatetime
    claim: NonEmptyStr
    trust_level: TrustLevel


class IntentSummary(StrictModel):
    """Compact intent projection."""

    intent_id: NonEmptyStr
    intent_type: NonEmptyStr
    text: NonEmptyStr
    expected_evidence: list[str] = Field(default_factory=list)
    requires_clinician_review: bool = False


class TimelineEntry(StrictModel):
    """One event on the patient timeline, oldest first."""

    event_id: NonEmptyStr
    event_type: EventType
    event_time: AwareDatetime
    source_time: AwareDatetime
    actor: ActorRef
    payload_ref: NonEmptyStr


class TimelineResponse(StrictModel):
    """``GET /api/v1/patients/{patient_id}/timeline`` payload."""

    patient_id: NonEmptyStr
    hours: int = Field(ge=1, le=24 * 30)
    window_start: AwareDatetime
    window_end: AwareDatetime
    count: int = Field(ge=0)
    entries: list[TimelineEntry] = Field(default_factory=list)


class LoopSummary(StrictModel):
    """Compact loop projection for list endpoints."""

    loop_id: NonEmptyStr
    intent_id: NonEmptyStr
    goal: NonEmptyStr
    state: LoopState
    waiting_for: list[EventType] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    owner: str | None = None
    priority: str = "NORMAL"
    confidence: float = Field(ge=0.0, le=1.0)
    next_check_at: AwareDatetime | None = None


class LoopDetailResponse(StrictModel):
    """``GET /api/v1/loops/{loop_id}`` payload: loop + intent + evidence."""

    loop: LoopSummary
    intent: IntentSummary | None = None
    evidence: list[EvidenceSummary] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class FindingResponse(StrictModel):
    """``GET /api/v1/findings/{finding_id}`` payload.

    ``supporting_evidence`` and ``searched_sources`` are always present so
    the console can show exactly what was searched.
    """

    finding_id: NonEmptyStr
    patient_id: NonEmptyStr
    loop_id: str | None = None
    intent_id: str | None = None
    finding_type: FindingType
    claim: NonEmptyStr
    supporting_evidence: list[str] = Field(default_factory=list)
    searched_sources: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_review: bool
    review_status: str
    detected_at: AwareDatetime


class ReviewRequest(StrictModel):
    action: ReviewAction
    reason: str | None = None


class ReviewResponse(StrictModel):
    decision_id: NonEmptyStr
    finding_id: NonEmptyStr
    action: str
    review_status: str


class HandoffResponse(StrictModel):
    handoff_id: NonEmptyStr
    patient_id: NonEmptyStr
    encounter_id: NonEmptyStr
    status: str
    situation: str = ""
    background: str = ""
    assessment: str = ""
    recommendation: str = ""
    loop_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    confirmed_items: list[str] = Field(default_factory=list)
