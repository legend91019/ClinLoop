"""initial workflow schema

Creates the eleven core ClinLoop tables:

    patients, encounters, clinical_events, clinical_intents, open_loops,
    evidence_nodes, findings, agent_runs, review_decisions,
    handoff_reports, audit_logs

Every table carries ``created_at``/``updated_at`` and a JSON ``payload``
holding the original source record. Enum-valued columns are stored as
strings so SQLite and PostgreSQL behave identically and adding an enum
member is a data change, not a DDL migration.

Revision ID: 0001
Revises:
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Enum-like columns are plain strings of this width.
_STR = 32


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "patients",
        sa.Column("patient_id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_patients_synthetic", "patients", ["synthetic"])

    op.create_table(
        "encounters",
        sa.Column("encounter_id", sa.String(64), primary_key=True),
        sa.Column(
            "patient_id",
            sa.String(64),
            sa.ForeignKey("patients.patient_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ward", sa.String(64), nullable=True),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discharged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_encounters_patient", "encounters", ["patient_id"])

    op.create_table(
        "clinical_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("encounter_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(_STR), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_ref", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("actor_role", sa.String(64), nullable=False),
        sa.Column("actor_name", sa.String(128), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_clinical_events_patient_event_time",
        "clinical_events",
        ["patient_id", "event_time"],
    )
    op.create_index("ix_clinical_events_type", "clinical_events", ["event_type"])
    op.create_index("ix_clinical_events_encounter", "clinical_events", ["encounter_id"])

    op.create_table(
        "clinical_intents",
        sa.Column("intent_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("encounter_id", sa.String(64), nullable=False),
        sa.Column("intent_type", sa.String(_STR), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("expected_evidence", sa.JSON(), nullable=False),
        sa.Column("source_event_id", sa.String(64), nullable=True),
        sa.Column("requires_clinician_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_clinical_intents_patient", "clinical_intents", ["patient_id"])
    op.create_index("ix_clinical_intents_source_event", "clinical_intents", ["source_event_id"])

    op.create_table(
        "open_loops",
        sa.Column("loop_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("encounter_id", sa.String(64), nullable=False),
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("state", sa.String(_STR), nullable=False),
        sa.Column("waiting_for", sa.JSON(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("owner", sa.String(64), nullable=True),
        sa.Column("last_plan", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="NORMAL"),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_open_loops_patient_state", "open_loops", ["patient_id", "state"])
    op.create_index("ix_open_loops_intent", "open_loops", ["intent_id"])
    op.create_index("ix_open_loops_priority", "open_loops", ["priority"])
    op.create_index("ix_open_loops_state", "open_loops", ["state"])

    op.create_table(
        "evidence_nodes",
        sa.Column("evidence_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("loop_id", sa.String(64), nullable=True),
        sa.Column("source_type", sa.String(_STR), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("trust_level", sa.String(_STR), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_evidence_nodes_patient", "evidence_nodes", ["patient_id"])
    op.create_index(
        "ix_evidence_nodes_loop_observed_at", "evidence_nodes", ["loop_id", "observed_at"]
    )
    op.create_index(
        "ix_evidence_nodes_source", "evidence_nodes", ["source_type", "source_id"]
    )

    op.create_table(
        "findings",
        sa.Column("finding_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("loop_id", sa.String(64), nullable=True),
        sa.Column("intent_id", sa.String(64), nullable=True),
        sa.Column("finding_type", sa.String(_STR), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("supporting_evidence", sa.JSON(), nullable=False),
        sa.Column("searched_sources", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("requires_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("review_status", sa.String(_STR), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("source_run_id", sa.String(64), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_findings_patient_type", "findings", ["patient_id", "finding_type"])
    op.create_index("ix_findings_loop", "findings", ["loop_id"])
    op.create_index("ix_findings_review_status", "findings", ["review_status"])

    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("loop_id", sa.String(64), nullable=True),
        sa.Column("intent_id", sa.String(64), nullable=True),
        sa.Column("trigger_event_id", sa.String(64), nullable=False),
        sa.Column("resumed_from_run_id", sa.String(64), nullable=True),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=False),
        sa.Column("finding_ids", sa.JSON(), nullable=False),
        sa.Column("candidate_state_changes", sa.JSON(), nullable=False),
        sa.Column("stop_reason", sa.String(_STR), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "trigger_event_id", "resumed_from_run_id", name="uq_agent_runs_origin"
        ),
    )
    op.create_index("ix_agent_runs_trigger_event", "agent_runs", ["trigger_event_id"])
    op.create_index("ix_agent_runs_loop", "agent_runs", ["loop_id"])

    op.create_table(
        "review_decisions",
        sa.Column("decision_id", sa.String(64), primary_key=True),
        sa.Column(
            "finding_id",
            sa.String(64),
            sa.ForeignKey("findings.finding_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(_STR), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("reviewer_role", sa.String(64), nullable=False),
        sa.Column("reviewer_name", sa.String(128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_review_decisions_finding", "review_decisions", ["finding_id"])
    op.create_index("ix_review_decisions_time", "review_decisions", ["decided_at"])

    op.create_table(
        "handoff_reports",
        sa.Column("handoff_id", sa.String(64), primary_key=True),
        sa.Column("patient_id", sa.String(64), nullable=False),
        sa.Column("encounter_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(_STR), nullable=False, server_default="DRAFT"),
        sa.Column("situation", sa.Text(), nullable=False, server_default=""),
        sa.Column("background", sa.Text(), nullable=False, server_default=""),
        sa.Column("assessment", sa.Text(), nullable=False, server_default=""),
        sa.Column("recommendation", sa.Text(), nullable=False, server_default=""),
        sa.Column("loop_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("pending_items", sa.JSON(), nullable=False),
        sa.Column("confirmed_items", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.String(64), nullable=True),
        sa.Column("created_by_role", sa.String(64), nullable=True),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_handoff_reports_patient", "handoff_reports", ["patient_id"])
    op.create_index("ix_handoff_reports_status", "handoff_reports", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("audit_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("actor_role", sa.String(64), nullable=False),
        sa.Column("old_state", sa.String(_STR), nullable=True),
        sa.Column("new_state", sa.String(_STR), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source_run_id", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_audit_logs_entity_time", "audit_logs", ["entity_type", "entity_id", "created_at"]
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("handoff_reports")
    op.drop_table("review_decisions")
    op.drop_table("agent_runs")
    op.drop_table("findings")
    op.drop_table("evidence_nodes")
    op.drop_table("open_loops")
    op.drop_table("clinical_intents")
    op.drop_table("clinical_events")
    op.drop_table("encounters")
    op.drop_table("patients")
