"""Create one isolated fictional walkthrough without changing existing records."""

import json
from datetime import timedelta

from apps.api.app.db import build_engine, create_schema, session_scope
from apps.api.app.db_models import ClinicalDocumentRow, Encounter, Patient
from apps.api.app.services.workspace_agent_service import add_lab
from packages.contracts import ActorRef, utcnow
from packages.contracts.workspace_agent import LabInput

PATIENT = "P-ROUND-DEMO"
ENCOUNTER = "ENC-ROUND-DEMO"
TRANSCRIPT = "患者：今天感觉比昨天好一些。\n医生：请再确认一下过敏史。\n患者：我记不清了，需要问家属。\n医生：血培养结果出来后查看，处理完血培养结果后整理交接事项。"
DRAFT = "【病情变化】\n患者诉今日较昨日好转。\n【诊疗评估】\n现有资料不足，待医生补充。\n【诊疗计划】\n血培养结果出来后查看。"
PLAN = "血培养结果出来后查看；处理完血培养结果后整理交接事项。"


def transcript_metadata():
    return {
        "requested_kind": "ROUND",
        "initial_draft_mode": "DEMO",
        "drafting": {
            "status": "READY",
            "draft_mode": "DEMO",
            "document_id": "ROUND-DEMO-DRAFT",
            "provider": "fixture",
        },
    }


def repair_transcript(session):
    """Repair only the original fixture metadata; preserve dialogue and clinician edits."""
    raw = session.get(ClinicalDocumentRow, "ROUND-DEMO-RAW")
    if (
        raw
        and raw.patient_id == PATIENT
        and raw.encounter_id == ENCOUNTER
        and raw.kind == "INTERVIEW"
        and raw.author_id == "DEMO-FIXTURE"
    ):
        payload = dict(raw.payload or {})
        for key, value in transcript_metadata().items():
            payload.setdefault(key, value)
        if payload != raw.payload:
            raw.payload = payload
            raw.revision += 1
        if raw.status == "SUBMITTED":
            raw.status = "TRANSCRIPT"
            raw.submitted_at = None


def seed(session):
    existing = session.get(Patient, PATIENT)
    if existing:
        enc = session.get(Encounter, ENCOUNTER)
        if (
            not existing.synthetic
            or existing.payload.get("scenario") != "round_walkthrough"
            or not enc
            or enc.patient_id != PATIENT
        ):
            raise ValueError("演示标识已被其他记录占用")
        repair_transcript(session)
        return False
    now = utcnow()
    session.add(
        Patient(
            patient_id=PATIENT,
            display_name="查房演示·陈明（虚构）",
            synthetic=True,
            payload={
                "scenario": "round_walkthrough",
                "age": 46,
                "sex": "男",
                "chief_complaint": "模拟检查结果随访",
                "allergies": "待核实",
                "history": "演示资料，不对应真实患者",
            },
        )
    )
    session.flush()
    session.add(
        Encounter(
            encounter_id=ENCOUNTER,
            patient_id=PATIENT,
            ward="模拟病区",
            admitted_at=now - timedelta(days=1),
            payload={"bed": "演示01"},
        )
    )
    session.flush()
    for key, kind, title, content, status, created, payload in [
        (
            "BASE",
            "ROUND",
            "上次查房（预置演示记录）",
            "已安排血常规复查，血培养结果待回报；过敏史待核实。",
            "SUBMITTED",
            now - timedelta(hours=12),
            {},
        ),
        (
            "RAW",
            "INTERVIEW",
            "本次查房原始对话（虚构）",
            TRANSCRIPT,
            "TRANSCRIPT",
            now,
            transcript_metadata(),
        ),
        (
            "DRAFT",
            "ROUND",
            "待审核查房草稿（故意遗漏交接安排）",
            DRAFT,
            "DRAFT",
            now,
            {
                "generation": {
                    "draft_mode": "DEMO",
                    "provider": "fixture",
                    "model": "人工预置核查样例",
                    "interview_id": "ROUND-DEMO-RAW",
                    "source_text": TRANSCRIPT,
                    "writing_version": 2,
                }
            },
        ),
    ]:
        session.add(
            ClinicalDocumentRow(
                document_id=f"ROUND-DEMO-{key}",
                patient_id=PATIENT,
                encounter_id=ENCOUNTER,
                kind=kind,
                title=title,
                content=content,
                status=status,
                revision=1,
                author_id="DEMO-FIXTURE",
                created_at=created,
                submitted_at=created if status == "SUBMITTED" else None,
                payload=payload,
            )
        )
    add_lab(
        session,
        PATIENT,
        LabInput(
            encounter_id=ENCOUNTER,
            request_id="round-demo-count",
            panel="blood_count_result",
            result="虚构血常规报告已回报，供资料变化识别演示。",
        ),
        ActorRef(actor_id="DEMO-FIXTURE", role="PHYSICIAN"),
    )
    return True


def main():
    engine = build_engine()
    try:
        create_schema(engine)
        with session_scope(engine) as session:
            created = seed(session)
        print(
            json.dumps(
                {
                    "created": created,
                    "patient_id": PATIENT,
                    "url": f"http://127.0.0.1:5173/?patient={PATIENT}&view=records",
                }
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
