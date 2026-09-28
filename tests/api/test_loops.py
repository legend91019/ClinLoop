"""Loop and finding read-model tests (Task 4).

Acceptance criteria from the plan:

* ``GET /api/v1/patients/{patient_id}/loops`` lists the patient's loops
* ``GET /api/v1/loops/{loop_id}`` returns the loop with its intent and
  an evidence summary
* ``GET /api/v1/findings/{finding_id}`` preserves the original claim,
  supporting evidence and searched sources
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from packages.fixtures import (
    FIXTURE_EVIDENCE_CULTURE_ID,
    FIXTURE_FINDING_ID,
    FIXTURE_LOOP_CULTURE_ID,
    FIXTURE_LOOP_SUSCEPTIBILITY_ID,
)


def test_patient_loops_are_listed(client: TestClient, patient_id: str) -> None:
    response = client.get(f"/api/v1/patients/{patient_id}/loops")
    assert response.status_code == 200

    loops = response.json()
    ids = {loop["loop_id"] for loop in loops}
    assert {FIXTURE_LOOP_CULTURE_ID, FIXTURE_LOOP_SUSCEPTIBILITY_ID} <= ids


def test_loop_list_projection_exposes_the_operational_fields(
    client: TestClient, patient_id: str
) -> None:
    loops = client.get(f"/api/v1/patients/{patient_id}/loops").json()
    loop = next(item for item in loops if item["loop_id"] == FIXTURE_LOOP_SUSCEPTIBILITY_ID)

    assert loop["state"] == "WAITING_EVENT"
    assert loop["waiting_for"] == ["LAB_RESULT_CREATED"]
    assert loop["depends_on"] == [FIXTURE_LOOP_CULTURE_ID]
    assert loop["priority"] == "HIGH"


def test_loops_can_be_filtered_to_active(client: TestClient, patient_id: str) -> None:
    response = client.get(f"/api/v1/patients/{patient_id}/loops", params={"active_only": True})
    assert response.status_code == 200
    for loop in response.json():
        assert loop["state"] not in {"RESOLVED", "CANCELLED"}


def test_unknown_patient_loops_is_empty(client: TestClient) -> None:
    response = client.get("/api/v1/patients/P-NOBODY/loops")
    assert response.status_code == 200
    assert response.json() == []


def test_loop_detail_returns_intent_and_evidence(client: TestClient) -> None:
    response = client.get(f"/api/v1/loops/{FIXTURE_LOOP_CULTURE_ID}")
    assert response.status_code == 200

    body = response.json()
    assert body["loop"]["loop_id"] == FIXTURE_LOOP_CULTURE_ID
    assert body["intent"] is not None
    assert body["intent"]["intent_type"] == "FOLLOW_RESULT"

    evidence_ids = {item["evidence_id"] for item in body["evidence"]}
    assert FIXTURE_EVIDENCE_CULTURE_ID in evidence_ids


def test_loop_detail_evidence_keeps_its_source_pointer(client: TestClient) -> None:
    """The console jumps from the loop to the raw lab record."""
    body = client.get(f"/api/v1/loops/{FIXTURE_LOOP_CULTURE_ID}").json()
    culture = next(
        item for item in body["evidence"] if item["evidence_id"] == FIXTURE_EVIDENCE_CULTURE_ID
    )
    assert culture["source_id"] == "LAB-8821"
    assert culture["source_type"] == "LABS"
    assert culture["trust_level"] == "SYSTEM_VERIFIED"


def test_loop_detail_lists_its_findings(client: TestClient) -> None:
    body = client.get(f"/api/v1/loops/{FIXTURE_LOOP_CULTURE_ID}").json()
    assert FIXTURE_FINDING_ID in body["findings"]


def test_unknown_loop_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/loops/LOOP-DOES-NOT-EXIST")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def test_finding_exposes_claim_evidence_and_searched_sources(client: TestClient) -> None:
    response = client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}")
    assert response.status_code == 200

    body = response.json()
    assert body["finding_type"] == "RESULT_WITHOUT_ACKNOWLEDGEMENT"
    assert body["claim"]
    assert FIXTURE_EVIDENCE_CULTURE_ID in body["supporting_evidence"]
    assert set(body["searched_sources"]) >= {"LABS", "NOTES", "PROGRESS_NOTES"}
    assert body["requires_review"] is True


def test_finding_links_back_to_its_loop_and_intent(client: TestClient) -> None:
    body = client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    assert body["loop_id"] == FIXTURE_LOOP_CULTURE_ID
    assert body["intent_id"]


def test_unknown_finding_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/findings/FND-DOES-NOT-EXIST")
    assert response.status_code == 404


def test_finding_404_body_is_a_structured_error(client: TestClient) -> None:
    body = client.get("/api/v1/findings/FND-DOES-NOT-EXIST").json()
    assert "detail" in body
