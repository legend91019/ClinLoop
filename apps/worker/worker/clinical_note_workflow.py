"""Build a scoped source bundle and draft an independent clinical document."""

import hashlib
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db_models import ClinicalDocumentRow, Encounter, Patient
from apps.api.app.db_time import as_utc
from apps.api.app.repositories import AgentRunRepository, AuditRepository
from apps.api.app.settings import get_settings
from apps.mcp_server.mcp_server.server import build_registry
from apps.worker.worker.clinical_writing import (
    SECTIONS,
    DraftingError,
    demo_clinical_note,
    render_clinical_note,
    transcript_speaker,
    write_clinical_note,
)
from packages.contracts import (
    ActorRef,
    AgentRun,
    AgentStep,
    AgentStepKind,
    ClinicalEvent,
    StopReason,
    ToolCall,
    new_id,
    utcnow,
)

KINDS = {"ADMISSION": "入院病历", "ROUND": "查房记录", "PROGRESS": "病程记录"}


def build_context(
    session: Session, source: ClinicalDocumentRow, event: ClinicalEvent, labs: list
) -> dict:
    patient = session.get(Patient, event.patient_id)
    encounter = session.get(Encounter, event.encounter_id)
    profile = {
        "display_name": patient.display_name,
        **{
            key: value
            for key, value in (patient.payload or {}).items()
            if key
            in {
                "sex",
                "age",
                "ethnicity",
                "marital_status",
                "birthplace",
                "occupation",
                "chief_complaint",
                "history",
                "allergies",
            }
        },
    }
    sources = []
    for key, value in profile.items():
        if value not in (None, "", "待核对", "未记录", "未说明", "待补录"):
            sources.append(
                {
                    "source_id": f"P{len(sources) + 1:03}",
                    "kind": "profile",
                    "field": key,
                    "text": str(value),
                    "label": f"患者档案：{key}",
                }
            )
    lines = [line.strip() for line in source.content.splitlines() if line.strip()]
    if len(lines) > 160:
        raise DraftingError("TRANSCRIPT_TOO_MANY_SEGMENTS")
    for i, line in enumerate(lines, 1):
        kind, _ = transcript_speaker(line)
        if re.search(r"[？?]$", line):
            kind = "question"
        sources.append(
            {
                "source_id": f"T{i:03}",
                "kind": kind,
                "text": line,
                "label": f"原始对话第{i}段",
                "ref": source.document_id,
            }
        )
    for i, lab in enumerate(labs, 1):
        payload = lab.get("payload", {})
        text = str(
            payload.get("result") or payload.get("text") or json.dumps(payload, ensure_ascii=False)
        )
        sources.append(
            {
                "source_id": f"L{i:03}",
                "kind": "lab",
                "text": text,
                "label": f"检查项目：{payload.get('panel', '未标注')}；报告时间：{lab['event_time']}",
                "ref": lab["event_id"],
            }
        )
    signed = session.scalars(
        select(ClinicalDocumentRow)
        .where(
            ClinicalDocumentRow.patient_id == event.patient_id,
            ClinicalDocumentRow.encounter_id == event.encounter_id,
            ClinicalDocumentRow.status == "SUBMITTED",
            ClinicalDocumentRow.submitted_at <= event.source_time,
        )
        .order_by(ClinicalDocumentRow.submitted_at.desc())
        .limit(10)
    ).all()
    for i, note in enumerate(signed, 1):
        sources.append(
            {
                "source_id": f"N{i:03}",
                "kind": "signed_note",
                "text": note.content,
                "label": f"既往已提交文书：{note.title}；提交时间：{as_utc(note.submitted_at).isoformat()}",
                "ref": note.document_id,
            }
        )
    kind = source.payload["requested_kind"]
    context = {
        "kind": kind,
        "title": KINDS[kind],
        "patient": profile,
        "patient_id": event.patient_id,
        "encounter_id": event.encounter_id,
        "record_time": as_utc(source.created_at).isoformat(),
        "admitted_at": as_utc(encounter.admitted_at).isoformat() if encounter.admitted_at else None,
        "section_order": SECTIONS[kind],
        "sources": sources,
    }
    if len(json.dumps(context, ensure_ascii=False)) > 80000:
        raise DraftingError("NOTE_CONTEXT_TOO_LARGE")
    return context


