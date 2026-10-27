"""Patient directory, draft documents and explicitly clinician-managed tasks."""

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from apps.api.app.db_models import (
    ClinicalDocumentRow,
    Encounter,
    EventPublicationRow,
    OpenLoopRow,
    Patient,
)
from apps.api.app.db_time import as_utc, as_utc_optional
from apps.api.app.repositories import (
    AuditRepository,
    ClinicalEventRepository,
    ClinicalIntentRepository,
    EvidenceRepository,
    LoopRepository,
)
from packages.contracts import (
    ActorRef,
    ClinicalEvent,
    ClinicalIntent,
    EventType,
    EvidenceNode,
    IntentType,
    LoopState,
    OpenLoop,
    TrustLevel,
    new_id,
    utcnow,
)
from packages.contracts.workspace import (
    DocumentCreate,
    DocumentEdit,
    DocumentResponse,
    PatientCreate,
    PatientSummary,
    TaskCreate,
    TaskHistory,
    TaskResponse,
    TaskUpdate,
)


def require_encounter(session: Session, patient_id: str, encounter_id: str) -> Encounter:
    patient = session.get(Patient, patient_id)
    encounter = session.get(Encounter, encounter_id)
    if patient is None or encounter is None or encounter.patient_id != patient_id:
        raise HTTPException(404, "患者或就诊记录不存在，或不属于当前患者")
    if not patient.synthetic:
        raise HTTPException(403, "此工作台仅支持模拟患者")
    return encounter


def list_patients(session: Session) -> list[PatientSummary]:
    counts = dict(
        session.execute(
            select(OpenLoopRow.encounter_id, func.count())
            .where(OpenLoopRow.state.notin_(["RESOLVED", "CANCELLED"]))
            .group_by(OpenLoopRow.encounter_id)
        ).all()
    )
    result = []
    for patient in session.scalars(
        select(Patient).where(Patient.synthetic.is_(True)).order_by(Patient.patient_id)
    ):
        for encounter in sorted(patient.encounters, key=lambda item: item.encounter_id):
            profile = patient.payload or {}
            result.append(
                PatientSummary(
                    patient_id=patient.patient_id,
                    encounter_id=encounter.encounter_id,
                    display_name=patient.display_name,
                    sex=profile.get("sex", "未说明"),
                    age=profile.get("age", 40),
                    ethnicity=profile.get("ethnicity", "未记录"),
                    marital_status=profile.get("marital_status", "未记录"),
                    birthplace=profile.get("birthplace", "未记录"),
                    occupation=profile.get("occupation", "未记录"),
                    ward=encounter.ward or "模拟病区",
                    bed=(encounter.payload or {}).get("bed", ""),
                    chief_complaint=profile.get("chief_complaint", ""),
                    history=profile.get("history", ""),
                    allergies=profile.get("allergies", "未记录"),
                    admitted_at=as_utc_optional(encounter.admitted_at),
                    synthetic=True,
                    open_tasks=counts.get(encounter.encounter_id, 0),
                )
            )
    return result


def create_patient(session: Session, body: PatientCreate, actor: ActorRef) -> str:
    patient_id, encounter_id = new_id("P"), new_id("ENC")
    session.add(
        Patient(
            patient_id=patient_id,
            display_name=body.display_name,
            synthetic=True,
            payload=body.model_dump(mode="json"),
        )
    )
    session.flush()
    session.add(
        Encounter(
            encounter_id=encounter_id,
            patient_id=patient_id,
            ward=body.ward,
            admitted_at=as_utc(body.admitted_at) if body.admitted_at else utcnow(),
            payload={"bed": body.bed, "attending_physician": actor.actor_id},
        )
    )
    AuditRepository(session).append(
        entity_type="patient",
        entity_id=patient_id,
        action="create_synthetic_patient",
        actor=actor,
        payload={"patient_id": patient_id},
    )
    session.flush()
    return patient_id


def document_response(row: ClinicalDocumentRow) -> DocumentResponse:
    return DocumentResponse(
        document_id=row.document_id,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        kind=row.kind,
        title=row.title,
        content=row.content,
        status=row.status,
        revision=row.revision,
        author_id=row.author_id,
        created_at=as_utc(row.created_at),
        updated_at=as_utc(row.updated_at),
        submitted_at=as_utc_optional(row.submitted_at),
        event_id=row.event_id,
        generation=(row.payload or {}).get("generation"),
        signature=(row.payload or {}).get("signature"),
    )


def get_document(session: Session, patient_id: str, document_id: str) -> ClinicalDocumentRow:
    row = session.get(ClinicalDocumentRow, document_id)
    if row is None or row.patient_id != patient_id:
        raise HTTPException(404, "当前患者没有这份文书")
    return row


def list_documents(session: Session, patient_id: str, encounter_id: str) -> list[DocumentResponse]:
    require_encounter(session, patient_id, encounter_id)
    rows = session.scalars(
        select(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.patient_id == patient_id,
            ClinicalDocumentRow.encounter_id == encounter_id,
            ClinicalDocumentRow.kind != "INTERVIEW",
        )
        .order_by(ClinicalDocumentRow.created_at.desc(), ClinicalDocumentRow.document_id)
    )
    return [document_response(row) for row in rows]


