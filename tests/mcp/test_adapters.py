from __future__ import annotations

import apps.mcp_server.mcp_server.adapters as adapters_module
from apps.mcp_server.mcp_server.adapters import RepositoryTools
from packages.contracts import ActorRef, EventType, HandoffReport
from packages.fixtures import main_case_events


class _Patients:
    def exists(self, patient_id: str) -> bool:
        return patient_id == "P-1001"


class _Events:
    def timeline(self, patient_id: str, *, hours: int) -> list:
        assert patient_id == "P-1001"
        assert hours == 720
        return [
            *main_case_events(),
            main_case_events()[0].model_copy(
                update={
                    "event_id": "EVT-ORDER-1",
                    "event_type": EventType.ORDER_UPDATED,
                    "payload_ref": "ORDER-1",
                }
            ),
        ]


class _Handoffs:
    def list_for_patient(self, patient_id: str) -> list[HandoffReport]:
        return [
            HandoffReport(
                handoff_id="HAND-1",
                patient_id=patient_id,
                encounter_id="ENC-2001",
                created_by=ActorRef(actor_id="DR-1", role="PHYSICIAN"),
            )
        ]


def test_repository_tools_expose_typed_event_views(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(adapters_module, "PatientRepository", lambda _session: _Patients())
    monkeypatch.setattr(adapters_module, "ClinicalEventRepository", lambda _session: _Events())
    tools = RepositoryTools(object())

    assert [item["event_type"] for item in tools.get_orders(patient_id="P-1001")] == [
        "ORDER_UPDATED"
    ]
    assert [item["event_type"] for item in tools.get_labs(patient_id="P-1001")] == [
        "LAB_RESULT_CREATED"
    ]
    assert [item["event_type"] for item in tools.get_consults(patient_id="P-1001")] == []
    assert [item["event_type"] for item in tools.get_progress_notes(patient_id="P-1001")] == [
        "NOTE_CREATED",
        "PROGRESS_NOTE_CREATED",
    ]


def test_repository_tools_return_the_latest_handoff(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(adapters_module, "PatientRepository", lambda _session: _Patients())
    monkeypatch.setattr(adapters_module, "HandoffRepository", lambda _session: _Handoffs())

    result = RepositoryTools(object()).get_handoff(patient_id="P-1001")

    assert result is not None
    assert result["handoff_id"] == "HAND-1"
