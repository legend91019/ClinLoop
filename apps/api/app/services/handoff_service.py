from __future__ import annotations

from sqlalchemy import select

from apps.api.app.db_models import Encounter, HandoffReportRow
from apps.api.app.repositories import AuditRepository, HandoffRepository
from apps.api.app.services.handoff_content_service import derive_handoff_content
from apps.api.app.services.handoff_write_service import update_current_draft
from packages.contracts import ActorRef, HandoffReport, HandoffStatus, new_id, utcnow


def create_draft(session, patient_id: str, encounter_id: str, actor: ActorRef) -> HandoffReport:
    if actor.role not in {"PHYSICIAN", "CLINICIAN"}:
        raise PermissionError("clinician role required")
    encounter = session.get(Encounter, encounter_id)
    if encounter is None or encounter.patient_id != patient_id:
        raise KeyError("encounter does not belong to this patient")
    content = derive_handoff_content(session, patient_id, encounter_id)
    report = HandoffReport(
        handoff_id=new_id("HAND"),
        patient_id=patient_id,
        encounter_id=encounter_id,
        created_by=actor,
        situation=f"合成病例 {patient_id}：{len(content.loop_ids)} 个高优先级未闭环事项。",
        background="\n".join(content.confirmed_items),
        assessment="工作流连续性待医生确认；本草稿不提供诊断或治疗建议。",
        recommendation="\n".join(content.loop_goals),
        **content.protected_fields(),
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
    if actor.role not in {"PHYSICIAN", "CLINICIAN"}:
        raise PermissionError("clinician role required")
    row = session.scalar(
        select(HandoffReportRow).where(HandoffReportRow.handoff_id == handoff_id).with_for_update()
    )
    if row is None:
        raise KeyError(handoff_id)
    if row.status != HandoffStatus.DRAFT.value:
        raise ValueError("only DRAFT handoffs can be sealed")
    content = derive_handoff_content(session, row.patient_id, row.encounter_id)
    if content.requires_review:
        raise ValueError("handoff cannot be sealed while a finding requires clinician review")
    derived = content.protected_fields()
    changes = {name: {"old": getattr(row, name), "new": value} for name, value in derived.items()}
    sealed_at = utcnow()
    update_current_draft(
        session,
        row,
        {
            **derived,
            "status": HandoffStatus.SEALED.value,
            "sealed_at": sealed_at,
            "payload": {
                **(row.payload or {}),
                **derived,
                "status": HandoffStatus.SEALED.value,
                "sealed_at": sealed_at.isoformat(),
            },
        },
    )
    AuditRepository(session).append(
        entity_type="handoff",
        entity_id=handoff_id,
        action="seal",
        actor=actor,
        old_state=HandoffStatus.DRAFT.value,
        new_state=HandoffStatus.SEALED.value,
        payload={"patient_id": row.patient_id, "changes": changes},
    )
    session.flush()
    report = HandoffRepository(session).get(handoff_id)
    assert report is not None
    return report
