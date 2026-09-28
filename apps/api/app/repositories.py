"""Repositories: the only place that translates contracts <-> SQLAlchemy.

Rules (task 3/4):

* Route handlers never touch a ``Session`` directly.
* Repository methods accept and return **contracts**, never ORM rows.
* ``LoopRepository.apply_transition`` is the only way a loop state may
  change, and it always appends an audit entry. It refuses to write a
  state the deterministic policy rejects.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from apps.api.app.db_models import (
    AgentRunRow,
    AuditLogRow,
    ClinicalEventRow,
    ClinicalIntentRow,
    EvidenceNodeRow,
    FindingRow,
    HandoffReportRow,
    OpenLoopRow,
)
from apps.api.app.db_models import (
    Patient as PatientRow,
)
from apps.api.app.db_time import as_utc, as_utc_optional
from packages.contracts import (
    ACTIVE_LOOP_STATES,
    ActorRef,
    AgentRun,
    ClinicalEvent,
    ClinicalIntent,
    EventType,
    EvidenceNode,
    Finding,
    HandoffReport,
    LoopState,
    OpenLoop,
    TrustLevel,
    utcnow,
)
from packages.domain import validate_transition

__all__ = [
    "PatientRepository",
    "ClinicalEventRepository",
    "ClinicalIntentRepository",
    "LoopRepository",
    "EvidenceRepository",
    "FindingRepository",
    "AgentRunRepository",
    "HandoffRepository",
    "AuditRepository",
    "event_row_to_contract",
    "loop_row_to_contract",
    "evidence_row_to_contract",
    "finding_row_to_contract",
]


# ---------------------------------------------------------------------------
# Mappers
# ---------------------------------------------------------------------------


def event_row_to_contract(row: ClinicalEventRow) -> ClinicalEvent:
    return ClinicalEvent(
        event_id=row.event_id,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        event_type=EventType(row.event_type),
        event_time=as_utc(row.event_time),
        source_time=as_utc(row.source_time),
        payload_ref=row.payload_ref,
        actor=ActorRef(
            actor_id=row.actor_id,
            role=row.actor_role,
            display_name=row.actor_name,
        ),
        payload=row.payload or {},
        ingested_at=as_utc(row.created_at),
    )


def loop_row_to_contract(row: OpenLoopRow) -> OpenLoop:
    return OpenLoop(
        loop_id=row.loop_id,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        intent_id=row.intent_id,
        goal=row.goal,
        state=LoopState(row.state),
        waiting_for=[EventType(t) for t in (row.waiting_for or [])],
        depends_on=list(row.depends_on or []),
        owner=row.owner,
        last_plan=row.last_plan,
        confidence=row.confidence,
        priority=row.priority,
        next_check_at=as_utc_optional(row.next_check_at),
        last_planned_at=as_utc_optional(row.last_planned_at),
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
    )


def evidence_row_to_contract(row: EvidenceNodeRow) -> EvidenceNode:
    return EvidenceNode(
        evidence_id=row.evidence_id,
        patient_id=row.patient_id,
        source_type=row.source_type,
        source_id=row.source_id,
        observed_at=as_utc(row.observed_at),
        claim=row.claim,
        provenance=row.provenance or {},
        trust_level=TrustLevel(row.trust_level),
        verified_at=as_utc_optional(row.verified_at),
        created_at=as_utc(row.created_at),
    )


def finding_row_to_contract(row: FindingRow) -> Finding:
    return Finding(
        finding_id=row.finding_id,
        patient_id=row.patient_id,
        loop_id=row.loop_id,
        intent_id=row.intent_id,
        finding_type=row.finding_type,
        claim=row.claim,
        supporting_evidence=list(row.supporting_evidence or []),
        searched_sources=list(row.searched_sources or []),
        confidence=row.confidence,
        requires_review=row.requires_review,
        review_status=row.review_status,
        source_run_id=row.source_run_id,
        detected_at=as_utc(row.detected_at),
    )


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure(
        self,
        *,
        patient_id: str,
        encounter_id: str,
        display_name: str,
        ward: str | None = None,
    ) -> None:
        """Idempotently create the patient and encounter. Safe to re-run."""
        from apps.api.app.db_models import Encounter

        if self.session.get(PatientRow, patient_id) is None:
            self.session.add(
                PatientRow(
                    patient_id=patient_id,
                    display_name=display_name,
                    synthetic=True,
                    payload={},
                )
            )
        if self.session.get(Encounter, encounter_id) is None:
            self.session.add(
                Encounter(
                    encounter_id=encounter_id,
                    patient_id=patient_id,
                    ward=ward,
                    payload={},
                )
            )
        self.session.flush()

    def exists(self, patient_id: str) -> bool:
        return self.session.get(PatientRow, patient_id) is not None


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class ClinicalEventRepository:
    """Idempotent event store keyed on ``event_id``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def exists(self, event_id: str) -> bool:
        return self.session.get(ClinicalEventRow, event_id) is not None

    def add(self, event: ClinicalEvent) -> ClinicalEventRow:
        """Insert an event. The caller must check :meth:`exists` first.

        Raises:
            ValueError: when ``event_id`` is already present. The API maps
                this to ``409 Conflict``.
        """
        if self.exists(event.event_id):
            raise ValueError(f"duplicate event_id: {event.event_id}")

        row = ClinicalEventRow(
            event_id=event.event_id,
            patient_id=event.patient_id,
            encounter_id=event.encounter_id,
            event_type=event.event_type.value,
            event_time=event.event_time,
            source_time=event.source_time,
            payload_ref=event.payload_ref,
            actor_id=event.actor.actor_id,
            actor_role=event.actor.role,
            actor_name=event.actor.display_name,
            payload=event.payload,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, event_id: str) -> ClinicalEvent | None:
        row = self.session.get(ClinicalEventRow, event_id)
        return event_row_to_contract(row) if row else None

    def timeline(
        self,
        patient_id: str,
        *,
        hours: int = 24,
        now: datetime | None = None,
    ) -> list[ClinicalEvent]:
        """Events for ``patient_id`` in the last ``hours``, oldest first."""
        reference = now or utcnow()
        window_start = reference - timedelta(hours=hours)
        stmt: Select[tuple[ClinicalEventRow]] = (
            select(ClinicalEventRow)
            .where(
                ClinicalEventRow.patient_id == patient_id,
                ClinicalEventRow.event_time >= window_start,
                ClinicalEventRow.event_time <= reference,
            )
            .order_by(ClinicalEventRow.event_time.asc(), ClinicalEventRow.event_id.asc())
        )
        return [event_row_to_contract(row) for row in self.session.scalars(stmt)]

    def list_for_patient(self, patient_id: str) -> list[ClinicalEvent]:
        stmt = (
            select(ClinicalEventRow)
            .where(ClinicalEventRow.patient_id == patient_id)
            .order_by(ClinicalEventRow.event_time.asc())
        )
        return [event_row_to_contract(row) for row in self.session.scalars(stmt)]


# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------


class ClinicalIntentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, intent: ClinicalIntent) -> None:
        if self.session.get(ClinicalIntentRow, intent.intent_id) is not None:
            return
        self.session.add(
            ClinicalIntentRow(
                intent_id=intent.intent_id,
                patient_id=intent.patient_id,
                encounter_id=intent.encounter_id,
                intent_type=intent.intent_type.value,
                text=intent.text,
                expected_evidence=list(intent.expected_evidence),
                source_event_id=intent.source_event_id,
                requires_clinician_review=intent.requires_clinician_review,
                payload=intent.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def get(self, intent_id: str) -> ClinicalIntent | None:
        row = self.session.get(ClinicalIntentRow, intent_id)
        if row is None:
            return None
        return ClinicalIntent(
            intent_id=row.intent_id,
            patient_id=row.patient_id,
            encounter_id=row.encounter_id,
            intent_type=row.intent_type,
            text=row.text,
            expected_evidence=list(row.expected_evidence or []),
            source_event_id=row.source_event_id,
            requires_clinician_review=row.requires_clinician_review,
            created_at=as_utc(row.created_at),
        )

    def list_for_patient(self, patient_id: str) -> list[ClinicalIntent]:
        stmt = select(ClinicalIntentRow).where(ClinicalIntentRow.patient_id == patient_id)
        result: list[ClinicalIntent] = []
        for row in self.session.scalars(stmt):
            restored = self.get(row.intent_id)
            if restored is not None:
                result.append(restored)
        return result


# ---------------------------------------------------------------------------
# Loops
# ---------------------------------------------------------------------------


class LoopRepository:
    """Read/write access to Open Loops.

    State changes go exclusively through :meth:`apply_transition`, which
    delegates the decision to the deterministic policy and records an
    audit entry.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, loop: OpenLoop) -> None:
        if self.session.get(OpenLoopRow, loop.loop_id) is not None:
            return
        self.session.add(
            OpenLoopRow(
                loop_id=loop.loop_id,
                patient_id=loop.patient_id,
                encounter_id=loop.encounter_id,
                intent_id=loop.intent_id,
                goal=loop.goal,
                state=loop.state.value,
                waiting_for=[e.value for e in loop.waiting_for],
                depends_on=list(loop.depends_on),
                owner=loop.owner,
                last_plan=loop.last_plan,
                confidence=loop.confidence,
                priority=loop.priority,
                next_check_at=loop.next_check_at,
                last_planned_at=loop.last_planned_at,
                payload=loop.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def upsert(self, loop: OpenLoop) -> None:
        row = self.session.get(OpenLoopRow, loop.loop_id)
        if row is None:
            self.add(loop)
            return
        row.goal = loop.goal
        row.waiting_for = [e.value for e in loop.waiting_for]
        row.depends_on = list(loop.depends_on)
        row.owner = loop.owner
        row.last_plan = loop.last_plan
        row.confidence = loop.confidence
        row.priority = loop.priority
        row.next_check_at = loop.next_check_at
        row.last_planned_at = loop.last_planned_at
        row.updated_at = utcnow()
        self.session.flush()

    def get(self, loop_id: str) -> OpenLoop | None:
        row = self.session.get(OpenLoopRow, loop_id)
        return loop_row_to_contract(row) if row else None

    def list_for_patient(
        self,
        patient_id: str,
        *,
        states: Sequence[LoopState] | None = None,
        active_only: bool = False,
    ) -> list[OpenLoop]:
        stmt = select(OpenLoopRow).where(OpenLoopRow.patient_id == patient_id)
        if states is not None:
            stmt = stmt.where(OpenLoopRow.state.in_([s.value for s in states]))
        elif active_only:
            stmt = stmt.where(OpenLoopRow.state.in_([s.value for s in ACTIVE_LOOP_STATES]))
        stmt = stmt.order_by(OpenLoopRow.created_at.asc(), OpenLoopRow.loop_id.asc())
        return [loop_row_to_contract(row) for row in self.session.scalars(stmt)]

    def list_high_priority_open(self, patient_id: str) -> list[OpenLoop]:
        """Active loops at HIGH or CRITICAL priority — the handoff input."""
        stmt = (
            select(OpenLoopRow)
            .where(
                OpenLoopRow.patient_id == patient_id,
                OpenLoopRow.priority.in_(["HIGH", "CRITICAL"]),
                OpenLoopRow.state.in_([s.value for s in ACTIVE_LOOP_STATES]),
            )
            .order_by(OpenLoopRow.created_at.asc())
        )
        return [loop_row_to_contract(row) for row in self.session.scalars(stmt)]

    def apply_transition(
        self,
        loop_id: str,
        requested: LoopState,
        *,
        evidence_ids: Sequence[str] | None = None,
        reviewer: ActorRef | None = None,
        reason: str | None = None,
        source_run_id: str | None = None,
    ) -> OpenLoop:
        """Validate and persist a state change, appending an audit entry.

        Raises:
            KeyError: unknown loop.
            PermissionError: the policy rejects the change (missing evidence
                or missing clinician approval).
            InvalidTransition: the edge does not exist.
        """
        row = self.session.get(OpenLoopRow, loop_id)
        if row is None:
            raise KeyError(f"unknown loop_id: {loop_id}")

        current = LoopState(row.state)
        decision = validate_transition(
            current,
            requested,
            evidence_ids=evidence_ids,
            clinician_approved=reviewer is not None,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        row.state = requested.value
        row.updated_at = utcnow()
        self.session.flush()

        AuditRepository(self.session).append(
            entity_type="open_loop",
            entity_id=loop_id,
            actor=reviewer,
            action="state_transition",
            old_state=current.value,
            new_state=requested.value,
            reason=reason or decision.reason,
            source_run_id=source_run_id,
        )
        return loop_row_to_contract(row)

    def candidate_state_changes(self, loop_id: str) -> dict[str, str]:
        """States the agent may *propose* for this loop right now.

        Purely informational — nothing is written.
        """
        from packages.domain import allowed_targets

        loop = self.get(loop_id)
        if loop is None:
            return {}
        return {target.value: "candidate" for target in allowed_targets(loop.state)}


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class EvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def append(self, node: EvidenceNode, *, loop_id: str | None = None) -> None:
        if self.session.get(EvidenceNodeRow, node.evidence_id) is not None:
            return
        self.session.add(
            EvidenceNodeRow(
                evidence_id=node.evidence_id,
                patient_id=node.patient_id,
                loop_id=loop_id,
                source_type=node.source_type,
                source_id=node.source_id,
                observed_at=node.observed_at,
                claim=node.claim,
                trust_level=node.trust_level.value,
                provenance=node.provenance,
                verified_at=node.verified_at,
                payload=node.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def get(self, evidence_id: str) -> EvidenceNode | None:
        row = self.session.get(EvidenceNodeRow, evidence_id)
        return evidence_row_to_contract(row) if row else None

    def list_for_loop(self, loop_id: str) -> list[EvidenceNode]:
        stmt = (
            select(EvidenceNodeRow)
            .where(EvidenceNodeRow.loop_id == loop_id)
            .order_by(EvidenceNodeRow.observed_at.asc())
        )
        return [evidence_row_to_contract(row) for row in self.session.scalars(stmt)]

    def list_for_patient(self, patient_id: str) -> list[EvidenceNode]:
        stmt = (
            select(EvidenceNodeRow)
            .where(EvidenceNodeRow.patient_id == patient_id)
            .order_by(EvidenceNodeRow.observed_at.asc())
        )
        return [evidence_row_to_contract(row) for row in self.session.scalars(stmt)]

    def count_for_patient(self, patient_id: str) -> int:
        return len(self.list_for_patient(patient_id))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class FindingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, finding: Finding) -> None:
        if self.session.get(FindingRow, finding.finding_id) is not None:
            return
        self.session.add(
            FindingRow(
                finding_id=finding.finding_id,
                patient_id=finding.patient_id,
                loop_id=finding.loop_id,
                intent_id=finding.intent_id,
                finding_type=finding.finding_type.value,
                claim=finding.claim,
                supporting_evidence=list(finding.supporting_evidence),
                searched_sources=list(finding.searched_sources),
                confidence=finding.confidence,
                requires_review=finding.requires_review,
                review_status=finding.review_status,
                source_run_id=finding.source_run_id,
                detected_at=finding.detected_at,
                payload=finding.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def get(self, finding_id: str) -> Finding | None:
        row = self.session.get(FindingRow, finding_id)
        return finding_row_to_contract(row) if row else None

    def list_for_patient(self, patient_id: str) -> list[Finding]:
        stmt = (
            select(FindingRow)
            .where(FindingRow.patient_id == patient_id)
            .order_by(FindingRow.detected_at.asc())
        )
        return [finding_row_to_contract(row) for row in self.session.scalars(stmt)]

    def list_for_loop(self, loop_id: str) -> list[Finding]:
        stmt = (
            select(FindingRow)
            .where(FindingRow.loop_id == loop_id)
            .order_by(FindingRow.detected_at.asc())
        )
        return [finding_row_to_contract(row) for row in self.session.scalars(stmt)]

    def ids_for_loop(self, loop_id: str) -> list[str]:
        return [f.finding_id for f in self.list_for_loop(loop_id)]


# ---------------------------------------------------------------------------
# Agent runs
# ---------------------------------------------------------------------------


class AgentRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, run: AgentRun) -> None:
        if self.session.get(AgentRunRow, run.run_id) is not None:
            return
        self.session.add(AgentRunRow(**self._row_kwargs(run)))
        self.session.flush()

    def exists_for_trigger(self, trigger_event_id: str) -> bool:
        """True when this event already produced a run (idempotency)."""
        stmt = select(AgentRunRow.run_id).where(
            AgentRunRow.trigger_event_id == trigger_event_id,
            AgentRunRow.resumed_from_run_id.is_(None),
        )
        return self.session.scalars(stmt).first() is not None

    def append_trace(
        self,
        run_id: str,
        *,
        steps: list[dict[str, Any]] | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        plan: list[str] | None = None,
        finding_ids: list[str] | None = None,
        candidate_state_changes: dict[str, str] | None = None,
        stop_reason: str | None = None,
        finished: bool = False,
    ) -> None:
        row = self.session.get(AgentRunRow, run_id)
        if row is None:
            raise KeyError(f"unknown run_id: {run_id}")
        if steps:
            row.steps = [*(row.steps or []), *steps]
        if tool_calls:
            row.tool_calls = [*(row.tool_calls or []), *tool_calls]
        if plan is not None:
            row.plan = plan
        if finding_ids:
            row.finding_ids = [*(row.finding_ids or []), *finding_ids]
        if candidate_state_changes:
            row.candidate_state_changes = {
                **(row.candidate_state_changes or {}),
                **candidate_state_changes,
            }
        if stop_reason is not None:
            row.stop_reason = stop_reason
        if finished:
            row.finished_at = utcnow()
        row.updated_at = utcnow()
        self.session.flush()

    def list_for_patient(self, patient_id: str) -> list[AgentRun]:
        stmt = (
            select(AgentRunRow)
            .join(OpenLoopRow, OpenLoopRow.loop_id == AgentRunRow.loop_id, isouter=True)
            .where((OpenLoopRow.patient_id == patient_id) | (AgentRunRow.intent_id.is_not(None)))
            .order_by(AgentRunRow.started_at.asc())
        )
        return [self._to_contract(row) for row in self.session.scalars(stmt)]

    @staticmethod
    def _row_kwargs(run: AgentRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "loop_id": run.loop_id,
            "intent_id": run.intent_id,
            "trigger_event_id": run.trigger_event_id,
            "resumed_from_run_id": run.resumed_from_run_id,
            "plan": list(run.plan),
            "steps": [s.model_dump(mode="json") for s in run.steps],
            "tool_calls": [t.model_dump(mode="json") for t in run.tool_calls],
            "finding_ids": list(run.finding_ids),
            "candidate_state_changes": dict(run.candidate_state_changes),
            "stop_reason": run.stop_reason.value if run.stop_reason else None,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "payload": run.model_dump(mode="json"),
        }

    @staticmethod
    def _to_contract(row: AgentRunRow) -> AgentRun:
        return AgentRun(
            run_id=row.run_id,
            loop_id=row.loop_id,
            intent_id=row.intent_id,
            trigger_event_id=row.trigger_event_id,
            resumed_from_run_id=row.resumed_from_run_id,
            plan=list(row.plan or []),
            steps=row.steps or [],
            tool_calls=row.tool_calls or [],
            finding_ids=list(row.finding_ids or []),
            candidate_state_changes=dict(row.candidate_state_changes or {}),
            stop_reason=row.stop_reason,
            started_at=as_utc(row.started_at),
            finished_at=as_utc_optional(row.finished_at),
        )


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


class HandoffRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, report: HandoffReport) -> None:
        if self.session.get(HandoffReportRow, report.handoff_id) is not None:
            return
        self.session.add(
            HandoffReportRow(
                handoff_id=report.handoff_id,
                patient_id=report.patient_id,
                encounter_id=report.encounter_id,
                status=report.status.value,
                situation=report.situation,
                background=report.background,
                assessment=report.assessment,
                recommendation=report.recommendation,
                loop_ids=list(report.loop_ids),
                evidence_ids=list(report.evidence_ids),
                pending_items=list(report.pending_items),
                confirmed_items=list(report.confirmed_items),
                created_by_id=report.created_by.actor_id if report.created_by else None,
                created_by_role=report.created_by.role if report.created_by else None,
                sealed_at=report.sealed_at,
                payload=report.model_dump(mode="json"),
            )
        )
        self.session.flush()

    def get(self, handoff_id: str) -> HandoffReport | None:
        row = self.session.get(HandoffReportRow, handoff_id)
        if row is None:
            return None
        return HandoffReport(
            handoff_id=row.handoff_id,
            patient_id=row.patient_id,
            encounter_id=row.encounter_id,
            status=row.status,
            situation=row.situation,
            background=row.background,
            assessment=row.assessment,
            recommendation=row.recommendation,
            loop_ids=list(row.loop_ids or []),
            evidence_ids=list(row.evidence_ids or []),
            pending_items=list(row.pending_items or []),
            confirmed_items=list(row.confirmed_items or []),
            created_at=as_utc(row.created_at),
            sealed_at=as_utc_optional(row.sealed_at),
        )

    def list_for_patient(self, patient_id: str) -> list[HandoffReport]:
        stmt = (
            select(HandoffReportRow.handoff_id)
            .where(HandoffReportRow.patient_id == patient_id)
            .order_by(HandoffReportRow.created_at.asc())
        )
        reports: list[HandoffReport] = []
        for handoff_id in self.session.scalars(stmt):
            report = self.get(handoff_id)
            if report is not None:
                reports.append(report)
        return reports


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class AuditRepository:
    """Append-only audit trail.

    There is intentionally no update or delete path. Neither method exists,
    so it cannot be called by accident (spec §7, task 8).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def append(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: ActorRef | None = None,
        old_state: str | None = None,
        new_state: str | None = None,
        reason: str | None = None,
        source_run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            AuditLogRow(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                actor_id=actor.actor_id if actor else "system",
                actor_role=actor.role if actor else "SYSTEM",
                old_state=old_state,
                new_state=new_state,
                reason=reason,
                source_run_id=source_run_id,
                payload=payload or {},
            )
        )
        self.session.flush()

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[AuditLogRow]:
        stmt = (
            select(AuditLogRow)
            .where(AuditLogRow.entity_type == entity_type, AuditLogRow.entity_id == entity_id)
            .order_by(AuditLogRow.created_at.asc(), AuditLogRow.audit_id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_for_patient(self, patient_id: str) -> list[AuditLogRow]:
        """Audit entries for a patient and everything that hangs off them."""
        stmt = (
            select(AuditLogRow)
            .where(
                (AuditLogRow.entity_id == patient_id)
                | (AuditLogRow.payload["patient_id"].as_string() == patient_id)
            )
            .order_by(AuditLogRow.created_at.asc(), AuditLogRow.audit_id.asc())
        )
        return list(self.session.scalars(stmt))

    def count(self) -> int:
        return len(list(self.session.scalars(select(AuditLogRow.audit_id))))
