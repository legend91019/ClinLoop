"""Explicit review and patient-specific simulation endpoints around the Worker."""

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.db_models import (
    ClinicalDocumentRow,
    ClinicalEventRow,
    EvidenceNodeRow,
    OpenLoopRow,
)
from apps.api.app.repositories import (
    AuditRepository,
    ClinicalEventRepository,
    ClinicalIntentRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
)
from apps.api.app.services.patient_workspace_service import (
    get_document,
    queue_event,
    require_encounter,
)
from apps.api.app.settings import get_settings
from apps.worker.worker.model_contracts import AgentProposal
from packages.contracts import (
    ActorRef,
    ClinicalIntent,
    EventType,
    IntentType,
    LoopState,
    OpenLoop,
    ReviewAction,
    new_id,
    utcnow,
)
from packages.contracts.workspace_agent import (
    PANELS,
    CandidateReview,
    LabInput,
    ResultAcknowledgement,
)


def snapshot(session: Session, patient_id: str, encounter_id: str) -> dict:
    require_encounter(session, patient_id, encounter_id)
    docs = session.scalars(
        select(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.patient_id == patient_id,
            ClinicalDocumentRow.encounter_id == encounter_id,
            ClinicalDocumentRow.status == "SUBMITTED",
        )
        .order_by(ClinicalDocumentRow.created_at.desc())
    ).all()
    tasks = []
    for row in session.scalars(
        select(OpenLoopRow)
        .where(OpenLoopRow.patient_id == patient_id, OpenLoopRow.encounter_id == encounter_id)
        .order_by(OpenLoopRow.created_at.desc())
    ):
        if row.payload.get("managed_by") != "workspace_agent":
            continue
        evidence = session.scalars(
            select(EvidenceNodeRow)
            .where(EvidenceNodeRow.loop_id == row.loop_id, EvidenceNodeRow.source_type == "LABS")
            .order_by(EvidenceNodeRow.observed_at.desc())
        ).first()
        event_id = evidence.provenance.get("event_id") if evidence else None
        result = ClinicalEventRepository(session).get(event_id) if event_id else None
        tasks.append(
            {
                "loop_id": row.loop_id,
                "goal": row.goal,
                "state": row.state,
                "priority": row.priority,
                "source_document_id": row.payload.get("source_document_id"),
                "result": result.model_dump(mode="json") if result else None,
                "evidence_id": evidence.evidence_id if evidence else None,
            }
        )
    return {
        "provider": get_settings().agent_provider,
        "documents": [
            {
                "document_id": doc.document_id,
                "title": doc.title,
                "analysis": (doc.payload or {}).get("agent_analysis"),
            }
            for doc in docs
        ],
        "tasks": tasks,
    }


