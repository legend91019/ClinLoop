from __future__ import annotations

from fastapi.testclient import TestClient

from packages.fixtures import FIXTURE_FINDING_ID


def test_audit_route_returns_seed_audit_entries(client: TestClient, patient_id: str) -> None:
    response = client.get(f"/api/v1/patients/{patient_id}/audit")

    assert response.status_code == 200
    assert response.json()[0]["action"] == "seed_fixture"


def test_handoff_draft_route_contains_open_loop_and_confirmed_evidence(
    client: TestClient, patient_id: str
) -> None:
    response = client.post(
        f"/api/v1/patients/{patient_id}/handoff/draft",
        json={"encounter_id": "ENC-2001"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DRAFT"
    assert body["loop_ids"]
    assert body["evidence_ids"]


def test_trace_route_is_queryable_for_a_loop(client: TestClient) -> None:
    response = client.get("/api/v1/loops/LOOP-1001/trace")

    assert response.status_code == 200
    assert response.json() == []


def test_review_route_rejects_missing_reason(client: TestClient) -> None:
    response = client.post(
        f"/api/v1/findings/{FIXTURE_FINDING_ID}/review",
        json={"action": "REJECT"},
    )

    assert response.status_code == 422