def create_document(
    session: Session, patient_id: str, body: DocumentCreate, actor: ActorRef
) -> DocumentResponse:
    require_encounter(session, patient_id, body.encounter_id)
    row = ClinicalDocumentRow(
        document_id=new_id("DOC"),
        patient_id=patient_id,
        encounter_id=body.encounter_id,
        kind=body.kind,
        title=body.title,
        content=body.content,
        author_id=actor.actor_id,
        status="DRAFT",
        revision=1,
    )
    session.add(row)
    session.flush()
    AuditRepository(session).append(
        entity_type="clinical_document",
        entity_id=row.document_id,
        action="create_draft",
        actor=actor,
        payload={"patient_id": patient_id},
    )
    return document_response(row)


def edit_document(
    session: Session, patient_id: str, document_id: str, body: DocumentEdit, actor: ActorRef
) -> DocumentResponse:
    get_document(session, patient_id, document_id)
    result = session.execute(
        update(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.document_id == document_id,
            ClinicalDocumentRow.patient_id == patient_id,
            ClinicalDocumentRow.status == "DRAFT",
            ClinicalDocumentRow.revision == body.revision,
        )
        .values(
            title=body.title, content=body.content, revision=body.revision + 1, updated_at=utcnow()
        )
    )
    if result.rowcount != 1:
        raise HTTPException(409, "文书已被修改或已提交，请重新加载后操作")
    AuditRepository(session).append(
        entity_type="clinical_document",
        entity_id=document_id,
        action="update_draft",
        actor=actor,
        payload={"patient_id": patient_id, "revision": body.revision + 1},
    )
    session.expire_all()
    return document_response(get_document(session, patient_id, document_id))


def queue_event(
    session: Session, patient_id: str, encounter_id: str, actor: ActorRef, text: str, **payload
) -> ClinicalEvent:
    now = utcnow()
    event = ClinicalEvent(
        event_id=new_id("EVT"),
        patient_id=patient_id,
        encounter_id=encounter_id,
        event_type=EventType.PROGRESS_NOTE_CREATED,
        event_time=now,
        source_time=now,
        payload_ref=new_id("NOTE"),
        actor=actor,
        payload={"text": text, **payload},
    )
    ClinicalEventRepository(session).add(event)
    session.add(EventPublicationRow(event_id=event.event_id, payload={}))
    return event


def submit_document(
    session: Session,
    patient_id: str,
    document_id: str,
    revision: int,
    actor: ActorRef,
    signature_name: str | None = None,
    confirmed: bool = False,
) -> DocumentResponse:
    row = get_document(session, patient_id, document_id)
    require_encounter(session, patient_id, row.encounter_id)
    if row.status == "SUBMITTED":
        return document_response(row)
    if row.kind == "INTERVIEW":
        raise HTTPException(409, "问诊原文不能作为病历签署，请核对生成的病历草稿")
    if (row.payload or {}).get("generation") and (
        not signature_name or not signature_name.strip() or not confirmed
    ):
        raise HTTPException(422, "Agent 病历须填写医生签名，并确认已核对问诊原文与病历内容")
    result = session.execute(
        update(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.document_id == document_id,
            ClinicalDocumentRow.status == "DRAFT",
            ClinicalDocumentRow.revision == revision,
        )
        .values(
            status="SUBMITTED", revision=revision + 1, submitted_at=utcnow(), updated_at=utcnow()
        )
    )
    if result.rowcount != 1:
        raise HTTPException(409, "草稿版本已变化，请重新加载后提交")
    session.expire_all()
    row = get_document(session, patient_id, document_id)
    if signature_name and confirmed:
        row.payload = {
            **(row.payload or {}),
            "signature": {
                "name": signature_name.strip(),
                "actor_id": actor.actor_id,
                "role": actor.role,
                "signed_at": utcnow().isoformat(),
                "revision": revision,
            },
        }
    event = queue_event(
        session,
        patient_id,
        row.encounter_id,
        actor,
        row.content,
        document_id=document_id,
        document_kind=row.kind,
        title=row.title,
    )
    row.event_id = event.event_id
    row.payload = {
        **(row.payload or {}),
        "agent_analysis": {
            "status": "QUEUED",
            "event_id": event.event_id,
            "run_id": None,
            "candidates": [],
        },
    }
    EvidenceRepository(session).append(
        EvidenceNode(
            evidence_id=new_id("EVI"),
            patient_id=patient_id,
            encounter_id=row.encounter_id,
            source_type="NOTES",
            source_id=event.payload_ref,
            observed_at=event.event_time,
            claim=f"{row.title}：{row.content}",
            provenance={"event_id": event.event_id, "document_id": document_id},
            trust_level=TrustLevel.CLINICIAN_CONFIRMED,
            verified_at=utcnow(),
        )
    )
    AuditRepository(session).append(
        entity_type="clinical_document",
        entity_id=document_id,
        action="submit_document",
        actor=actor,
        payload={"patient_id": patient_id, "event_id": event.event_id},
    )
    session.flush()
    if row.kind == "ROUND" and (row.payload or {}).get("signature"):
        from apps.api.app.services.round_reminder_service import sync_round_reminders

        sync_round_reminders(session)
    return document_response(row)


