"""Exercise the real patient/document/task flow, isolation and review boundaries."""

from sqlalchemy import func, select

from apps.api.app.db_models import ClinicalEventRow, Encounter, EventPublicationRow, OpenLoopRow

HEADERS = {"X-Actor-Id": "DR-WORKSPACE", "X-Actor-Role": "PHYSICIAN"}


def patient(client, name="测试患者（模拟）"):
    response = client.post(
        "/api/v1/patients",
        headers=HEADERS,
        json={
            "display_name": name,
            "age": 52,
            "sex": "女",
            "ward": "测试病区",
            "bed": "08",
            "chief_complaint": "合成资料核对",
            "allergies": "待核对",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_patient_demographics_and_admission_time_round_trip(workspace):
    client, _ = workspace
    body = {
        "display_name": "基本信息测试（模拟）",
        "sex": "女",
        "age": 34,
        "ethnicity": "汉族",
        "marital_status": "已婚",
        "birthplace": "四川省成都市",
        "occupation": "教师",
        "admitted_at": "2026-10-25T09:30:00+08:00",
    }
    created = client.post("/api/v1/patients", headers=HEADERS, json=body)
    assert created.status_code == 201, created.text
    result = created.json()
    for key in (
        "display_name",
        "sex",
        "age",
        "ethnicity",
        "marital_status",
        "birthplace",
        "occupation",
    ):
        assert result[key] == body[key]
    from datetime import datetime

    assert datetime.fromisoformat(result["admitted_at"]) == datetime.fromisoformat(
        body["admitted_at"]
    )
    listed = client.get("/api/v1/patients").json()
    assert listed[0]["occupation"] == "教师"
    assert listed[0]["admitted_at"] == result["admitted_at"]


def document(client, p):
    response = client.post(
        f"/api/v1/patients/{p['patient_id']}/documents",
        headers=HEADERS,
        json={
            "encounter_id": p["encounter_id"],
            "kind": "ROUND",
            "title": "查房记录",
            "content": "本次查房核对资料，继续等待报告。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_seed_is_idempotent_and_preserves_edited_drafts(workspace):
    client, _ = workspace
    assert client.post("/api/v1/demo/patients", headers=HEADERS).json() == {"created": 6}
    rows = client.get("/api/v1/patients").json()
    assert len(rows) == 6
    assert all(row["synthetic"] and row["open_tasks"] == 1 for row in rows)
    p = rows[0]
    path = f"/api/v1/patients/{p['patient_id']}/documents"
    docs = client.get(path, params={"encounter_id": p["encounter_id"]}).json()
    draft = next(doc for doc in docs if doc["status"] == "DRAFT")
    client.patch(
        f"{path}/{draft['document_id']}",
        headers=HEADERS,
        json={"revision": draft["revision"], "title": draft["title"], "content": "队友补录的内容"},
    )
    assert client.post("/api/v1/demo/patients", headers=HEADERS).json() == {"created": 0}
    docs = client.get(path, params={"encounter_id": p["encounter_id"]}).json()
    assert any(doc["content"] == "队友补录的内容" for doc in docs)


def test_draft_conflict_submission_evidence_and_immutability(workspace):
    client, engine = workspace
    p = patient(client)
    doc = document(client, p)
    path = f"/api/v1/patients/{p['patient_id']}/documents/{doc['document_id']}"
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ClinicalEventRow)) == 0
    edit = {
        "revision": 1,
        "title": "查房记录（补充）",
        "content": "已核对患者资料，检验报告仍待回报。",
    }
    saved = client.patch(path, headers=HEADERS, json=edit)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2
    assert client.patch(path, headers=HEADERS, json=edit).status_code == 409
    assert client.post(path + "/submit", headers=HEADERS, json={"revision": 1}).status_code == 409
    submitted = client.post(path + "/submit", headers=HEADERS, json={"revision": 2}).json()
    assert submitted["status"] == "SUBMITTED" and submitted["event_id"]
    assert (
        client.post(path + "/submit", headers=HEADERS, json={"revision": 2}).json()["event_id"]
        == submitted["event_id"]
    )
    assert client.patch(path, headers=HEADERS, json={**edit, "revision": 3}).status_code == 409
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ClinicalEventRow)) == 1
        assert connection.scalar(select(func.count()).select_from(EventPublicationRow)) == 1
    handoff = client.post(
        f"/api/v1/patients/{p['patient_id']}/handoff/draft",
        params={"encounter_id": p["encounter_id"]},
        headers=HEADERS,
    )
    assert handoff.status_code == 200, handoff.text
    assert any("已核对患者资料" in text for text in handoff.json()["confirmed_items"])


