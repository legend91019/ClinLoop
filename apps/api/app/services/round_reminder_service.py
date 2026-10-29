"""A persisted first-round reminder, completed only by a signed round note."""

import hashlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db_models import ClinicalDocumentRow, Encounter, OpenLoopRow, Patient
from apps.api.app.db_time import as_utc
from apps.api.app.repositories import AuditRepository, ClinicalIntentRepository, LoopRepository
from apps.api.app.services.patient_workspace_service import require_encounter
from packages.contracts import ActorRef, ClinicalIntent, IntentType, LoopState, OpenLoop, utcnow

SYSTEM = ActorRef(actor_id="ROUND-SCHEDULER", role="SYSTEM")


def round_status(session: Session, patient_id: str, encounter_id: str, *, now=None) -> dict:
    encounter = require_encounter(session, patient_id, encounter_id)
    now = now or utcnow()
    due = as_utc(encounter.admitted_at) + timedelta(hours=48) if encounter.admitted_at else None
    documents = session.scalars(
        select(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.patient_id == patient_id,
            ClinicalDocumentRow.encounter_id == encounter_id,
            ClinicalDocumentRow.kind == "ROUND",
            ClinicalDocumentRow.status == "SUBMITTED",
        )
        .order_by(ClinicalDocumentRow.submitted_at)
    ).all()
    signed = next(
        (
            doc
            for doc in documents
            if (doc.payload or {}).get("signature")
            and (
                not encounter.admitted_at
                or as_utc(doc.submitted_at) >= as_utc(encounter.admitted_at)
            )
        ),
        None,
    )
    state = (
        "COMPLETED"
        if signed
        else "UNSCHEDULED"
        if due is None
        else "OVERDUE"
        if now >= due
        else "PENDING"
    )
    return {
        "state": state,
        "due_at": due,
        "document_id": signed.document_id if signed else None,
        "signed_at": as_utc(signed.submitted_at) if signed else None,
        "completed_late": bool(signed and due and as_utc(signed.submitted_at) > due),
        "reminder_id": "ROUND-" + hashlib.sha256(encounter_id.encode()).hexdigest()[:40],
    }


def sync_round_reminders(session: Session, *, now=None) -> int:
    """Called by the worker, even without new clinical events or an open browser."""
    changed = 0
    encounters = session.scalars(
        select(Encounter)
        .join(Patient)
        .where(Patient.synthetic.is_(True), Encounter.discharged_at.is_(None))
    ).all()
    for encounter in encounters:
        status = round_status(session, encounter.patient_id, encounter.encounter_id, now=now)
        row = session.get(OpenLoopRow, status["reminder_id"])
        if status["state"] == "OVERDUE" and row is None:
            intent_id = "INT-" + status["reminder_id"]
            ClinicalIntentRepository(session).add(
                ClinicalIntent(
                    intent_id=intent_id,
                    patient_id=encounter.patient_id,
                    encounter_id=encounter.encounter_id,
                    intent_type=IntentType.UPDATE_PLAN,
                    text="入院48小时内完成首次查房并签署记录",
                )
            )
            loop = OpenLoop(
                loop_id=status["reminder_id"],
                patient_id=encounter.patient_id,
                encounter_id=encounter.encounter_id,
                intent_id=intent_id,
                goal="首次查房已逾期：请完成查房、审核并签署查房记录",
                priority="HIGH",
                owner=(encounter.payload or {}).get("attending_physician") or "主管医生（待分配）",
                next_check_at=status["due_at"],
            )
            repository = LoopRepository(session)
            repository.add(loop)
            repository.apply_transition(
                loop.loop_id,
                LoopState.PLANNED,
                reviewer=SYSTEM,
                reason="入院已满48小时，未找到医生签署的查房记录",
            )
            row = session.get(OpenLoopRow, loop.loop_id)
            row.payload = {**row.payload, "managed_by": "first_round", "source_document_id": None}
            changed += 1
        elif (
            row is not None
            and status["state"] == "COMPLETED"
            and row.state not in {"RESOLVED", "CANCELLED"}
        ):
            repository = LoopRepository(session)
            repository.apply_transition(
                row.loop_id,
                LoopState.PENDING_REVIEW,
                reviewer=SYSTEM,
                reason="检测到医生签署的查房记录",
            )
            repository.apply_transition(
                row.loop_id,
                LoopState.RESOLVED,
                reviewer=SYSTEM,
                reason=f"签署记录：{status['document_id']}",
            )
            row.payload = {**row.payload, "source_document_id": status["document_id"]}
            changed += 1
        if changed and row is not None and session.is_modified(row):
            AuditRepository(session).append(
                entity_type="open_loop",
                entity_id=row.loop_id,
                action="first_round_reminder",
                actor=SYSTEM,
                payload={"patient_id": encounter.patient_id, "state": row.state},
            )
    return changed
