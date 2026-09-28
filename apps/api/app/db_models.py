"""SQLAlchemy 2.0 ORM models for the ClinLoop workflow schema.

Conventions (task 3):

* Every core table carries ``created_at``/``updated_at`` plus the original
  JSON ``payload`` so the raw source record is never lost.
* Enums are stored as their string values (``Enum(..., native_enum=False)``)
  so SQLite and PostgreSQL behave identically and adding a member is a
  data change, not a DDL migration.
* Indexes target the hot paths: patient/event, patient/state,
  loop/observed_at, audit/entity/time.

These objects never cross the API boundary — routes return the DTOs from
:mod:`packages.contracts.api`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.api.app.db import Base
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
from packages.contracts.models import utcnow

__all__ = [
    "Patient",
    "Encounter",
    "ClinicalEventRow",
    "ClinicalIntentRow",
    "OpenLoopRow",
    "EvidenceNodeRow",
    "FindingRow",
    "AgentRunRow",
    "ReviewDecisionRow",
    "HandoffReportRow",
    "AuditLogRow",
    "JSONPayloadMixin",
    "TimestampMixin",
]

#: Portable string-backed enum column. Values stay readable in the DB.
_STR_LEN = 32


class TimestampMixin:
    """``created_at`` / ``updated_at`` with database-side defaults."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class JSONPayloadMixin:
    """Keeps the original source record alongside the normalised row."""

    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Patient(TimestampMixin, JSONPayloadMixin, Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    encounters: Mapped[list[Encounter]] = relationship(
        back_populates="patient", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (Index("ix_patients_synthetic", "synthetic"),)


class Encounter(TimestampMixin, JSONPayloadMixin, Base):
    __tablename__ = "encounters"

    encounter_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("patients.patient_id", ondelete="CASCADE"), nullable=False
    )
    ward: Mapped[str | None] = mapped_column(String(64), nullable=True)
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discharged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    patient: Mapped[Patient] = relationship(back_populates="encounters")

    __table_args__ = (Index("ix_encounters_patient", "patient_id"),)


class ClinicalEventRow(TimestampMixin, JSONPayloadMixin, Base):
    """An ingested clinical event. ``event_id`` is the idempotency key."""

    __tablename__ = "clinical_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    encounter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_clinical_events_patient_event_time", "patient_id", "event_time"),
        Index("ix_clinical_events_type", "event_type"),
        Index("ix_clinical_events_encounter", "encounter_id"),
    )


class ClinicalIntentRow(TimestampMixin, JSONPayloadMixin, Base):
    """A clinician intent extracted from a note."""

    __tablename__ = "clinical_intents"

    intent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    encounter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_type: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requires_clinician_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_clinical_intents_patient", "patient_id"),
        Index("ix_clinical_intents_source_event", "source_event_id"),
    )


class OpenLoopRow(TimestampMixin, JSONPayloadMixin, Base):
    """An open clinical work item."""

    __tablename__ = "open_loops"

    loop_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    encounter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False, index=True)
    waiting_for: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    depends_on: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="NORMAL")
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_open_loops_patient_state", "patient_id", "state"),
        Index("ix_open_loops_intent", "intent_id"),
        Index("ix_open_loops_priority", "priority"),
    )


class EvidenceNodeRow(TimestampMixin, JSONPayloadMixin, Base):
    """One traceable piece of clinical evidence.

    ``loop_id`` is optional: evidence can exist before it is bound to a
    loop, and the same evidence may support several findings.
    """

    __tablename__ = "evidence_nodes"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    loop_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    trust_level: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_evidence_nodes_patient", "patient_id"),
        Index("ix_evidence_nodes_loop_observed_at", "loop_id", "observed_at"),
        Index("ix_evidence_nodes_source", "source_type", "source_id"),
    )


class FindingRow(TimestampMixin, JSONPayloadMixin, Base):
    """A workflow gap bound to evidence, awaiting or carrying a review."""

    __tablename__ = "findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    loop_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finding_type: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    searched_sources: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_status: Mapped[str] = mapped_column(
        String(_STR_LEN), nullable=False, default="PENDING_REVIEW"
    )
    source_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("ix_findings_patient_type", "patient_id", "finding_type"),
        Index("ix_findings_loop", "loop_id"),
        Index("ix_findings_review_status", "review_status"),
    )


class AgentRunRow(TimestampMixin, JSONPayloadMixin, Base):
    """One agent execution, including its plan, steps and tool calls."""

    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    loop_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resumed_from_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    finding_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    candidate_state_changes: Mapped[dict[str, str]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    stop_reason: Mapped[str | None] = mapped_column(String(_STR_LEN), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_runs_trigger_event", "trigger_event_id"),
        Index("ix_agent_runs_loop", "loop_id"),
        UniqueConstraint("trigger_event_id", "resumed_from_run_id", name="uq_agent_runs_origin"),
    )


class ReviewDecisionRow(TimestampMixin, JSONPayloadMixin, Base):
    """A clinician decision on a finding. Append-only."""

    __tablename__ = "review_decisions"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    finding_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("findings.finding_id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(64), nullable=False)
    reviewer_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("ix_review_decisions_finding", "finding_id"),
        Index("ix_review_decisions_time", "decided_at"),
    )


class HandoffReportRow(TimestampMixin, JSONPayloadMixin, Base):
    """An I-PASS/SBAR handoff draft."""

    __tablename__ = "handoff_reports"

    handoff_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(64), nullable=False)
    encounter_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(_STR_LEN), nullable=False, default="DRAFT")
    situation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assessment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    loop_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    pending_items: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confirmed_items: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_handoff_reports_patient", "patient_id"),
        Index("ix_handoff_reports_status", "status"),
    )


class AuditLogRow(TimestampMixin, JSONPayloadMixin, Base):
    """Append-only audit trail.

    There is deliberately no ``update``/``delete`` helper for this table
    anywhere in the codebase. Reviews and seals append here; they never
    overwrite an earlier entry (spec §7).
    """

    __tablename__ = "audit_logs"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False)
    old_state: Mapped[str | None] = mapped_column(String(_STR_LEN), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(_STR_LEN), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_audit_logs_entity_time", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_logs_action", "action"),
    )


# The enum classes are re-exported for callers that map rows back to
# contracts; importing them here keeps a single source of truth.
_ENUM_REFERENCES = (
    EventType,
    LoopState,
    FindingType,
    TrustLevel,
    IntentType,
    ReviewAction,
    HandoffStatus,
    StopReason,
    AgentStepKind,
)
