"""Analyse submitted patient documents through the configured provider and read tools.

No task is created here: proposals are persisted for explicit clinician review.
"""

import hashlib
import json
import re
from time import monotonic

from sqlalchemy.orm import Session

from apps.api.app.db_models import ClinicalDocumentRow
from apps.api.app.repositories import AgentRunRepository, AuditRepository
from apps.mcp_server.mcp_server.server import build_registry
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext
from apps.worker.worker.providers import ModelProviderError
from packages.contracts import (
    ActorRef,
    AgentRun,
    AgentStep,
    AgentStepKind,
    ClinicalEvent,
    EventType,
    StopReason,
    ToolCall,
    new_id,
    utcnow,
)


def analyze_document(session: Session, agent: WorkflowAgent, event: ClinicalEvent) -> AgentRun:
    doc = session.get(ClinicalDocumentRow, event.payload.get("document_id"))
    run = AgentRun(
        run_id=new_id("RUN"),
        trigger_event_id=event.event_id,
        plan=["读取当前患者记录", "识别后续意图", "核对原文与患者归属", "等待医生确认"],
        trace_metadata={**agent.provider.metadata.as_dict(), "workflow": "patient_document"},
    )

    def step(kind: AgentStepKind, reason: str, tool: ToolCall | None = None):
        run.steps.append(
            AgentStep(
                step_id=new_id("STEP"),
                kind=kind,
                reason=reason,
                input_ref=event.event_id,
                tool_call=tool,
                started_at=utcnow(),
                finished_at=utcnow(),
            )
        )

    step(AgentStepKind.OBSERVE, "读取已提交记录，限定当前患者、就诊与记录时间。")
    candidates = []
    error = None
    try:
        if (
            doc is None
            or doc.patient_id != event.patient_id
            or doc.encounter_id != event.encounter_id
            or doc.status != "SUBMITTED"
        ):
            raise ModelProviderError("DOCUMENT_SCOPE_INVALID")
        registry = build_registry(session, as_of=event.source_time)
        visible = []
        for name in ("get_progress_notes", "get_labs"):
            started = monotonic()
            rows = agent.policy.call(registry, name, patient_id=event.patient_id)
            rows = [row for row in rows if row.get("encounter_id") == event.encounter_id]
            digest = hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            call = ToolCall(
                tool_name=name,
                arguments={"patient_id": event.patient_id},
                result_ref=f"sha256:{digest}",
                duration_ms=int((monotonic() - started) * 1000),
                started_at=utcnow(),
            )
            run.tool_calls.append(call)
            step(AgentStepKind.ACT, f"调用只读工具 {name}，找到当前就诊 {len(rows)} 条记录。", call)
            visible.extend(ClinicalEvent.model_validate(row) for row in rows)
        # The existing provider contract emits one proposal. Analyse bounded clauses
        # individually so a round can contain several independently reviewable tasks.
        analysis_text = doc.content
        generation = (doc.payload or {}).get("generation", {})
        if generation.get("writing_version") == 2:
            # Only the physician-reviewed plan is eligible for task extraction;
            # model-written assessments and report summaries are not new orders.
            match = re.search(r"【诊疗计划】\s*(.*?)(?=\n【|\Z)", doc.content, re.S)
            analysis_text = match.group(1) if match else ""
            analysis_text = analysis_text.replace("现有资料不足，待医生补充。", "")
        elif generation:
            # Attached reports are context, never new orders. Strip the generated
            # scaffolding before applying the existing bounded task extractor.
            analysis_text = analysis_text.split(
                "【本次就诊已有检查记录（原始结果，待医生核对）】", 1
            )[0]
            analysis_text = "\n".join(
                line
                for line in analysis_text.splitlines()
                if line.strip()
                and not line.startswith(("【", "患者：", "性别：", "年龄：", "查房对话记录时间："))
                and line.strip() != "问诊原文未明确记录，待医生补充。"
            )
        clauses = list(
            dict.fromkeys(
                part.strip()
                for part in re.split(
                    r"[\n。；;]+|[，,](?=\s*(?:另外|并且|同时|还需|补充|核对|整理|完善))",
                    analysis_text,
                )
                if len(part.strip()) >= 5
            )
        )
        if len(clauses) > agent.policy.max_steps:
            raise ModelProviderError("DOCUMENT_TOO_MANY_CLAUSES")
        started = monotonic()
        for clause in clauses:
            if monotonic() - started > agent.policy.timeout_seconds:
                raise ModelProviderError("DOCUMENT_ANALYSIS_TIMEOUT")
            analysis_event = event.model_copy(
                update={
                    "event_type": EventType.NOTE_CREATED,
                    "payload": {**event.payload, "text": clause, "workspace_analysis": True},
                }
            )
            proposal = agent.provider.analyze(
                AgentContext(event=analysis_event, recent_events=visible)
            )
            valid_refs = {ref for item in visible for ref in (item.event_id, item.payload_ref)} | {
                event.event_id,
                event.payload_ref,
            }
            if proposal.patient_id != event.patient_id or set(proposal.evidence_refs) - valid_refs:
                raise ModelProviderError("MODEL_INVALID_EVIDENCE_REFERENCE")
            if proposal.intent_type is None:
                continue
            if proposal.intent_type.value == "FOLLOW_RESULT" and (
                not proposal.expected_evidence or not proposal.waiting_for
            ):
                raise ModelProviderError("MODEL_INVALID_WAITING_TASK")
            candidates.append(
                {
                    "candidate_id": new_id("CAND"),
                    "status": "PENDING",
                    "source_text": clause,
                    "proposal": proposal.model_dump(mode="json"),
                    "loop_id": None,
                    "review_reason": "",
                }
            )
        step(
            AgentStepKind.REASON,
            f"依据原文识别 {len(candidates)} 个候选任务；模型来源见运行元数据。",
        )
        step(
            AgentStepKind.PLAN, "结果随访任务等待检验事件，其他任务由医生跟进；全部先提交医生确认。"
        )
        step(AgentStepKind.VERIFY, "候选均绑定当前患者、就诊及原文；未直接创建任务或关闭临床事项。")
    except (ModelProviderError, ValueError, PermissionError, KeyError, TimeoutError) as exc:
        error = str(exc) if isinstance(exc, ModelProviderError) else "DOCUMENT_ANALYSIS_FAILED"
        candidates = []
        step(AgentStepKind.VERIFY, f"分析保守退出：{error}。没有创建任务。")
    run.trace_metadata = {
        **agent.provider.metadata.as_dict(),
        "workflow": "patient_document",
        "candidate_count": len(candidates),
    }
    run.stop_reason = (
        StopReason.MODEL_ERROR
        if error
        else StopReason.REQUIRES_CLINICIAN_REVIEW
        if candidates
        else StopReason.SUFFICIENT_EVIDENCE
    )
    run.finished_at = utcnow()
    if (
        doc is not None
        and doc.patient_id == event.patient_id
        and doc.encounter_id == event.encounter_id
    ):
        doc.payload = {
            **(doc.payload or {}),
            "agent_analysis": {
                "status": "FAILED" if error else "READY",
                "event_id": event.event_id,
                "run_id": run.run_id,
                "provider": agent.provider.metadata.provider,
                "model": agent.provider.metadata.model,
                "error": error,
                "candidates": candidates,
            },
        }
    AgentRunRepository(session).create(run)
    AuditRepository(session).append(
        entity_type="agent_run",
        entity_id=run.run_id,
        action="analyze_document",
        actor=ActorRef(actor_id="WORKER", role="SYSTEM"),
        source_run_id=run.run_id,
        payload={
            "patient_id": event.patient_id,
            "document_id": event.payload.get("document_id"),
            "error": error,
        },
    )
    return run
