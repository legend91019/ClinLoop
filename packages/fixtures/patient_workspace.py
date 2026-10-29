"""Small, idempotent, wholly fictional patient cohort for the local workspace."""

from sqlalchemy.orm import Session

from apps.api.app.db_models import Encounter, Patient
from apps.api.app.repositories import PatientRepository
from apps.api.app.services.patient_workspace_service import (
    create_document,
    create_task,
    submit_document,
)
from packages.contracts import ActorRef, utcnow
from packages.contracts.workspace import DocumentCreate, TaskCreate

CASES = [
    (
        "林晓禾（模拟）",
        "女",
        34,
        "呼吸观察区",
        "01",
        "咳嗽伴间断发热 3 天",
        "既往史待补充",
        "自述无已知药物过敏，待核对",
        "核对本次检验结果是否回报",
        "HIGH",
    ),
    (
        "周明远（模拟）",
        "男",
        62,
        "综合内科",
        "02",
        "血压记录波动，来院观察",
        "既往血压随访资料待补录",
        "过敏史未记录",
        "补充既往随访记录与过敏史",
        "NORMAL",
    ),
    (
        "陈雨宁（模拟）",
        "女",
        47,
        "外科观察区",
        "03",
        "术后观察记录随访",
        "手术记录待核对",
        "过敏史待核对",
        "核对术后记录与交班事项",
        "HIGH",
    ),
    (
        "许安（模拟）",
        "男",
        28,
        "综合内科",
        "04",
        "间断腹部不适 1 天",
        "既往史待补充",
        "未记录",
        "补充症状变化的查房记录",
        "NORMAL",
    ),
    (
        "宋知夏（模拟）",
        "女",
        55,
        "综合内科",
        "05",
        "常规复查与资料整理",
        "既往复查报告待整理",
        "未记录",
        "收集并核对既往复查报告",
        "LOW",
    ),
    (
        "顾承（模拟）",
        "男",
        71,
        "康复观察区",
        "06",
        "活动情况随访",
        "既往康复记录待补录",
        "未记录",
        "整理本次活动观察与交班待办",
        "HIGH",
    ),
]

DEMOGRAPHICS = [
    {
        "ethnicity": "汉族",
        "marital_status": "未婚",
        "birthplace": "四川省成都市",
        "occupation": "教师",
    },
    {
        "ethnicity": "汉族",
        "marital_status": "已婚",
        "birthplace": "江苏省南京市",
        "occupation": "退休职工",
    },
    {
        "ethnicity": "回族",
        "marital_status": "已婚",
        "birthplace": "宁夏银川市",
        "occupation": "会计",
    },
    {
        "ethnicity": "汉族",
        "marital_status": "未婚",
        "birthplace": "浙江省杭州市",
        "occupation": "工程师",
    },
    {
        "ethnicity": "土家族",
        "marital_status": "已婚",
        "birthplace": "湖北省恩施市",
        "occupation": "个体经营者",
    },
    {
        "ethnicity": "汉族",
        "marital_status": "丧偶",
        "birthplace": "山东省济南市",
        "occupation": "退休职工",
    },
]


def seed_workspace_patients(session: Session) -> int:
    actor = ActorRef(actor_id="DR-DEMO", role="PHYSICIAN", display_name="模拟医生")
    # Check the complete reserved ID range before making any changes. An existing
    # patient or encounter may belong to another workflow and must not be adopted.
    for index in range(1, len(CASES) + 1):
        patient_id, encounter_id = f"P-200{index}", f"ENC-300{index}"
        existing = session.get(Patient, patient_id)
        encounter = session.get(Encounter, encounter_id)
        if existing is not None and (
            not existing.synthetic
            or existing.display_name != CASES[index - 1][0]
            or encounter is None
            or encounter.patient_id != patient_id
        ):
            raise ValueError(f"模拟患者 ID 冲突：{patient_id}")
        if existing is None and encounter is not None:
            raise ValueError(f"模拟就诊 ID 冲突：{encounter_id}")
    created = 0
    for index, (
        name,
        sex,
        age,
        ward,
        bed,
        complaint,
        history,
        allergies,
        goal,
        priority,
    ) in enumerate(CASES, start=1):
        patient_id, encounter_id = f"P-200{index}", f"ENC-300{index}"
        demographics = DEMOGRAPHICS[index - 1]
        existing = session.get(Patient, patient_id)
        if existing is not None:
            existing.payload = {**demographics, **(existing.payload or {})}
            continue
        PatientRepository(session).ensure(
            patient_id=patient_id, encounter_id=encounter_id, display_name=name, ward=ward
        )
        patient = session.get(Patient, patient_id)
        patient.payload = {
            **demographics,
            "sex": sex,
            "age": age,
            "chief_complaint": complaint,
            "history": history,
            "allergies": allergies,
        }
        encounter = session.get(Encounter, encounter_id)
        encounter.payload = {"bed": bed}
        encounter.admitted_at = utcnow()
        document = create_document(
            session,
            patient_id,
            DocumentCreate(
                encounter_id=encounter_id,
                kind="ADMISSION",
                title="模拟入院记录",
                content=f"【合成数据，仅供功能演示】\n主诉：{complaint}。\n现病史：为演示录入流程建立的虚构病例，待医生补充。\n既往史：{history}。\n过敏史：{allergies}。\n查体与辅助检查：待录入。\n记录计划：完善资料，跟进待办。",
            ),
            actor,
        )
        submitted = submit_document(
            session, patient_id, document.document_id, document.revision, actor
        )
        create_document(
            session,
            patient_id,
            DocumentCreate(
                encounter_id=encounter_id,
                kind="ROUND",
                title="首次查房记录（待完善）",
                content="主观情况：待记录。\n客观观察：待记录。\n本次评估：待医生填写。\n后续安排：核对当前待办。",
            ),
            actor,
        )
        create_task(
            session,
            patient_id,
            TaskCreate(
                encounter_id=encounter_id,
                goal=goal,
                priority=priority,
                owner="DR-DEMO",
                source_document_id=submitted.document_id,
            ),
            actor,
        )
        created += 1
    return created
