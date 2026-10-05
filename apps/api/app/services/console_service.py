"""Draft text editing with immutable provenance and append-only audit."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db_models import HandoffReportRow
from apps.api.app.repositories import AuditRepository, HandoffRepository
from apps.api.app.services.handoff_write_service import update_current_draft
from packages.contracts import ActorRef, HandoffReport, HandoffStatus
from packages.contracts.console import HandoffDraftUpdate


def edit_handoff_draft(
    session: Session, handoff_id: str, update: HandoffDraftUpdate, actor: ActorRef
) -> HandoffReport:
    if actor.role not in {"PHYSICIAN", "CLINICIAN"}:
        raise PermissionError("clinician role required")
    row = session.scalar(
        select(HandoffReportRow).where(HandoffReportRow.handoff_id == handoff_id).with_for_update()
    )
    if row is None:
        raise KeyError(handoff_id)
    if row.status != HandoffStatus.DRAFT.value:
        raise ValueError("only DRAFT handoffs are editable")
    fields = update.model_dump(exclude_unset=True)
    changes = {name: {"old": getattr(row, name), "new": value} for name, value in fields.items()}
    update_current_draft(session, row, {**fields, "payload": {**(row.payload or {}), **fields}})
    AuditRepository(session).append(
        entity_type="handoff",
        entity_id=handoff_id,
        action="edit_draft",
        actor=actor,
        old_state=row.status,
        new_state=row.status,
        payload={"patient_id": row.patient_id, "changes": changes},
    )
    session.flush()
    report = HandoffRepository(session).get(handoff_id)
    assert report is not None
    return report