def test_task_lifecycle_handoff_and_stale_updates(workspace):
    client, _ = workspace
    p = patient(client)
    base = f"/api/v1/patients/{p['patient_id']}"
    response = client.post(
        base + "/tasks",
        headers=HEADERS,
        json={
            "encounter_id": p["encounter_id"],
            "goal": "核对报告回报情况",
            "priority": "HIGH",
            "owner": "DR-WORKSPACE",
        },
    )
    assert response.status_code == 201, response.text
    task = response.json()
    assert task["state"] == "PLANNED"
    handoff = client.post(
        base + "/handoff/draft", params={"encounter_id": p["encounter_id"]}, headers=HEADERS
    ).json()
    assert task["loop_id"] in handoff["loop_ids"]
    path = base + "/tasks/" + task["loop_id"]
    progress = {"expected_state": "PLANNED", "state": "IN_PROGRESS", "reason": "开始核对报告"}
    assert client.patch(path, headers=HEADERS, json=progress).json()["state"] == "IN_PROGRESS"
    assert client.patch(path, headers=HEADERS, json=progress).status_code == 409
    finished = client.patch(
        path,
        headers=HEADERS,
        json={
            "expected_state": "IN_PROGRESS",
            "state": "RESOLVED",
            "reason": "已核对报告并记录结果",
        },
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["state"] == "RESOLVED"
    assert any(item["reason"] == "已核对报告并记录结果" for item in finished.json()["history"])
    assert (
        client.patch(
            path,
            headers=HEADERS,
            json={"expected_state": "RESOLVED", "state": "IN_PROGRESS", "reason": "再开"},
        ).status_code
        == 409
    )
    handoff = client.post(
        base + "/handoff/draft", params={"encounter_id": p["encounter_id"]}, headers=HEADERS
    ).json()
    assert task["loop_id"] not in handoff["loop_ids"]


def test_patient_and_encounter_isolation(workspace):
    client, engine = workspace
    first, second = patient(client, "患者甲（模拟）"), patient(client, "患者乙（模拟）")
    doc = document(client, first)
    other = f"/api/v1/patients/{second['patient_id']}"
    assert (
        client.get(other + "/documents", params={"encounter_id": first["encounter_id"]}).status_code
        == 404
    )
    assert (
        client.post(
            other + f"/documents/{doc['document_id']}/submit", headers=HEADERS, json={"revision": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            other + "/tasks",
            headers=HEADERS,
            json={
                "encounter_id": second["encounter_id"],
                "goal": "核对",
                "owner": "DR-1",
                "source_document_id": doc["document_id"],
            },
        ).status_code
        == 404
    )
    assert (
        client.get(other + "/documents", params={"encounter_id": second["encounter_id"]}).json()
        == []
    )
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        session.add(
            Encounter(
                encounter_id="ENC-SECOND-STAY",
                patient_id=first["patient_id"],
                ward="第二病区",
                payload={},
            )
        )
        session.commit()
    assert (
        client.get(
            f"/api/v1/patients/{first['patient_id']}/documents",
            params={"encounter_id": "ENC-SECOND-STAY"},
        ).json()
        == []
    )


def test_identity_and_validation_are_required(workspace):
    client, _ = workspace
    assert client.post("/api/v1/patients", json={"display_name": "模拟"}).status_code == 403
    assert client.post("/api/v1/demo/patients").status_code == 403
    assert (
        client.post(
            "/api/v1/patients",
            headers={**HEADERS, "X-Actor-Role": "PATIENT"},
            json={"display_name": "模拟"},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/patients", headers=HEADERS, json={"display_name": "  "}).status_code
        == 422
    )
    p = patient(client)
    response = client.post(
        f"/api/v1/patients/{p['patient_id']}/tasks",
        headers=HEADERS,
        json={
            "encounter_id": p["encounter_id"],
            "goal": "核对",
            "owner": "DR-1",
            "due_at": "2026-10-27T10:00:00",
        },
    )
    assert response.status_code == 422


def test_worker_processing_does_not_turn_document_into_blood_culture_task(workspace):
    client, engine = workspace
    from sqlalchemy.orm import Session

    from apps.worker.worker.agent import WorkflowAgent
    from apps.worker.worker.providers import MockProvider
    from apps.worker.worker.service import process_pending_database_events

    p = patient(client)
    doc = document(client, p)
    client.post(
        f"/api/v1/patients/{p['patient_id']}/documents/{doc['document_id']}/submit",
        headers=HEADERS,
        json={"revision": 1},
    )
    with Session(engine) as session:
        process_pending_database_events(session, WorkflowAgent(provider=MockProvider()), limit=20)
        session.commit()
        assert session.scalar(select(func.count()).select_from(OpenLoopRow)) == 0
