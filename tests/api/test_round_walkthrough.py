from sqlalchemy.orm import Session

from apps.api.app.db_models import ClinicalDocumentRow
from scripts.init_round_walkthrough import seed


def test_interview_api_and_repair_preserve_fixture_and_doctor_edits(workspace):
    client, engine = workspace
    with Session(engine) as session:
        seed(session)
        session.commit()
    url = "/api/v1/patients/P-ROUND-DEMO/interviews"
    params = {"encounter_id": "ENC-ROUND-DEMO"}
    reply = client.get(url, params=params)
    assert reply.status_code == 200, reply.text
    item = reply.json()[0]
    assert item["kind"] == "ROUND"
    assert item["generation"]["draft_mode"] == "DEMO"
    assert item["document"]["document_id"] == "ROUND-DEMO-DRAFT"
    with Session(engine) as session:
        raw = session.get(ClinicalDocumentRow, "ROUND-DEMO-RAW")
        original = raw.content
        raw.payload = {}
        raw.status = "SUBMITTED"
        draft = session.get(ClinicalDocumentRow, "ROUND-DEMO-DRAFT")
        draft.content = "医生已编辑，不能覆盖"
        session.commit()
        assert not seed(session)
        session.commit()
        assert raw.content == original
        assert raw.status == "TRANSCRIPT"
        assert draft.content == "医生已编辑，不能覆盖"
    repaired = client.get(url, params=params)
    assert repaired.status_code == 200
    assert repaired.json()[0]["generation"]["status"] == "READY"


def test_walkthrough_preserves_existing_edits(workspace):
    _, engine = workspace
    with Session(engine) as session:
        assert seed(session)
        session.commit()
        draft = session.get(ClinicalDocumentRow, "ROUND-DEMO-DRAFT")
        assert "交接" not in draft.content
        assert "交接" in draft.payload["generation"]["source_text"]
        draft.content = "医生已修改的内容"
        session.commit()
        assert not seed(session)
        assert draft.content == "医生已修改的内容"


def test_preparation_visible_without_write_identity_and_scoped(workspace):
    client, engine = workspace
    with Session(engine) as session:
        seed(session)
        session.commit()
    reply = client.get(
        "/api/v1/patients/P-ROUND-DEMO/round-preparation", params={"encounter_id": "ENC-ROUND-DEMO"}
    )
    assert reply.status_code == 200
    data = reply.json()
    assert len(data["new_labs"]) == 1
    assert data["new_labs"][0]["label"] == "blood_count_result"
    assert data["last_round"]["id"] == "ROUND-DEMO-BASE"
    assert (
        client.get(
            "/api/v1/patients/P-ROUND-DEMO/round-preparation", params={"encounter_id": "OTHER"}
        ).status_code
        == 404
    )
