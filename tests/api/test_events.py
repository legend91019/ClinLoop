"""Event ingest and timeline tests (Task 4).

Acceptance criteria from the plan:

* a valid ``ClinicalEvent`` returns **202** with its ``event_id``
* an invalid event returns **422**
* a duplicate ``event_id`` returns **409**
* the timeline is ordered by ``event_time`` and defaults to 24 hours
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from packages.contracts import EventType, utcnow
from packages.fixtures import MAIN_CASE, MAIN_PATIENT_ID


def event_payload(
    *,
    event_id: str = "EVT-API-0001",
    event_type: str = EventType.CONSULT_NOTE_CREATED.value,
    hours_after_demo: float = 0.0,
    **overrides: object,
) -> dict[str, object]:
    """A valid ingest payload, anchored near 'now' so the timeline window catches it."""
    reference = utcnow()
    moment = reference + timedelta(hours=hours_after_demo)
    payload: dict[str, object] = {
        "event_id": event_id,
        "patient_id": MAIN_PATIENT_ID,
        "encounter_id": MAIN_CASE.encounter_id,
        "event_type": event_type,
        "event_time": moment.isoformat(),
        "source_time": (moment + timedelta(minutes=1)).isoformat(),
        "payload_ref": "CONSULT-6001",
        "actor": {"actor_id": "DR-777", "role": "CONSULTANT", "display_name": "Dr. Synth"},
        "payload": {"text": "Synthetic consult note."},
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# POST /api/v1/events
# --------------------------------------------------------------------------


def test_valid_event_is_accepted_with_202_and_event_id(client: TestClient) -> None:
    response = client.post("/api/v1/events", json=event_payload(event_id="EVT-API-1001"))
    assert response.status_code == 202, response.text

    body = response.json()
    assert body["event_id"] == "EVT-API-1001"
    assert body["accepted"] is True
    assert body["duplicate"] is False


def test_duplicate_event_returns_409(client: TestClient) -> None:
    payload = event_payload(event_id="EVT-API-1002")
    first = client.post("/api/v1/events", json=payload)
    assert first.status_code == 202

    second = client.post("/api/v1/events", json=payload)
    assert second.status_code == 409, second.text
    assert "EVT-API-1002" in second.json()["detail"]


def test_invalid_event_returns_422(client: TestClient) -> None:
    broken = event_payload(event_id="EVT-API-1003")
    del broken["event_type"]

    response = client.post("/api/v1/events", json=broken)
    assert response.status_code == 422


def test_unknown_event_type_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/events", json=event_payload(event_id="EVT-API-1004", event_type="NOT_A_TYPE")
    )
    assert response.status_code == 422


def test_naive_event_time_is_rejected(client: TestClient) -> None:
    broken = event_payload(event_id="EVT-API-1005")
    broken["event_time"] = "2026-09-28T09:10:00"  # no offset
    response = client.post("/api/v1/events", json=broken)
    assert response.status_code == 422


def test_unknown_field_is_rejected(client: TestClient) -> None:
    """extra='forbid' must survive the HTTP boundary."""
    broken = event_payload(event_id="EVT-API-1006")
    broken["unexpected"] = "nope"
    response = client.post("/api/v1/events", json=broken)
    assert response.status_code == 422


def test_accepted_event_appears_on_the_timeline(client: TestClient, patient_id: str) -> None:
    event_id = "EVT-API-1007"
    client.post("/api/v1/events", json=event_payload(event_id=event_id))

    response = client.get(f"/api/v1/patients/{patient_id}/timeline", params={"hours": 24})
    assert response.status_code == 200

    ids = [entry["event_id"] for entry in response.json()["entries"]]
    assert event_id in ids


def test_ingesting_does_not_modify_loop_state(client: TestClient, patient_id: str) -> None:
    """Task 4 is ingest only: no agent runs, no state changes."""
    before = client.get(f"/api/v1/patients/{patient_id}/loops").json()
    client.post("/api/v1/events", json=event_payload(event_id="EVT-API-1008"))
    after = client.get(f"/api/v1/patients/{patient_id}/loops").json()
    assert before == after


# --------------------------------------------------------------------------
# GET /api/v1/patients/{patient_id}/timeline
# --------------------------------------------------------------------------


def test_timeline_is_ordered_by_event_time(client: TestClient, patient_id: str) -> None:
    response = client.get(f"/api/v1/patients/{patient_id}/timeline", params={"hours": 72})
    assert response.status_code == 200

    entries = response.json()["entries"]
    assert len(entries) >= len(MAIN_CASE.timeline)

    times = [entry["event_time"] for entry in entries]
    assert times == sorted(times)


def test_timeline_defaults_to_24_hours_window(client: TestClient, patient_id: str) -> None:
    response = client.get(f"/api/v1/patients/{patient_id}/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["hours"] == 24
    assert body["patient_id"] == patient_id


def test_timeline_respects_the_hours_parameter(client: TestClient, patient_id: str) -> None:
    wide = client.get(f"/api/v1/patients/{patient_id}/timeline", params={"hours": 72}).json()
    narrow = client.get(f"/api/v1/patients/{patient_id}/timeline", params={"hours": 1}).json()
    assert wide["count"] >= narrow["count"]
    assert narrow["hours"] == 1


def test_timeline_rejects_nonsense_hours(client: TestClient, patient_id: str) -> None:
    assert (
        client.get(f"/api/v1/patients/{patient_id}/timeline", params={"hours": 0}).status_code
        == 422
    )
    assert (
        client.get(f"/api/v1/patients/{patient_id}/timeline", params={"hours": -3}).status_code
        == 422
    )


def test_timeline_entries_carry_source_and_actor(client: TestClient, patient_id: str) -> None:
    entries = client.get(f"/api/v1/patients/{patient_id}/timeline", params={"hours": 72}).json()[
        "entries"
    ]
    first = entries[0]
    assert {"event_id", "event_type", "event_time", "source_time", "actor", "payload_ref"} <= set(
        first
    )
    assert first["actor"]["actor_id"]


def test_unknown_patient_timeline_is_empty_not_500(client: TestClient) -> None:
    response = client.get("/api/v1/patients/P-NOBODY/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["entries"] == []
