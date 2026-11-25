"""Scoped evidence tools, persisted assistant requests and conditional task execution."""

import hashlib
import json
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.api.app.db_models import (
    CareAssistanceRow,
    ClinicalDocumentRow,
    ClinicalEventRow,
    OpenLoopRow,
    Patient,
)
from apps.api.app.db_time import as_utc
from apps.api.app.repositories import AuditRepository
from apps.api.app.services.patient_workspace_service import (
    create_task,
    get_document,
    require_encounter,
    update_task,
)
from packages.contracts import ActorRef, new_id, utcnow
from packages.contracts.care_assistance import CareDecision, CareOutput, CareRequest
from packages.contracts.workspace import TaskCreate, TaskUpdate

TOOLS = ("read_documents", "read_labs", "read_tasks")


def evidence_tools(session: Session, patient: str, encounter: str) -> dict:
    """Only current-encounter sources; bounded reads expose truncation explicitly."""
    enc = require_encounter(session, patient, encounter)
    person = session.get(Patient, patient)
    documents = session.scalars(
        select(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.patient_id == patient,
            ClinicalDocumentRow.encounter_id == encounter,
        )
        .order_by(ClinicalDocumentRow.created_at.desc())
        .limit(51)
    ).all()
    labs = session.scalars(
        select(ClinicalEventRow)
        .where(
            ClinicalEventRow.patient_id == patient,
            ClinicalEventRow.encounter_id == encounter,
            ClinicalEventRow.event_type == "LAB_RESULT_CREATED",
        )
        .order_by(ClinicalEventRow.event_time.desc())
        .limit(51)
    ).all()
    tasks = session.scalars(
        select(OpenLoopRow)
        .where(
            OpenLoopRow.patient_id == patient,
            OpenLoopRow.encounter_id == encounter,
        )
        .order_by(OpenLoopRow.created_at.desc())
        .limit(101)
    ).all()
    rounds = [d for d in documents if d.kind == "ROUND" and d.status == "SUBMITTED"]
    baseline = max((as_utc(d.submitted_at) for d in rounds if d.submitted_at), default=None)
    profile = {
        "id": "profile",
        "kind": "profile",
        "label": "患者基本资料",
        "text": json.dumps({"name": person.display_name, **person.payload}, ensure_ascii=False),
        "admitted_at": as_utc(enc.admitted_at).isoformat() if enc.admitted_at else None,
        "last_round_at": baseline.isoformat() if baseline else None,
    }
    return {
        "profile": [profile],
        "read_documents": [
            dict(
                id=d.document_id,
                kind=d.kind,
                label=d.title,
                text=d.content,
                status=d.status,
                revision=d.revision,
                source_interview_id=(d.payload or {}).get("generation", {}).get("interview_id"),
                time=as_utc(d.submitted_at or d.created_at).isoformat(),
                since_last_round=baseline is None
                or as_utc(d.submitted_at or d.created_at) > baseline,
            )
            for d in documents[:50]
        ],
        "read_labs": [
            dict(
                id=e.event_id,
                kind="LAB",
                label=str(e.payload.get("panel", "检查结果")),
                text=json.dumps(e.payload, ensure_ascii=False),
                time=as_utc(e.event_time).isoformat(),
                since_last_round=baseline is None or as_utc(e.event_time) > baseline,
            )
            for e in labs[:50]
        ],
        "read_tasks": [
            dict(
                id=t.loop_id,
                kind="TASK",
                label=t.goal,
                text=t.goal,
                state=t.state,
                due_at=as_utc(t.next_check_at).isoformat() if t.next_check_at else None,
            )
            for t in tasks[:100]
        ],
        "limits": {
            "documents_truncated": len(documents) > 50,
            "labs_truncated": len(labs) > 50,
            "tasks_truncated": len(tasks) > 100,
        },
    }


