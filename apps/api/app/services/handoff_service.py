from __future__ import annotations

from apps.api.app.db_models import HandoffReportRow
from apps.api.app.repositories import AuditRepository, EvidenceRepository, LoopRepository
from packages.contracts import ActorRef, HandoffReport, HandoffStatus, new_id, utcnow


def create_draft(session, patient_id: str, encounter_id: str, actor: ActorRef) -> HandoffReport:
    loops = LoopRepository(session).list_high_priority_open(patient_id)
    evidence = EvidenceRepository(session).list_for_patient(patient_id)
    report = HandoffReport(
        handoff_id=new_id("HAND"),
        patient_id=patient_id,
        encounter_id=encounter_id,
        created_by=actor,
        loop_ids=[loop.loop_id for loop in loops],
        evidence_ids=[
            node.evidence_id
            for node in evidence
            if node.trust_level.value in {"SYSTEM_VERIFIED", "CLINICIAN_CONFIRMED"}
        ],
        pending_items=[loop.goal for loop in loops],
        confirmed_items=[
            node.claim for node in evidence if node.trust_level.value == "CLINICIAN_CONFIRMED"
        ],
    )
    session.add(
        HandoffReportRow(
            handoff_id=report.handoff_id,
            patient_id=report.patient_id,
            encounter_id=report.encounter_id,
            status=report.status.value,
            situation=report.situation,
            background=report.background,
            assessment=report.assessment,
            recommendation=report.recommendation,
            loop_ids=report.loop_ids,
            evidence_ids=report.evidence_ids,
            pending_items=report.pending_items,
            confirmed_items=report.confirmed_items,
            created_by_id=actor.actor_id,
            created_by_role=actor.role,
            payload=report.model_dump(mode="json"),
        )
    )
    AuditRepository(session).append(
        entity_type="handoff",
        entity_id=report.handoff_id,
        action="draft",
        actor=actor,
        payload={"patient_id": patient_id},
    )
    session.flush()
    return report


def seal_handoff(session, handoff_id: str, actor: ActorRef) -> HandoffReport:
    row = session.get(HandoffReportRow, handoff_id)
    if row is None:
        raise KeyError(handoff_id)
    if row.status == HandoffStatus.SEALED.value:
        raise ValueError("handoff is already sealed")
    from sqlalchemy import select

    from apps.api.app.db_models import FindingRow

    pending_high_risk = session.scalar(
        select(FindingRow.finding_id).where(
            FindingRow.patient_id == row.patient_id,
            FindingRow.requires_review.is_(True),
            FindingRow.review_status == "PENDING_REVIEW",
        )
    )
    if pending_high_risk:
        raise ValueError("handoff cannot be sealed while a finding requires clinician review")
    row.status = HandoffStatus.SEALED.value
    row.sealed_at = utcnow()
    AuditRepository(session).append(
        entity_type="handoff",
        entity_id=handoff_id,
        action="seal",
        actor=actor,
        old_state=HandoffStatus.DRAFT.value,
        new_state=HandoffStatus.SEALED.value,
    )
    session.flush()
    return HandoffReport(
        handoff_id=row.handoff_id,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        status=row.status,
        situation=row.situation,
        background=row.background,
        assessment=row.assessment,
        recommendation=row.recommendation,
        loop_ids=row.loop_ids or [],
        evidence_ids=row.evidence_ids or [],
        pending_items=row.pending_items or [],
        confirmed_items=row.confirmed_items or [],
        sealed_at=row.sealed_at,
    )
