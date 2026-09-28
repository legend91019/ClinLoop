"""Frozen Pydantic v2 models for the ClinLoop clinical workflow.

Design rules enforced here (see spec §3 and §7):

* ``extra="forbid"`` everywhere — an unknown field is a contract violation,
  not something to silently drop.
* All datetimes are timezone-aware. A naive datetime raises.
* IDs are non-empty and stripped.
* ``confidence`` lives in ``[0.0, 1.0]``.
* Patient-reported evidence carries its own trust level and can never be
  silently promoted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from packages.contracts.enums import (
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

__all__ = [
    "StrictModel",
    "new_id",
    "utcnow",
    "ActorRef",
    "ClinicalEvent",
    "ClinicalIntent",
    "OpenLoop",
    "EvidenceNode",
    "Finding",
    "AgentStep",
    "ToolCall",
    "AgentRun",
    "ReviewDecision",
    "HandoffReport",
    "TransitionResult",
]

#: A non-empty, stripped identifier.
NonEmptyStr = Annotated[str, Field(min_length=1)]

#: Probability-like value.
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]


def _require_timezone(value: datetime) -> datetime:
    """Reject naive datetimes at coercion time.

    This runs *during* field validation, before any model validator can
    compare two datetimes — otherwise a naive input would raise
    ``TypeError: can't compare offset-naive and offset-aware datetimes``
    instead of a clean 422.
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            "datetime must be timezone-aware; naive values are rejected "
            "to avoid ambiguous clinical timelines"
        )
    return value


#: Timezone-aware datetime. Naive values are rejected at coercion time.
AwareDatetime = Annotated[datetime, AfterValidator(_require_timezone)]


