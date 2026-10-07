from __future__ import annotations

from datetime import timedelta

from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import ProviderMetadata
from packages.contracts import EventType, IntentType, StopReason
from packages.fixtures import main_case_events


class SelectingProvider:
    kind = "real"
    name = "test-model"
    metadata = ProviderMetadata(provider="test-model", model="test")

    def analyze(self, context: AgentContext) -> AgentProposal:
        return AgentProposal(
            patient_id=context.event.patient_id,
            intent_type=IntentType.FOLLOW_RESULT,
            goal="Follow the blood culture result",
            rationale="Check the result and clinician response",
            expected_evidence=["blood_culture_result"],
            waiting_for=[EventType.LAB_RESULT_CREATED],
            priority="HIGH",
            confidence=0.8,
            requested_tools=["get_labs", "get_progress_notes"]
            if context.event.event_type is EventType.LAB_RESULT_CREATED
            else [],
        )


class RecordingTools:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def call(self, name: str, **arguments):
        self.calls.append(name)
        event_type = {
            "get_labs": EventType.LAB_RESULT_CREATED,
            "get_progress_notes": EventType.PROGRESS_NOTE_CREATED,
        }[name]
        return [
            event.model_dump(mode="json") for event in self.events if event.event_type is event_type
        ]


def test_unmatched_lab_result_does_not_create_a_gap() -> None:
    note, lab, *_ = main_case_events()
    agent = WorkflowAgent(provider=SelectingProvider())
    agent.handle_event(note)
    unrelated = lab.model_copy(
        update={
            "event_id": "EVT-UNRELATED-LAB",
            "payload_ref": "LAB-UNRELATED",
            "payload": {**lab.payload, "panel": "METABOLIC_PANEL"},
        }
    )

    run = agent.handle_event(unrelated)

    assert run.finding_ids == []
    assert run.stop_reason is StopReason.WAITING_EXTERNAL_EVENT


def test_matching_result_stays_with_its_patient_when_two_loops_exist() -> None:
    note, lab, *_ = main_case_events()
    other_note = note.model_copy(
        update={
            "event_id": "EVT-OTHER-NOTE",
            "patient_id": "P-OTHER",
            "encounter_id": "ENC-OTHER",
            "payload_ref": "NOTE-OTHER",
        }
    )
    agent = WorkflowAgent(provider=SelectingProvider())
    first = agent.handle_event(note)
    second = agent.handle_event(other_note)

    result = agent.handle_event(lab, tool_registry=RecordingTools([lab]))

    assert first.loop_id != second.loop_id
    assert result.loop_id == first.loop_id
    assert result.finding_ids


def test_acknowledged_result_does_not_create_a_gap() -> None:
    note, lab, progress, *_ = main_case_events()
    early_ack = progress.model_copy(
        update={
            "event_id": "EVT-EARLY-ACK",
            "event_time": lab.event_time + timedelta(minutes=1),
            "source_time": lab.source_time,
            "payload": {**progress.payload, "acknowledges_event_id": lab.event_id},
        }
    )
    agent = WorkflowAgent(provider=SelectingProvider())
    agent.handle_event(note)
    agent.memory.record_event(early_ack)
    registry = RecordingTools([lab, early_ack])

    run = agent.handle_event(lab, tool_registry=registry)

    assert registry.calls == ["get_labs", "get_progress_notes"]
    assert [tool.tool_name for tool in run.tool_calls] == registry.calls
    assert run.finding_ids == []


def test_unacknowledged_result_records_real_read_calls() -> None:
    note, lab, *_ = main_case_events()
    agent = WorkflowAgent(provider=SelectingProvider())
    agent.handle_event(note)
    registry = RecordingTools([lab])

    run = agent.handle_event(lab, tool_registry=registry)

    assert [tool.tool_name for tool in run.tool_calls] == ["get_labs", "get_progress_notes"]
    assert all(tool.ok and tool.result_ref for tool in run.tool_calls)
    assert run.finding_ids


def test_result_missing_from_lab_tool_does_not_create_a_gap() -> None:
    note, lab, *_ = main_case_events()
    agent = WorkflowAgent(provider=SelectingProvider())
    agent.handle_event(note)
    registry = RecordingTools([])

    run = agent.handle_event(lab, tool_registry=registry)

    assert [tool.tool_name for tool in run.tool_calls] == ["get_labs", "get_progress_notes"]
    assert run.finding_ids == []