def fingerprint(bundle: dict) -> str:
    return hashlib.sha256(
        json.dumps(bundle, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def owned(session: Session, patient: str, run_id: str) -> CareAssistanceRow:
    row = session.get(CareAssistanceRow, run_id)
    if row is None or row.patient_id != patient:
        raise HTTPException(404, "当前患者没有这次 Agent 运行")
    require_encounter(session, patient, row.encounter_id)
    return row


def response(session: Session, row: CareAssistanceRow, digest: str | None = None) -> dict:
    if digest is None:
        digest = fingerprint(evidence_tools(session, row.patient_id, row.encounter_id))
    return dict(
        run_id=row.run_id,
        mode=row.mode,
        document_id=row.document_id,
        status=row.status,
        revision=row.revision,
        created_at=as_utc(row.created_at),
        stale=bool(row.payload.get("fingerprint") and row.payload["fingerprint"] != digest),
        **{k: v for k, v in row.payload.items() if k not in {"fingerprint", "lease"}},
    )


def request(session: Session, patient: str, body: CareRequest, actor: ActorRef):
    bundle = evidence_tools(session, patient, body.encounter_id)
    if body.mode != "PREPARE":
        if not body.document_id:
            raise HTTPException(422, "请先选择并保存病历")
        doc = get_document(session, patient, body.document_id)
        if doc.encounter_id != body.encounter_id or doc.kind == "INTERVIEW":
            raise HTTPException(409, "请选择本次就诊的临床文书")
        if body.mode == "PLAN" and doc.status != "SUBMITTED":
            raise HTTPException(409, "条件计划只能依据已签署的病历")
    digest = fingerprint(bundle)
    previous = session.scalars(
        select(CareAssistanceRow)
        .where(
            CareAssistanceRow.patient_id == patient,
            CareAssistanceRow.encounter_id == body.encounter_id,
            CareAssistanceRow.mode == body.mode,
            CareAssistanceRow.document_id == body.document_id,
        )
        .order_by(CareAssistanceRow.created_at.desc())
    ).first()
    if previous and previous.status in {"QUEUED", "RUNNING"}:
        return response(session, previous, digest)
    row = CareAssistanceRow(
        run_id=new_id("CARE"),
        patient_id=patient,
        encounter_id=body.encounter_id,
        document_id=body.document_id,
        mode=body.mode,
        status="QUEUED",
        revision=1,
        payload={
            "clarification": body.clarification,
            "actor_id": actor.actor_id,
            "fingerprint": digest,
            "trace": [],
            "history": [],
        },
    )
    session.add(row)
    session.flush()
    AuditRepository(session).append(
        entity_type="care_assistance",
        entity_id=row.run_id,
        action="request",
        actor=actor,
        reason=body.mode,
    )
    return response(session, row, digest)


def task_gate(session: Session, row: CareAssistanceRow, task: dict, bindings: dict) -> dict:
    loop = session.get(OpenLoopRow, bindings.get(task["key"]))
    if loop and loop.state in {"RESOLVED", "CANCELLED"}:
        return {"state": loop.state, "message": "医生已处理", "result_ids": []}
    dependencies = [session.get(OpenLoopRow, bindings.get(key)) for key in task["depends_on"]]
    if any(d is None or d.state != "RESOLVED" for d in dependencies):
        return {"state": "WAITING", "message": "等待前置任务完成；取消不视为完成", "result_ids": []}
    if task["condition"] == "CLARIFY":
        return {"state": "CLARIFY", "message": task["question"], "result_ids": []}
    ids = []
    if task["condition"] == "RESULT":
        # Match only results created after the source document, within this encounter.
        doc = get_document(session, row.patient_id, row.document_id)
        results = session.scalars(
            select(ClinicalEventRow)
            .where(
                ClinicalEventRow.patient_id == row.patient_id,
                ClinicalEventRow.encounter_id == row.encounter_id,
                ClinicalEventRow.event_type == "LAB_RESULT_CREATED",
                ClinicalEventRow.event_time >= doc.submitted_at,
            )
            .order_by(ClinicalEventRow.event_time.desc())
        ).all()
        ids = [e.event_id for e in results if e.payload.get("panel") == task["panel"]]
        if not ids:
            return {
                "state": "WAITING",
                "message": "等待本次计划之后的匹配检查结果",
                "result_ids": [],
            }
        if len(ids) > 1:
            return {
                "state": "CLARIFY",
                "message": "找到多份结果，请核实对应检查后调整条件",
                "result_ids": ids,
            }
    return {"state": "READY", "message": "条件已满足，等待医生处理", "result_ids": ids}


def sync_plans(session: Session):
    for row in session.scalars(
        select(CareAssistanceRow).where(CareAssistanceRow.status == "ACTIVE")
    ):
        data = deepcopy(row.payload)
        states = {}
        for task in data["result"]["tasks"]:
            state = task_gate(session, row, task, data["bindings"])
            loop = session.get(OpenLoopRow, data["bindings"].get(task["key"]))
            state["overdue"] = bool(
                loop
                and loop.next_check_at
                and as_utc(loop.next_check_at) < utcnow()
                and state["state"] not in {"RESOLVED", "CANCELLED"}
            )
            states[task["key"]] = state
        if states != data.get("task_states"):
            data["task_states"] = states
            data.setdefault("history", []).append(
                {
                    "time": utcnow().isoformat(),
                    "actor": "SYSTEM",
                    "reason": "根据依赖、检查结果和截止时间更新计划",
                    "states": states,
                }
            )
            # A background wake-up must not overwrite a concurrent clinician decision.
            session.execute(
                update(CareAssistanceRow)
                .where(
                    CareAssistanceRow.run_id == row.run_id,
                    CareAssistanceRow.revision == row.revision,
                )
                .values(payload=data, revision=row.revision + 1),
                execution_options={"synchronize_session": False},
            )
            session.expire(row)


def guard_task(session: Session, loop: OpenLoopRow):
    run_id = loop.payload.get("care_run_id")
    if not run_id:
        return
    row = owned(session, loop.patient_id, run_id)
    tasks = row.payload["result"]["tasks"]
    task = next(t for t in tasks if row.payload["bindings"].get(t["key"]) == loop.loop_id)
    gate = task_gate(session, row, task, row.payload["bindings"])
    if gate["state"] != "READY":
        raise HTTPException(409, gate["message"])


def decide(session: Session, patient: str, run_id: str, body: CareDecision, actor: ActorRef):
    row = owned(session, patient, run_id)
    if row.revision != body.revision or row.status not in {"READY", "ACTIVE"}:
        raise HTTPException(409, "运行状态或版本已更新，请刷新")
    locked = session.execute(
        update(CareAssistanceRow)
        .where(
            CareAssistanceRow.run_id == run_id,
            CareAssistanceRow.revision == body.revision,
        )
        .values(revision=body.revision + 1)
    )
    if locked.rowcount != 1:
        raise HTTPException(409, "其他窗口已更新，请刷新")
    data = deepcopy(row.payload)
    if body.action in {"ACCEPT", "UPDATE"}:
        if row.mode != "PLAN":
            raise HTTPException(409, "只有条件计划能创建或调整任务")
        if body.action == "ACCEPT" and row.status != "READY":
            raise HTTPException(409, "计划已经确认")
        if body.action == "UPDATE" and row.status != "ACTIVE":
            raise HTTPException(409, "计划尚未生效")
        if body.action == "ACCEPT" and response(session, row)["stale"]:
            raise HTTPException(409, "资料已变化，请重新分析后确认计划")
        output = CareOutput.model_validate(
            {
                **data["result"],
                **(
                    {"tasks": [t.model_dump(mode="json") for t in body.tasks]}
                    if body.tasks is not None
                    else {}
                ),
            }
        )
        if not output.tasks:
            raise HTTPException(409, "没有可确认的任务")
        original = {t["key"]: t for t in data["result"]["tasks"]}
        if set(original) != {t.key for t in output.tasks}:
            raise HTTPException(409, "调整时需保留任务标识，新增任务请重新分析")
        for task in output.tasks:
            if (
                task.source_ids != original[task.key]["source_ids"]
                or task.source_quote != original[task.key]["source_quote"]
            ):
                raise HTTPException(409, "不能修改任务的原始证据")
            if task.condition == "CLARIFY":
                raise HTTPException(409, "请先补充问题并重新分析，或明确调整任务条件")
        bindings = data.get("bindings", {})
        for task in output.tasks:
            if row.status == "ACTIVE":
                loop = session.get(OpenLoopRow, bindings[task.key])
                if (
                    loop.state in {"RESOLVED", "CANCELLED"}
                    and task.model_dump(mode="json") != original[task.key]
                ):
                    raise HTTPException(409, "已结束的任务不能修改")
                loop.goal, loop.next_check_at = task.goal, task.due_at
            else:
                # Linking is explicit; do not silently merge two semantically different tasks.
                if task.existing_loop_id:
                    raise HTTPException(
                        409, "发现已有任务，请在医生待办处理；重新分析时说明是否为独立事项"
                    )
                active = session.scalars(
                    select(OpenLoopRow).where(
                        OpenLoopRow.patient_id == patient,
                        OpenLoopRow.encounter_id == row.encounter_id,
                        OpenLoopRow.state.notin_(["RESOLVED", "CANCELLED"]),
                    )
                ).all()
                if any(
                    t.goal.strip() == task.goal.strip()
                    or (
                        t.payload.get("source_document_id") == row.document_id
                        and t.payload.get("care_source_quote") == task.source_quote
                    )
                    for t in active
                ):
                    raise HTTPException(409, "已有同名活动任务，请先核对，避免重复创建")
                created = create_task(
                    session,
                    patient,
                    TaskCreate(
                        encounter_id=row.encounter_id,
                        goal=task.goal,
                        owner=actor.actor_id,
                        due_at=task.due_at,
                        source_document_id=row.document_id,
                    ),
                    actor,
                )
                bindings[task.key] = created.loop_id
                loop = session.get(OpenLoopRow, created.loop_id)
                loop.payload = {
                    **loop.payload,
                    "care_run_id": run_id,
                    "care_source_quote": task.source_quote,
                }
        data["bindings"] = bindings
        data["result"] = output.model_dump(mode="json")
        row.status = "ACTIVE"
    elif body.action in {"RESOLVE", "DISMISS"}:
        if row.mode == "PLAN":
            if row.status != "ACTIVE" or body.item_key not in data.get("bindings", {}):
                raise HTTPException(409, "请先确认计划并选择任务")
            loop = session.get(OpenLoopRow, data["bindings"][body.item_key])
            update_task(
                session,
                patient,
                loop.loop_id,
                TaskUpdate(
                    expected_state=loop.state,
                    state="RESOLVED" if body.action == "RESOLVE" else "CANCELLED",
                    reason=body.reason,
                ),
                actor,
            )
        else:
            if response(session, row)["stale"]:
                raise HTTPException(409, "资料已变化，请重新核查后记录意见")
            if not body.item_key.isdigit() or int(body.item_key) >= len(data["result"]["findings"]):
                raise HTTPException(404, "核查项目不存在")
            data.setdefault("reviews", {})[body.item_key] = {
                "action": body.action,
                "reason": body.reason,
                "actor": actor.actor_id,
            }
    data.setdefault("history", []).append(
        {
            "time": utcnow().isoformat(),
            "actor": actor.actor_id,
            "action": body.action,
            "reason": body.reason,
        }
    )
    row.payload = data
    AuditRepository(session).append(
        entity_type="care_assistance",
        entity_id=run_id,
        action=body.action,
        actor=actor,
        reason=body.reason,
    )
    session.flush()
    sync_plans(session)
    return response(session, row)
