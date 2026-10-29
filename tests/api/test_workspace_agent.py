"""Patient documents must drive the actual Worker, tools, review and result chain."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db_models import ClinicalDocumentRow, OpenLoopRow
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.providers import MockProvider
from apps.worker.worker.service import process_pending_database_events
from tests.api.test_patient_workspace import HEADERS, patient


def drain(engine, provider=None):
    with Session(engine) as session:
        runs = process_pending_database_events(
            session, WorkflowAgent(provider=provider or MockProvider()), limit=100
        )
        session.commit()
        return runs


def submit(client, p, text="血培养结果出来后提醒我查看；补充患者过敏史。"):
    base = f"/api/v1/patients/{p['patient_id']}/documents"
    doc = client.post(
        base,
        headers=HEADERS,
        json={
            "encounter_id": p["encounter_id"],
            "kind": "ROUND",
            "title": "Agent 查房",
            "content": text,
        },
    ).json()
    response = client.post(
        base + f"/{doc['document_id']}/submit", headers=HEADERS, json={"revision": 1}
    )
    assert response.status_code == 200, response.text
    return doc


def state(client, p):
    response = client.get(
        f"/api/v1/patients/{p['patient_id']}/agent-workspace",
        params={"encounter_id": p["encounter_id"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def review(client, p, doc, candidate, verdict="ACCEPT", reason="医生核对后确认"):
    return client.post(
        f"/api/v1/patients/{p['patient_id']}/documents/{doc['document_id']}/candidates/{candidate['candidate_id']}/review",
        headers=HEADERS,
        json={"action": verdict, "reason": reason},
    )


def lab(client, p, panel="blood_culture_result"):
    response = client.post(
        f"/api/v1/patients/{p['patient_id']}/agent-labs",
        headers=HEADERS,
        json={
            "encounter_id": p["encounter_id"],
            "request_id": uuid4().hex,
            "panel": panel,
            "result": "模拟报告回报，供功能验证",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_round_proposals_require_review_and_are_idempotent(workspace):
    client, engine = workspace
    p = patient(client)
    doc = submit(client, p)
    assert state(client, p)["documents"][0]["analysis"]["status"] == "QUEUED"
    runs = drain(engine)
    assert len(runs[0].tool_calls) == 2
    snapshot = state(client, p)
    candidates = snapshot["documents"][0]["analysis"]["candidates"]
    assert len(candidates) == 2
    assert snapshot["tasks"] == []
    follow = next(c for c in candidates if c["proposal"]["intent_type"] == "FOLLOW_RESULT")
    response = review(client, p, doc, follow)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACCEPTED"
    assert review(client, p, doc, follow).json()["loop_id"] == response.json()["loop_id"]
    assert len(state(client, p)["tasks"]) == 1
    other = next(c for c in candidates if c["candidate_id"] != follow["candidate_id"])
    assert review(client, p, doc, other, "REJECT", "").status_code == 422
    assert review(client, p, doc, other, "REJECT", "本次不需要新增").status_code == 200
    assert review(client, p, doc, other).status_code == 409
    assert drain(engine) == []


def test_result_wakes_agent_requires_clinician_and_creates_dependency(workspace):
    client, engine = workspace
    p = patient(client)
    doc = submit(client, p, "血培养结果出来后提醒我查看。")
    drain(engine)
    candidate = state(client, p)["documents"][0]["analysis"]["candidates"][0]
    loop = review(client, p, doc, candidate).json()["loop_id"]
    assert state(client, p)["tasks"][0]["state"] == "WAITING_EVENT"
    lab(client, p, "renal_function_result")
    drain(engine)
    assert state(client, p)["tasks"][0]["state"] == "WAITING_EVENT"
    lab(client, p)
    runs = drain(engine)
    assert any(call.tool_name == "get_labs" for run in runs for call in run.tool_calls)
    task = state(client, p)["tasks"][0]
    assert task["state"] == "RESULT_AVAILABLE" and task["evidence_id"] and task["result"]
    endpoint = f"/api/v1/patients/{p['patient_id']}/agent-tasks/{loop}/acknowledge"
    assert client.post(endpoint, json={"reason": "已查看"}).status_code == 403
    ack = client.post(
        endpoint,
        headers=HEADERS,
        json={
            "reason": "已查看原始血培养记录，继续等待药敏",
            "next_panel": "susceptibility_result",
        },
    )
    assert ack.status_code == 202, ack.text
    drain(engine)
    tasks = state(client, p)["tasks"]
    assert next(t for t in tasks if t["loop_id"] == loop)["state"] == "RESOLVED"
    child = next(t for t in tasks if t["loop_id"] != loop)
    assert child["state"] == "WAITING_EVENT"
    lab(client, p, "susceptibility_result")
    drain(engine)
    assert (
        next(t for t in state(client, p)["tasks"] if t["loop_id"] == child["loop_id"])["state"]
        == "RESULT_AVAILABLE"
    )


def test_scope_negation_and_generic_tasks(workspace):
    client, engine = workspace
    p, other = patient(client, "模拟甲"), patient(client, "模拟乙")
    doc = submit(client, p, "无需跟进血培养结果；已补充过敏史；补充患者既往史。")
    drain(engine)
    candidates = state(client, p)["documents"][0]["analysis"]["candidates"]
    assert len(candidates) == 1 and candidates[0]["proposal"]["intent_type"] == "UPDATE_PLAN"
    assert review(client, other, doc, candidates[0]).status_code == 404
    loop = review(client, p, doc, candidates[0]).json()["loop_id"]
    endpoint = f"/api/v1/patients/{p['patient_id']}/tasks/{loop}"
    assert (
        client.patch(
            endpoint,
            headers=HEADERS,
            json={"state": "RESOLVED", "expected_state": "PLANNED", "reason": "已补充来源信息"},
        ).status_code
        == 200
    )
    assert state(client, other)["tasks"] == []


def test_model_error_is_visible_and_retry_does_not_create_tasks(workspace):
    client, engine = workspace
    from apps.worker.worker.providers import ModelProviderError

    class BrokenProvider(MockProvider):
        def analyze(self, context):
            raise ModelProviderError("MODEL_UNAVAILABLE")

    p = patient(client)
    doc = submit(client, p)
    drain(engine, BrokenProvider())
    assert state(client, p)["documents"][0]["analysis"]["status"] == "FAILED"
    assert state(client, p)["tasks"] == []
    endpoint = f"/api/v1/patients/{p['patient_id']}/documents/{doc['document_id']}/analyze"
    first = client.post(endpoint, headers=HEADERS).json()
    second = client.post(endpoint, headers=HEADERS).json()
    assert first["event_id"] == second["event_id"]
    drain(engine)
    assert state(client, p)["documents"][0]["analysis"]["status"] == "READY"


def test_result_from_another_patient_cannot_wake_a_task(workspace):
    client, engine = workspace
    p, other = patient(client, "模拟甲"), patient(client, "模拟乙")
    doc = submit(client, p, "血培养结果出来后提醒我查看。")
    drain(engine)
    review(client, p, doc, state(client, p)["documents"][0]["analysis"]["candidates"][0])
    lab(client, other)
    drain(engine)
    assert state(client, p)["tasks"][0]["state"] == "WAITING_EVENT"
    with Session(engine) as session:
        assert len(session.scalars(select(OpenLoopRow)).all()) == 1
        assert session.get(ClinicalDocumentRow, doc["document_id"]).payload["agent_analysis"][
            "run_id"
        ]