def new_id(prefix: str) -> str:
    """Return a stable-prefixed unique identifier, e.g. ``EVT-3f9c...``."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""

    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Base model: reject unknown fields, validate on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)


class ActorRef(StrictModel):
    """Who or what produced a record."""

    actor_id: NonEmptyStr
    role: NonEmptyStr
    display_name: str | None = None


class EvidenceNode(StrictModel):
    """A single traceable piece of clinical evidence.

    ``source_id`` points back at the originating record (e.g. ``LAB-8821``)
    so the doctor console can jump from a Finding to raw data.
    """

    evidence_id: NonEmptyStr
    patient_id: NonEmptyStr
    encounter_id: NonEmptyStr | None = None
    source_type: NonEmptyStr = Field(
        description="NOTES | ORDERS | LABS | CONSULTS | HANDOFF | PATIENT"
    )
    source_id: NonEmptyStr
    observed_at: AwareDatetime
    claim: NonEmptyStr
    provenance: dict[str, Any] = Field(default_factory=dict)
    trust_level: TrustLevel = TrustLevel.SYSTEM_VERIFIED
    verified_at: AwareDatetime | None = None
    created_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _pending_verification_consistency(self) -> EvidenceNode:
        if self.trust_level is TrustLevel.PATIENT_REPORTED and self.verified_at is not None:
            raise ValueError(
                "PATIENT_REPORTED evidence cannot be marked verified at ingest; "
                "it requires a clinician review decision"
            )
        return self


class ClinicalEvent(StrictModel):
    """An inbound clinical event on the event stream.

    ``source_time`` is when the source system recorded it; ``event_time``
    is when it occurred in the patient's timeline. They may differ
    (transcription lag) and are kept separate on purpose.
    """

    event_id: NonEmptyStr
    patient_id: NonEmptyStr
    encounter_id: NonEmptyStr
    event_type: EventType
    event_time: AwareDatetime
    source_time: AwareDatetime
    payload_ref: NonEmptyStr
    actor: ActorRef
    payload: dict[str, Any] = Field(default_factory=dict)
    ingested_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _event_time_not_after_source_time_by_a_lot(self) -> ClinicalEvent:
        # Sanity guard: a source cannot record an event before it happened
        # by more than a small clock-skew allowance.
        if self.source_time < self.event_time - timedelta(minutes=5):
            raise ValueError("source_time precedes event_time beyond allowed clock skew")
        return self


class ClinicalIntent(StrictModel):
    """What the clinician asked for, extracted from a note.

    ``expected_evidence`` names the evidence kinds that would satisfy the
    intent (e.g. ``["blood_culture_result"]``).
    """

    intent_id: NonEmptyStr
    patient_id: NonEmptyStr
    encounter_id: NonEmptyStr
    intent_type: IntentType
    text: NonEmptyStr
    expected_evidence: list[NonEmptyStr] = Field(default_factory=list)
    source_event_id: NonEmptyStr | None = None
    requires_clinician_review: bool = False
    created_at: AwareDatetime = Field(default_factory=utcnow)

    @field_validator("expected_evidence")
    @classmethod
    def _dedupe_expected_evidence(cls, value: list[str]) -> list[str]:
        seen: list[str] = []
        for item in value:
            if item not in seen:
                seen.append(item)
        return seen


class OpenLoop(StrictModel):
    """An open clinical work item tracking intent until it is closed.

    The Agent may only ever *propose* a new ``state``; the deterministic
    guard validates and persists it.
    """

    loop_id: NonEmptyStr
    patient_id: NonEmptyStr
    encounter_id: NonEmptyStr
    intent_id: NonEmptyStr
    goal: NonEmptyStr
    state: LoopState = LoopState.CREATED
    waiting_for: list[EventType] = Field(default_factory=list)
    depends_on: list[NonEmptyStr] = Field(default_factory=list)
    owner: str | None = None
    last_plan: str | None = None
    confidence: UnitFloat = 1.0
    priority: str = "NORMAL"
    next_check_at: AwareDatetime | None = None
    last_planned_at: AwareDatetime | None = None
    created_at: AwareDatetime = Field(default_factory=utcnow)
    updated_at: AwareDatetime = Field(default_factory=utcnow)

    @field_validator("priority")
    @classmethod
    def _known_priority(cls, value: str) -> str:
        if value not in {"LOW", "NORMAL", "HIGH", "CRITICAL"}:
            raise ValueError(f"unknown priority: {value}")
        return value

    @model_validator(mode="after")
    def _waiting_state_declares_events(self) -> OpenLoop:
        if self.state is LoopState.WAITING_EVENT and not self.waiting_for:
            raise ValueError("WAITING_EVENT loops must declare at least one waiting_for event type")
        return self


class Finding(StrictModel):
    """A workflow gap detected by the Agent and bound to evidence.

    ``searched_sources`` is mandatory so that "not found in the records
    we searched" is never presented as "does not exist".
    """

    finding_id: NonEmptyStr
    patient_id: NonEmptyStr
    loop_id: NonEmptyStr | None = None
    intent_id: NonEmptyStr | None = None
    finding_type: FindingType
    claim: NonEmptyStr
    supporting_evidence: list[NonEmptyStr] = Field(default_factory=list)
    searched_sources: list[NonEmptyStr] = Field(default_factory=list)
    confidence: UnitFloat = 1.0
    requires_review: bool = True
    review_status: str = "PENDING_REVIEW"
    source_run_id: NonEmptyStr | None = None
    detected_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _evidence_backed_or_explicitly_unsupported(self) -> Finding:
        # A finding with no supporting evidence is allowed ONLY when it
        # records exactly what was searched (an explicit "gap in coverage").
        if not self.supporting_evidence and not self.searched_sources:
            raise ValueError(
                "a Finding must carry supporting_evidence or searched_sources; "
                "unbacked claims are not permitted"
            )
        return self


class ToolCall(StrictModel):
    """One MCP tool invocation made by the agent during ACT."""

    tool_name: NonEmptyStr
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_ref: str | None = None
    ok: bool = True
    error_code: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    started_at: AwareDatetime | None = None


class AgentStep(StrictModel):
    """A single step of the OBSERVE→REASON→PLAN→ACT→VERIFY loop."""

    step_id: NonEmptyStr
    kind: AgentStepKind
    input_ref: str | None = None
    output_ref: str | None = None
    reason: NonEmptyStr
    tool_call: ToolCall | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None


class AgentRun(StrictModel):
    """One agent execution: triggered by an event, may span suspend/resume.

    ``plan`` is the reasoning plan; ``tool_calls`` the ACT effects;
    ``candidate_state_changes`` are *proposals* only — never persisted
    directly.
    """

    run_id: NonEmptyStr
    loop_id: NonEmptyStr | None = None
    intent_id: NonEmptyStr | None = None
    trigger_event_id: NonEmptyStr
    resumed_from_run_id: NonEmptyStr | None = None
    plan: list[str] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finding_ids: list[NonEmptyStr] = Field(default_factory=list)
    candidate_state_changes: dict[str, str] = Field(default_factory=dict)
    stop_reason: StopReason | None = None
    started_at: AwareDatetime = Field(default_factory=utcnow)
    finished_at: AwareDatetime | None = None

    @property
    def is_finished(self) -> bool:
        return self.stop_reason is not None and self.finished_at is not None


class ReviewDecision(StrictModel):
    """A clinician's decision on a Finding. Appends to the audit log."""

    decision_id: NonEmptyStr
    finding_id: NonEmptyStr
    action: ReviewAction
    reviewer: ActorRef
    reason: str | None = None
    decided_at: AwareDatetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _reject_and_modify_require_reason(self) -> ReviewDecision:
        if self.action in {ReviewAction.REJECT, ReviewAction.MODIFY}:
            if not self.reason or not self.reason.strip():
                raise ValueError(f"{self.action} requires a non-empty reason")
        return self


class HandoffReport(StrictModel):
    """An I-PASS/SBAR handoff draft derived from confirmed evidence."""

    handoff_id: NonEmptyStr
    patient_id: NonEmptyStr
    encounter_id: NonEmptyStr
    status: HandoffStatus = HandoffStatus.DRAFT
    situation: str = ""
    background: str = ""
    assessment: str = ""
    recommendation: str = ""
    loop_ids: list[NonEmptyStr] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)
    confirmed_items: list[str] = Field(default_factory=list)
    created_by: ActorRef | None = None
    created_at: AwareDatetime = Field(default_factory=utcnow)
    sealed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _sealed_requires_timestamp(self) -> HandoffReport:
        if self.status is HandoffStatus.SEALED and self.sealed_at is None:
            raise ValueError("a SEALED handoff must carry sealed_at")
        return self

    @property
    def is_editable(self) -> bool:
        """Only drafts may be edited by the doctor console."""
        return self.status is HandoffStatus.DRAFT


class TransitionResult(StrictModel):
    """Outcome of a state-transition validation.

    The guard returns this instead of raising for *policy* rejections, so
    the API can surface a structured 409/403 rather than a 500.
    """

    allowed: bool
    requested_state: LoopState
    current_state: LoopState
    requires_review: bool = False
    reason: str = ""
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rejection_explains_itself(self) -> TransitionResult:
        if not self.allowed and not self.reason:
            raise ValueError("a rejected transition must explain itself in `reason`")
        return self