def generate_interview_note(session: Session, event: ClinicalEvent, *, writer=None) -> AgentRun:
    settings = get_settings()
    source = session.get(ClinicalDocumentRow, event.payload.get("interview_id"))
    mode = event.payload.get("draft_mode", "DEMO")
    run = AgentRun(
        run_id=new_id("RUN"),
        trigger_event_id=event.event_id,
        plan=[
            "读取对话、档案及本次就诊检查",
            "撰写连贯的临床文书",
            "检查来源引用、数值及待补充信息",
            "交医生审核签署",
        ],
        trace_metadata={
            "workflow": "interview_note_drafting",
            "writing_version": 2,
            "draft_mode": mode,
            "provider": settings.note_draft_provider if mode == "CLINICAL" else "local-template",
            "model": settings.deepseek_model if mode == "CLINICAL" else "clinical-format-demo-v2",
        },
    )

    def step(kind, reason, tool=None):
        run.steps.append(
            AgentStep(
                step_id=new_id("STEP"),
                kind=kind,
                reason=reason,
                input_ref=event.payload_ref,
                tool_call=tool,
                started_at=utcnow(),
                finished_at=utcnow(),
            )
        )

    step(AgentStepKind.OBSERVE, "读取已保存的原始对话；正文独立起草，保留原文供医生对照。")
    status = {"status": "FAILED", "run_id": run.run_id, **run.trace_metadata}
    scoped = (
        source
        and source.kind == "INTERVIEW"
        and source.patient_id == event.patient_id
        and source.encounter_id == event.encounter_id
    )
    try:
        if not scoped:
            raise DraftingError("INTERVIEW_SCOPE_INVALID")
        registry = build_registry(session, as_of=event.source_time)
        for name in ("get_patient_snapshot", "get_labs"):
            args = {
                "patient_id": event.patient_id,
                **({"hours": 720} if name == "get_labs" else {}),
            }
            result = registry.call(name, **args)
            if name == "get_labs":
                labs = [item for item in result if item.get("encounter_id") == event.encounter_id][
                    :20
                ]
            call = ToolCall(
                tool_name=name, arguments=args, result_ref=event.patient_id, started_at=utcnow()
            )
            run.tool_calls.append(call)
            step(AgentStepKind.ACT, f"调用{name}核对本次就诊资料。", call)
        context = build_context(session, source, event, labs)
        call = ToolCall(
            tool_name="read_encounter_documents",
            arguments={"patient_id": event.patient_id, "encounter_id": event.encounter_id},
            result_ref=",".join(
                item["ref"] for item in context["sources"] if item["kind"] == "signed_note"
            ),
            started_at=utcnow(),
        )
        run.tool_calls.append(call)
        step(
            AgentStepKind.ACT,
            "读取保存前最近10份已提交文书；既往记录保留时间和来源，不作本次查体事实。",
            call,
        )
        draft_data = (
            writer(context, settings)
            if writer
            else write_clinical_note(context, settings)
            if mode == "CLINICAL"
            else demo_clinical_note(context)
        )
        step(
            AgentStepKind.REASON,
            "综合来源撰写独立临床叙述，原始对话与检查依据单独保留。"
            if mode == "CLINICAL"
            else "生成本地格式演示文书；未调用模型，不代表自动临床撰写能力。",
        )
        content = render_clinical_note(draft_data, context)
        step(
            AgentStepKind.VERIFY,
            "校验章节、来源标识和数值；语义支持、遗漏、冲突及医学表述仍需医生审核。",
        )
        document_id = (
            "DRAFT-"
            + hashlib.sha256(f"{source.document_id}:{event.event_id}".encode()).hexdigest()[:40]
        )
        draft = session.get(ClinicalDocumentRow, document_id)
        if draft is None:
            draft = ClinicalDocumentRow(
                document_id=document_id,
                patient_id=source.patient_id,
                encounter_id=source.encounter_id,
                kind=source.payload["requested_kind"],
                title=f"{KINDS[source.payload['requested_kind']]}（{'Agent 撰写草稿' if mode == 'CLINICAL' else '本地格式演示'}）",
                content=content,
                author_id="AGENT",
                status="DRAFT",
                revision=1,
                payload={
                    "generation": {
                        "interview_id": source.document_id,
                        "source_text": source.content,
                        "source_sha256": hashlib.sha256(source.content.encode()).hexdigest(),
                        "run_id": run.run_id,
                        "lab_sources": labs,
                        "sources": context["sources"],
                        "clinical_sections": [
                            section.model_dump() for section in draft_data.sections
                        ],
                        "missing_information": draft_data.missing_information,
                        "conflicts": [item.model_dump() for item in draft_data.conflicts],
                        **run.trace_metadata,
                    }
                },
            )
            session.add(draft)
            session.flush()
        status = {**status, "status": "READY", "document_id": document_id, "error": None}
        step(AgentStepKind.PLAN, "等待医生对照原始资料审核、修改并签署；签署后才触发任务提取。")
        run.stop_reason = StopReason.REQUIRES_CLINICIAN_REVIEW
    except (DraftingError, ValueError, KeyError, TypeError) as exc:
        status["error"] = str(exc) if isinstance(exc, DraftingError) else "NOTE_DRAFT_FAILED"
        step(
            AgentStepKind.VERIFY,
            f"起草失败：{status['error']}；原文保留，可重试或选择本地格式演示。",
        )
        run.stop_reason = StopReason.MODEL_ERROR
    if scoped:
        source.payload = {
            **source.payload,
            "drafting": {**source.payload.get("drafting", {}), **status},
        }
    run.finished_at = utcnow()
    AgentRunRepository(session).create(run)
    AuditRepository(session).append(
        entity_type="interview",
        entity_id=event.payload_ref,
        action="draft_record",
        actor=ActorRef(actor_id="WORKER", role="SYSTEM"),
        source_run_id=run.run_id,
        payload={
            "patient_id": event.patient_id,
            "status": status["status"],
            "error": status.get("error"),
        },
    )
    return run
