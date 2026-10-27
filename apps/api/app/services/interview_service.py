"""Preserve transcripts separately from clinician-signed clinical documents."""

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.db_models import ClinicalDocumentRow, EventPublicationRow
from apps.api.app.db_time import as_utc
from apps.api.app.repositories import AuditRepository, ClinicalEventRepository
from apps.api.app.services.patient_workspace_service import document_response, require_encounter
from packages.contracts import ActorRef, ClinicalEvent, EventType, new_id, utcnow
from packages.contracts.interviews import InterviewCreate, InterviewRedraft


def interview_response(session: Session, row: ClinicalDocumentRow) -> dict:
    generation = (row.payload or {}).get("drafting", {})
    draft = (
        session.get(ClinicalDocumentRow, generation.get("document_id"))
        if generation.get("document_id")
        else None
    )
    return {
        "interview_id": row.document_id,
        "patient_id": row.patient_id,
        "encounter_id": row.encounter_id,
        "transcript": row.content,
        "kind": row.payload["requested_kind"],
        "saved_at": as_utc(row.created_at),
        "author_id": row.author_id,
        "generation": generation,
        "document": document_response(draft).model_dump(mode="json") if draft else None,
    }


def get_interview(session: Session, patient_id: str, interview_id: str) -> ClinicalDocumentRow:
    row = session.get(ClinicalDocumentRow, interview_id)
    if row is None or row.patient_id != patient_id or row.kind != "INTERVIEW":
        raise HTTPException(404, "当前患者没有这份问诊原文")
    require_encounter(session, patient_id, row.encounter_id)
    return row


def queue_generation(
    session: Session, row: ClinicalDocumentRow, actor: ActorRef, *, mode: str, request_id: str
):
    now = utcnow()
    event = ClinicalEvent(
        event_id=new_id("EVT"),
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        event_type=EventType.INTERVIEW_SAVED,
        event_time=now,
        source_time=now,
        payload_ref=row.document_id,
        actor=actor,
        payload={
            "interview_id": row.document_id,
            "draft_mode": mode,
            "title": "根据原始对话撰写临床文书（待医生审核）",
        },
    )
    ClinicalEventRepository(session).add(event)
    session.add(EventPublicationRow(event_id=event.event_id, payload={}))
    row.payload = {
        **row.payload,
        "drafting": {
            "status": "QUEUED",
            "event_id": event.event_id,
            "draft_mode": mode,
            "request_id": request_id,
        },
    }


def save_interview(
    session: Session, patient_id: str, body: InterviewCreate, actor: ActorRef
) -> dict:
    require_encounter(session, patient_id, body.encounter_id)
    interview_id = f"INTV-{body.request_id}"
    existing = session.get(ClinicalDocumentRow, interview_id)
    if existing:
        if (
            existing.patient_id != patient_id
            or existing.encounter_id != body.encounter_id
            or existing.content != body.transcript
            or existing.payload.get("requested_kind") != body.kind
            or existing.payload.get("initial_draft_mode", "DEMO") != body.draft_mode
        ):
            raise HTTPException(409, "请求标识已用于另一份问诊，请刷新后重试")
        return interview_response(session, existing)
    row = ClinicalDocumentRow(
        document_id=interview_id,
        patient_id=patient_id,
        encounter_id=body.encounter_id,
        kind="INTERVIEW",
        title="问诊转录原文",
        content=body.transcript,
        status="TRANSCRIPT",
        author_id=actor.actor_id,
        revision=1,
        payload={"requested_kind": body.kind, "initial_draft_mode": body.draft_mode},
    )
    session.add(row)
    session.flush()
    queue_generation(session, row, actor, mode=body.draft_mode, request_id=body.request_id)
    AuditRepository(session).append(
        entity_type="interview",
        entity_id=interview_id,
        action="save_transcript",
        actor=actor,
        payload={"patient_id": patient_id},
    )
    return interview_response(session, row)


def list_interviews(session: Session, patient_id: str, encounter_id: str) -> list[dict]:
    require_encounter(session, patient_id, encounter_id)
    rows = session.scalars(
        select(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.patient_id == patient_id,
            ClinicalDocumentRow.encounter_id == encounter_id,
            ClinicalDocumentRow.kind == "INTERVIEW",
        )
        .order_by(ClinicalDocumentRow.created_at.desc())
    )
    return [interview_response(session, row) for row in rows]


def retry_generation(session: Session, patient_id: str, interview_id: str, actor: ActorRef) -> dict:
    row = get_interview(session, patient_id, interview_id)
    if row.payload.get("drafting", {}).get("status") != "FAILED":
        return interview_response(session, row)
    revision = row.revision
    changed = session.execute(
        update(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.document_id == interview_id,
            ClinicalDocumentRow.revision == revision,
        )
        .values(revision=revision + 1)
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "其他请求已更新生成状态，请刷新后查看")
    queue_generation(
        session,
        row,
        actor,
        mode=row.payload.get("drafting", {}).get("draft_mode", "DEMO"),
        request_id=new_id("REQ"),
    )
    return interview_response(session, row)


def redraft(
    session: Session, patient_id: str, interview_id: str, body: InterviewRedraft, actor: ActorRef
) -> dict:
    row = get_interview(session, patient_id, interview_id)
    state = row.payload.get("drafting", {})
    if state.get("request_id") == body.request_id:
        if state.get("draft_mode") != body.draft_mode:
            raise HTTPException(409, "请求标识已用于另一种撰写方式")
        return interview_response(session, row)
    if state.get("status") == "QUEUED":
        raise HTTPException(409, "已有病历正在撰写，请等待完成后再生成新版本")
    changed = session.execute(
        update(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.document_id == interview_id,
            ClinicalDocumentRow.revision == row.revision,
        )
        .values(revision=row.revision + 1)
    )
    if changed.rowcount != 1:
        raise HTTPException(409, "撰写状态已更新，请刷新后重试")
    queue_generation(session, row, actor, mode=body.draft_mode, request_id=body.request_id)
    AuditRepository(session).append(
        entity_type="interview",
        entity_id=row.document_id,
        action="redraft_clinical_note",
        actor=actor,
        payload={"patient_id": patient_id, "draft_mode": body.draft_mode},
    )
    return interview_response(session, row)
