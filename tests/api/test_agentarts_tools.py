from __future__ import annotations

from apps.api.app.settings import get_settings
from packages.fixtures import main_case_events


def test_tool_requires_configured_shared_key(client, monkeypatch) -> None:
    note, *_ = main_case_events()
    monkeypatch.setenv("AGENTARTS_TOOL_KEY", "test-tool-key")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/v1/agentarts/tools/get_progress_notes",
            json={"patient_id": note.patient_id, "trigger_event_id": note.event_id},
        )
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_read_only_tool_is_scoped_to_trigger_and_patient(client, monkeypatch) -> None:
    note, lab, *_ = main_case_events()
    monkeypatch.setenv("AGENTARTS_TOOL_KEY", "test-tool-key")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/v1/agentarts/tools/get_labs",
            headers={"X-ClinLoop-Tool-Key": "test-tool-key"},
            json={"patient_id": lab.patient_id, "trigger_event_id": note.event_id},
        )
        assert response.status_code == 200
        assert all(
            item["source_time"] <= note.source_time.isoformat()
            for item in response.json()["result"]
        )

        mismatch = client.post(
            "/api/v1/agentarts/tools/get_labs",
            headers={"X-ClinLoop-Tool-Key": "test-tool-key"},
            json={"patient_id": "P-OTHER", "trigger_event_id": note.event_id},
        )
        assert mismatch.status_code == 404

        write = client.post(
            "/api/v1/agentarts/tools/seal_handoff_report",
            headers={"X-ClinLoop-Tool-Key": "test-tool-key"},
            json={"patient_id": note.patient_id, "trigger_event_id": note.event_id},
        )
        assert write.status_code == 404
    finally:
        get_settings.cache_clear()