def request_analysis(session: Session, patient_id: str, document_id: str, actor: ActorRef) -> dict:
    doc = get_document(session, patient_id, document_id)
    require_encounter(session, patient_id, doc.encounter_id)
    if doc.status != "SUBMITTED":
        raise HTTPException(409, "请先提交记录，再交给 Agent 分析")
    current = (doc.payload or {}).get("agent_analysis", {})
    if current.get("status") in {"QUEUED", "READY"}:
        return current
    # Lock via revision before queuing so repeated clicks cannot duplicate work.
    result = session.execute(
        update(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.document_id == document_id,
            ClinicalDocumentRow.revision == doc.revision,
        )
        .values(revision=doc.revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "记录正在更新，请刷新后重试")
    event = queue_event(
        session,
        patient_id,
        doc.encounter_id,
        actor,
        doc.content,
        document_id=doc.document_id,
        document_kind=doc.kind,
        title=doc.title,
    )
    analysis = {"status": "QUEUED", "event_id": event.event_id, "run_id": None, "candidates": []}
    doc.payload = {**(doc.payload or {}), "agent_analysis": analysis}
    return analysis


def review_candidate(
    session: Session,
    patient_id: str,
    document_id: str,
    candidate_id: str,
    body: CandidateReview,
    actor: ActorRef,
) -> dict:
    doc = get_document(session, patient_id, document_id)
    require_encounter(session, patient_id, doc.encounter_id)
    analysis = deepcopy((doc.payload or {}).get("agent_analysis", {}))
    candidate = next(
        (c for c in analysis.get("candidates", []) if c["candidate_id"] == candidate_id), None
    )
    if analysis.get("status") != "READY" or candidate is None:
        raise HTTPException(404, "候选任务不存在或分析尚未完成")
    if candidate["status"] != "PENDING":
        if candidate["status"] == ("ACCEPTED" if body.action == "ACCEPT" else "REJECTED"):
            return candidate
        raise HTTPException(409, "该建议已有审核决定")
    result = session.execute(
        update(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.document_id == document_id,
            ClinicalDocumentRow.revision == doc.revision,
        )
        .values(revision=doc.revision + 1)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "其他审核已更新记录，请刷新后重试")
    if body.action == "ACCEPT":
        proposal = AgentProposal.model_validate(candidate["proposal"])
        if proposal.patient_id != patient_id:
            raise HTTPException(409, "候选患者归属无效")
        if proposal.intent_type == IntentType.FOLLOW_RESULT:
            for active in LoopRepository(session).list_for_patient(patient_id):
                intent = ClinicalIntentRepository(session).get(active.intent_id)
                if (
                    active.encounter_id == doc.encounter_id
                    and active.state == LoopState.WAITING_EVENT
                    and intent
                    and set(intent.expected_evidence) & set(proposal.expected_evidence)
                ):
                    raise HTTPException(
                        409, "当前就诊已有同项目的等待任务，请先处理已有任务，避免结果匹配歧义"
                    )
        intent = ClinicalIntent(
            intent_id=new_id("INT"),
            patient_id=patient_id,
            encounter_id=doc.encounter_id,
            intent_type=proposal.intent_type or IntentType.UPDATE_PLAN,
            text=candidate["source_text"],
            source_event_id=doc.event_id,
            expected_evidence=proposal.expected_evidence,
        )
        ClinicalIntentRepository(session).add(intent)
        loop = OpenLoop(
            loop_id=new_id("LOOP"),
            patient_id=patient_id,
            encounter_id=doc.encounter_id,
            intent_id=intent.intent_id,
            goal=proposal.goal,
            owner=actor.actor_id,
            priority=proposal.priority,
            last_plan=proposal.rationale,
            confidence=proposal.confidence,
            waiting_for=proposal.waiting_for
            if proposal.intent_type == IntentType.FOLLOW_RESULT
            else [],
        )
        repository = LoopRepository(session)
        repository.add(loop)
        repository.apply_transition(
            loop.loop_id, LoopState.PLANNED, reviewer=actor, reason="医生确认 Agent 候选任务"
        )
        if proposal.intent_type == IntentType.FOLLOW_RESULT:
            repository.apply_transition(
                loop.loop_id, LoopState.WAITING_EVENT, reviewer=actor, reason="等待匹配的检验结果"
            )
        row = session.get(OpenLoopRow, loop.loop_id)
        row.payload = {
            **row.payload,
            "managed_by": "workspace_agent",
            "source_document_id": doc.document_id,
            "candidate_id": candidate_id,
            "analysis_run_id": analysis.get("run_id"),
        }
        candidate["loop_id"] = loop.loop_id
    candidate["status"] = "ACCEPTED" if body.action == "ACCEPT" else "REJECTED"
    candidate["review_reason"] = body.reason
    doc.payload = {**doc.payload, "agent_analysis": analysis}
    AuditRepository(session).append(
        entity_type="clinical_document",
        entity_id=document_id,
        action=f"agent_candidate_{body.action.lower()}",
        actor=actor,
        reason=body.reason,
        source_run_id=analysis.get("run_id"),
        payload={"patient_id": patient_id, "candidate_id": candidate_id},
    )
    return candidate


def add_lab(session: Session, patient_id: str, body: LabInput, actor: ActorRef) -> str:
    require_encounter(session, patient_id, body.encounter_id)
    # Keep retries idempotent and prohibit reusing a key for a different result.
    existing = session.get(ClinicalEventRow, f"LAB-{body.request_id}")
    if existing:
        if (
            existing.patient_id != patient_id
            or existing.encounter_id != body.encounter_id
            or existing.payload.get("panel") != body.panel
            or existing.payload.get("result") != body.result
        ):
            raise HTTPException(409, "请求标识已用于其他结果")
        return existing.event_id
    from apps.api.app.db_models import EventPublicationRow
    from packages.contracts import ClinicalEvent

    now = utcnow()
    event = ClinicalEvent(
        event_id=f"LAB-{body.request_id}",
        patient_id=patient_id,
        encounter_id=body.encounter_id,
        event_type=EventType.LAB_RESULT_CREATED,
        event_time=now,
        source_time=now,
        payload_ref=new_id("LAB-SOURCE"),
        actor=actor,
        payload={
            "panel": body.panel,
            "result": body.result,
            "synthetic": True,
            "title": f"模拟{PANELS[body.panel]}结果",
        },
    )
    ClinicalEventRepository(session).add(event)
    session.add(EventPublicationRow(event_id=event.event_id, payload={}))
    return event.event_id


def acknowledge_result(
    session: Session, patient_id: str, loop_id: str, body: ResultAcknowledgement, actor: ActorRef
) -> str:
    row = session.get(OpenLoopRow, loop_id)
    if (
        row is None
        or row.patient_id != patient_id
        or row.payload.get("managed_by") != "workspace_agent"
    ):
        raise HTTPException(404, "当前患者没有这项 Agent 任务")
    require_encounter(session, patient_id, row.encounter_id)
    if row.state != "RESULT_AVAILABLE":
        raise HTTPException(409, "结果尚未到达，或已处理")
    pending = (row.payload or {}).get("ack_event_id")
    if pending:
        return pending
    evidence = [
        node
        for node in EvidenceRepository(session).list_for_patient(patient_id)
        if node.provenance.get("loop_id") == loop_id
        and node.source_type == "LABS"
        and node.encounter_id == row.encounter_id
    ]
    if len(evidence) != 1:
        raise HTTPException(409, "缺少唯一、可追溯的检验来源")
    result_id = evidence[0].provenance.get("event_id")
    referenced = ClinicalEventRepository(session).get(result_id) if result_id else None
    if (
        not referenced
        or referenced.patient_id != patient_id
        or referenced.encounter_id != row.encounter_id
    ):
        raise HTTPException(409, "检验来源不属于当前就诊")
    locked = session.execute(
        update(OpenLoopRow)
        .where(
            OpenLoopRow.loop_id == loop_id,
            OpenLoopRow.state == "RESULT_AVAILABLE",
            OpenLoopRow.payload["ack_event_id"].as_string().is_(None),
        )
        .values(updated_at=utcnow())
    )
    if locked.rowcount != 1:
        raise HTTPException(409, "处理记录正在更新，请刷新后重试")
    from apps.api.app.services.review_service import review_finding

    for finding in FindingRepository(session).list_for_patient(patient_id):
        if finding.loop_id == loop_id and finding.review_status == "PENDING_REVIEW":
            review_finding(
                session,
                finding.finding_id,
                ReviewAction.ACCEPT,
                actor,
                f"医生查看结果并确认本任务提示：{body.reason}",
            )
    event = queue_event(
        session,
        patient_id,
        row.encounter_id,
        actor,
        body.reason,
        acknowledges_event_id=result_id,
        workspace_close_after_ack=True,
        **({"creates_dependency": body.next_panel} if body.next_panel else {}),
    )
    row.payload = {**row.payload, "ack_event_id": event.event_id}
    return event.event_id
