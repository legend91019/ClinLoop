"""Transcripts, evidence provenance, signatures, reminders and the existing agent loop."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.db_models import ClinicalDocumentRow, Encounter, EvidenceNodeRow, OpenLoopRow
from apps.api.app.services.round_reminder_service import round_status, sync_round_reminders
from apps.worker.worker.clinical_writing import DraftingError
from packages.contracts import utcnow
from tests.api.test_patient_workspace import HEADERS, patient
from tests.api.test_workspace_agent import drain, lab, review, state


def save(client, p, **extra):
    return client.post(
        f"/api/v1/patients/{p['patient_id']}/interviews",
        headers=HEADERS,
        json={
            "encounter_id": p["encounter_id"],
            "request_id": uuid4().hex,
            "transcript": "医生：今天有发热吗？\n患者：没有发热。\n医生：血培养结果出来后提醒我查看；补充患者过敏史。",
            "kind": "ROUND",
            "draft_mode": "DEMO",
            **extra,
        },
    )


def interviews(client, p):
    return client.get(
        f"/api/v1/patients/{p['patient_id']}/interviews", params={"encounter_id": p["encounter_id"]}
    ).json()


def test_transcript_to_signed_note_to_original_agent_loop(workspace, monkeypatch):
    client, engine = workspace
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    p = patient(client)
    lab_event = lab(client, p)
    other = patient(client, "检查来源隔离（模拟）")
    other_lab = lab(client, other)
    saved = save(client, p)
    assert saved.status_code == 202, saved.text
    original = saved.json()
    assert original["generation"]["status"] == "QUEUED"
    assert original["document"] is None
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(EvidenceNodeRow)) == 0
    drain(engine)
    generated = interviews(client, p)[0]
    assert generated["generation"]["status"] == "READY", generated
    doc = generated["document"]
    assert doc["status"] == "DRAFT"
    assert "患者诉无发热。" in doc["content"]
    assert "医生：" not in doc["content"]
    assert other_lab["event_id"] not in str(doc["generation"])
    assert doc["generation"]["source_text"] == original["transcript"]
    assert doc["generation"]["lab_sources"][0]["event_id"] == lab_event["event_id"]
    base = f"/api/v1/patients/{p['patient_id']}/documents"
    listed = client.get(base, params={"encounter_id": p["encounter_id"]}).json()
    assert len(listed) == 1 and listed[0]["document_id"] == doc["document_id"]
    # The transcript cannot be edited or signed through generic document endpoints.
    assert (
        client.patch(
            base + "/" + original["interview_id"],
            headers=HEADERS,
            json={"revision": 1, "title": "篡改", "content": "改变原始问诊内容"},
        ).status_code
        == 409
    )
    path = base + "/" + doc["document_id"]
    assert client.post(path + "/submit", headers=HEADERS, json={"revision": 1}).status_code == 422
    assert (
        client.post(
            path + "/submit",
            headers=HEADERS,
            json={"revision": 1, "signature_name": "李医生", "confirmed": False},
        ).status_code
        == 422
    )
    with Session(engine) as session:
        assert not session.get(ClinicalDocumentRow, doc["document_id"]).payload.get("signature")
        assert session.scalar(select(func.count()).select_from(EvidenceNodeRow)) == 0
    signed = client.post(
        path + "/submit",
        headers=HEADERS,
        json={"revision": 1, "signature_name": "李医生", "confirmed": True},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["signature"]["actor_id"] == HEADERS["X-Actor-Id"]
    assert (
        client.patch(
            path,
            headers=HEADERS,
            json={"revision": 2, "title": "篡改", "content": "签署后不允许修改"},
        ).status_code
        == 409
    )
    assert interviews(client, p)[0]["transcript"] == original["transcript"]
    assert (
        client.get(
            f"/api/v1/patients/{p['patient_id']}/first-round",
            params={"encounter_id": p["encounter_id"]},
        ).json()["state"]
        == "COMPLETED"
    )
    drain(engine)
    analyzed = next(
        item for item in state(client, p)["documents"] if item["document_id"] == doc["document_id"]
    )
    candidates = analyzed["analysis"]["candidates"]
    follow = next(item for item in candidates if item["proposal"]["intent_type"] == "FOLLOW_RESULT")
    assert review(client, p, doc, follow).status_code == 200
    assert len(state(client, p)["tasks"]) == 1
    assert drain(engine) == []


def test_source_idempotency_scope_validation_and_retry(workspace, monkeypatch):
    client, engine = workspace
    p = patient(client)
    key = uuid4().hex
    first = save(client, p, request_id=key).json()
    assert save(client, p, request_id=key).json()["interview_id"] == first["interview_id"]
    assert len(interviews(client, p)) == 1
    assert save(client, p, request_id=key, transcript="另一份不一样的问诊").status_code == 409
    other = patient(client, "另一位（模拟）")
    assert save(client, other, encounter_id=p["encounter_id"]).status_code == 404
    assert client.post(f"/api/v1/patients/{p['patient_id']}/interviews", json={}).status_code == 403
    from apps.worker.worker import clinical_note_workflow

    def fail(*args):
        raise DraftingError("NOTE_DRAFT_TIMEOUT")

    with monkeypatch.context() as patch:
        patch.setattr(clinical_note_workflow, "demo_clinical_note", fail)
        drain(engine)
    assert interviews(client, p)[0]["generation"]["status"] == "FAILED"
    retry = client.post(
        f"/api/v1/patients/{p['patient_id']}/interviews/{first['interview_id']}/retry",
        headers=HEADERS,
    )
    assert retry.status_code == 202
    drain(engine)
    assert interviews(client, p)[0]["generation"]["status"] == "READY"
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ClinicalDocumentRow)
                .where(ClinicalDocumentRow.status == "DRAFT")
            )
            == 1
        )


def test_first_round_boundary_persisted_once_and_only_signature_completes(workspace):
    client, engine = workspace
    p = patient(client)
    now = utcnow()
    with Session(engine) as session:
        encounter = session.get(Encounter, p["encounter_id"])
        encounter.admitted_at = now - timedelta(hours=48)
        session.commit()
        assert (
            round_status(
                session, p["patient_id"], p["encounter_id"], now=now - timedelta(microseconds=1)
            )["state"]
            == "PENDING"
        )
        assert sync_round_reminders(session, now=now - timedelta(microseconds=1)) == 0
        assert sync_round_reminders(session, now=now) == 1
        session.commit()
        assert sync_round_reminders(session, now=now) == 0
    tasks = client.get(
        f"/api/v1/patients/{p['patient_id']}/tasks", params={"encounter_id": p["encounter_id"]}
    ).json()
    assert len(tasks) == 1 and tasks[0]["system_managed"] is True
    assert tasks[0]["owner"] == HEADERS["X-Actor-Id"]
    assert (
        client.patch(
            f"/api/v1/patients/{p['patient_id']}/tasks/{tasks[0]['loop_id']}",
            headers=HEADERS,
            json={
                "expected_state": "PLANNED",
                "state": "RESOLVED",
                "reason": "不能手动关闭系统提醒",
            },
        ).status_code
        == 404
    )
    save(client, p)
    drain(engine)
    doc = interviews(client, p)[0]["document"]
    with Session(engine) as session:
        assert sync_round_reminders(session, now=now) == 0
        assert (
            round_status(session, p["patient_id"], p["encounter_id"], now=now)["state"] == "OVERDUE"
        )
    response = client.post(
        f"/api/v1/patients/{p['patient_id']}/documents/{doc['document_id']}/submit",
        headers=HEADERS,
        json={"revision": 1, "signature_name": "主管医生", "confirmed": True},
    )
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        assert sync_round_reminders(session) == 0
        session.commit()
        assert session.get(OpenLoopRow, tasks[0]["loop_id"]).state == "RESOLVED"
        assert round_status(session, p["patient_id"], p["encounter_id"])["completed_late"] is True
        assert sync_round_reminders(session) == 0
