from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.db import session_factory
from apps.api.app.db_models import AuditLogRow, FindingRow, HandoffReportRow
from packages.fixtures import FIXTURE_FINDING_ID


@pytest.fixture(autouse=True)
def restore_fixture_review(api_engine):
    """Console write tests must not change the session-scoped seed for read tests."""
    with session_factory(api_engine)() as session:
        row = session.get(FindingRow, FIXTURE_FINDING_ID)
        previous = row.review_status, row.requires_review
    yield
    with session_factory(api_engine)() as session:
        row = session.get(FindingRow, FIXTURE_FINDING_ID)
        row.review_status, row.requires_review = previous
        session.commit()


def test_patient_findings_are_scoped(client: TestClient, patient_id: str) -> None:
    response = client.get(f"/api/v1/patients/{patient_id}/findings")
    assert response.status_code == 200
    assert any(item["finding_id"] == FIXTURE_FINDING_ID for item in response.json())
    assert all(item["patient_id"] == patient_id for item in response.json())
    assert client.get("/api/v1/patients/P-NOBODY/findings").json() == []


def test_evidence_source_returns_original_payload(client: TestClient) -> None:
    finding = client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    evidence_id = finding["supporting_evidence"][0]
    evidence = client.get(f"/api/v1/evidence/{evidence_id}").json()
    response = client.get(f"/api/v1/evidence/{evidence_id}/source")
    assert response.status_code == 200
    assert response.json()["payload_ref"] == evidence["source_id"]
    assert response.json()["payload"]
    assert client.get("/api/v1/evidence/UNKNOWN/source").status_code == 404


def _draft(client: TestClient, patient_id: str) -> dict:
    response = client.post(f"/api/v1/patients/{patient_id}/handoff/draft")
    assert response.status_code == 200
    return response.json()


def test_save_draft_preserves_links_and_appends_audit(client, patient_id, api_engine):
    draft = _draft(client, patient_id)
    response = client.patch(
        f"/api/v1/handoff/{draft['handoff_id']}",
        json={"situation": "已确认事实", "recommendation": "待跟进事项"},
        headers={"X-Actor-Id": "DR-CONSOLE", "X-Actor-Role": "PHYSICIAN"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["situation"] == "已确认事实"
    assert body["loop_ids"] == draft["loop_ids"]
    assert body["evidence_ids"] == draft["evidence_ids"]
    assert body["status"] == "DRAFT"
    assert client.get(f"/api/v1/handoff/{draft['handoff_id']}").json() == body
    with session_factory(api_engine)() as session:
        audit = session.scalar(
            select(AuditLogRow).where(
                AuditLogRow.entity_id == draft["handoff_id"], AuditLogRow.action == "edit_draft"
            )
        )
        assert audit.actor_id == "DR-CONSOLE"
        assert audit.payload["changes"]["situation"]["new"] == "已确认事实"


@pytest.mark.parametrize("field", ["status", "evidence_ids", "loop_ids", "pending_items"])
def test_draft_patch_rejects_protected_fields(client, patient_id, field):
    draft = _draft(client, patient_id)
    response = client.patch(f"/api/v1/handoff/{draft['handoff_id']}", json={field: []})
    assert response.status_code == 422


def test_sealed_draft_and_nonclinician_cannot_edit(client, patient_id, api_engine):
    draft = _draft(client, patient_id)
    url = f"/api/v1/handoff/{draft['handoff_id']}"
    assert (
        client.patch(url, json={"situation": "x"}, headers={"X-Actor-Role": "PATIENT"}).status_code
        == 403
    )
    with session_factory(api_engine)() as session:
        row = session.get(HandoffReportRow, draft["handoff_id"])
        row.status = "SEALED"
        from packages.contracts import utcnow

        row.sealed_at = utcnow()
        session.commit()
    assert client.patch(url, json={"situation": "x"}).status_code == 409
    assert client.patch("/api/v1/handoff/UNKNOWN", json={"situation": "x"}).status_code == 404


def test_draft_patch_disallows_null_and_empty_request(client, patient_id):
    draft = _draft(client, patient_id)
    url = f"/api/v1/handoff/{draft['handoff_id']}"
    assert client.patch(url, json={"situation": None}).status_code == 422
    assert client.patch(url, json={}).status_code == 422


def test_console_preflight_allows_local_origin_only(client):
    headers = {
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "content-type,x-actor-id,x-actor-role",
    }
    response = client.options("/api/v1/handoff/test", headers=headers)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == headers["Origin"]
    headers["Origin"] = "https://untrusted.invalid"
    response = client.options("/api/v1/handoff/test", headers=headers)
    assert "access-control-allow-origin" not in response.headers


def test_nonclinician_cannot_review_or_create_or_seal(client, patient_id):
    headers = {"X-Actor-Role": "PATIENT", "X-Actor-Id": "SYNTHETIC-PATIENT"}
    before = client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    assert (
        client.post(
            f"/api/v1/findings/{FIXTURE_FINDING_ID}/review",
            json={"action": "ACCEPT"},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json() == before
    assert (
        client.post(f"/api/v1/patients/{patient_id}/handoff/draft", headers=headers).status_code
        == 403
    )
    draft = _draft(client, patient_id)
    assert (
        client.post(f"/api/v1/handoff/{draft['handoff_id']}/seal", headers=headers).status_code
        == 403
    )


def test_draft_rejects_other_patient_encounter(client, patient_id):
    response = client.post(f"/api/v1/patients/{patient_id}/handoff/draft?encounter_id=ENC-UNKNOWN")
    assert response.status_code == 404


def test_draft_separates_confirmed_evidence_and_pending_findings(client, patient_id):
    finding = client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    draft = _draft(client, patient_id)
    assert draft["situation"]
    assert draft["background"]
    assert any(finding["claim"] in item for item in draft["pending_items"])
    assert any("Blood culture" in item for item in draft["confirmed_items"])


def test_review_and_seal_are_visible_in_patient_audit_without_overwriting_claim(client, patient_id):
    before = client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    draft = _draft(client, patient_id)
    response = client.post(
        f"/api/v1/findings/{FIXTURE_FINDING_ID}/review",
        json={"action": "ACCEPT", "reason": "合成病例人工核对"},
        headers={"X-Actor-Id": "DR-AUDIT", "X-Actor-Role": "PHYSICIAN"},
    )
    assert response.status_code == 200
    after = client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    for key in ("claim", "supporting_evidence", "searched_sources"):
        assert after[key] == before[key]
    assert client.post(f"/api/v1/handoff/{draft['handoff_id']}/seal").status_code == 200
    audit = client.get(f"/api/v1/patients/{patient_id}/audit").json()
    assert any(item["action"] == "review" and item["actor_id"] == "DR-AUDIT" for item in audit)
    assert any(
        item["action"] == "seal" and item["entity_id"] == draft["handoff_id"] for item in audit
    )