def task_response(session: Session, row: OpenLoopRow) -> TaskResponse:
    return TaskResponse(
        loop_id=row.loop_id,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        goal=row.goal,
        state=row.state,
        priority=row.priority,
        owner=row.owner,
        due_at=as_utc_optional(row.next_check_at),
        source_document_id=row.payload.get("source_document_id"),
        system_managed=row.payload.get("managed_by") == "first_round",
        history=[
            TaskHistory(
                action=item.action,
                actor_id=item.actor_id,
                reason=item.reason,
                created_at=as_utc(item.created_at),
            )
            for item in AuditRepository(session).list_for_entity("open_loop", row.loop_id)
        ],
    )


def list_tasks(session: Session, patient_id: str, encounter_id: str) -> list[TaskResponse]:
    require_encounter(session, patient_id, encounter_id)
    rows = session.scalars(
        select(OpenLoopRow)
        .where(OpenLoopRow.patient_id == patient_id, OpenLoopRow.encounter_id == encounter_id)
        .order_by(OpenLoopRow.created_at.desc())
    )
    return [
        task_response(session, row)
        for row in rows
        if row.payload.get("managed_by") in {"patient_workspace", "first_round"}
    ]


def create_task(
    session: Session, patient_id: str, body: TaskCreate, actor: ActorRef
) -> TaskResponse:
    require_encounter(session, patient_id, body.encounter_id)
    if body.source_document_id:
        doc = get_document(session, patient_id, body.source_document_id)
        if doc.encounter_id != body.encounter_id or doc.status != "SUBMITTED":
            raise HTTPException(409, "只能关联当前就诊已提交的文书")
    event = queue_event(session, patient_id, body.encounter_id, actor, f"创建随访任务：{body.goal}")
    intent = ClinicalIntent(
        intent_id=new_id("INT"),
        patient_id=patient_id,
        encounter_id=body.encounter_id,
        intent_type=IntentType.UPDATE_PLAN,
        text=body.goal,
        source_event_id=event.event_id,
    )
    ClinicalIntentRepository(session).add(intent)
    loop = OpenLoop(
        loop_id=new_id("LOOP"),
        patient_id=patient_id,
        encounter_id=body.encounter_id,
        intent_id=intent.intent_id,
        goal=body.goal,
        owner=body.owner,
        priority=body.priority,
        next_check_at=body.due_at,
    )
    repository = LoopRepository(session)
    repository.add(loop)
    repository.apply_transition(
        loop.loop_id, LoopState.PLANNED, reviewer=actor, reason="医生创建跟进任务"
    )
    row = session.get(OpenLoopRow, loop.loop_id)
    row.payload = {
        **row.payload,
        "managed_by": "patient_workspace",
        "source_document_id": body.source_document_id,
    }
    AuditRepository(session).append(
        entity_type="open_loop",
        entity_id=loop.loop_id,
        action="create_task",
        actor=actor,
        reason=body.goal,
        payload={"patient_id": patient_id},
    )
    return task_response(session, row)


def update_task(
    session: Session, patient_id: str, loop_id: str, body: TaskUpdate, actor: ActorRef
) -> TaskResponse:
    row = session.get(OpenLoopRow, loop_id)
    if (
        row is None
        or row.patient_id != patient_id
        or row.payload.get("managed_by") not in {"patient_workspace", "workspace_agent"}
    ):
        raise HTTPException(404, "当前患者没有这项手动任务")
    require_encounter(session, patient_id, row.encounter_id)
    if body.expected_state not in {"PLANNED", "IN_PROGRESS"}:
        raise HTTPException(409, "已结束的任务不能再次修改")
    if body.state == body.expected_state:
        raise HTTPException(409, "任务已处于该状态")
    result = session.execute(
        update(OpenLoopRow)
        .where(OpenLoopRow.loop_id == loop_id, OpenLoopRow.state == body.expected_state)
        .values(updated_at=utcnow())
    )
    if result.rowcount != 1:
        raise HTTPException(409, "任务状态已变化，请刷新后重试")
    repository = LoopRepository(session)
    if body.state == "IN_PROGRESS":
        repository.apply_transition(
            loop_id, LoopState.ACTION_REQUESTED, reviewer=actor, reason=body.reason
        )
    else:
        repository.apply_transition(
            loop_id, LoopState.PENDING_REVIEW, reviewer=actor, reason=body.reason
        )
    repository.apply_transition(loop_id, LoopState(body.state), reviewer=actor, reason=body.reason)
    AuditRepository(session).append(
        entity_type="open_loop",
        entity_id=loop_id,
        action="task_followup",
        actor=actor,
        reason=body.reason,
        payload={"patient_id": patient_id, "state": body.state},
    )
    queue_event(
        session,
        patient_id,
        row.encounter_id,
        actor,
        body.reason,
        task_id=loop_id,
        task_state=body.state,
        title=f"任务跟进：{row.goal}",
    )
    return task_response(session, row)
