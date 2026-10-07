from __future__ import annotations

from datetime import timedelta

from apps.api.app.db import session_scope
from apps.api.app.repositories import ClinicalEventRepository
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import ProviderMetadata
from apps.worker.worker.service import process_event
from packages.contracts import IntentType, utcnow
from packages.fixtures import main_case_events


class CapturingProvider:
    kind = "real"
    name = "capture"
    metadata = ProviderMetadata(provider="capture", model="test")

    def __init__(self):
        self.visible = []

    def analyze(self, context: AgentContext) -> AgentProposal:
        self.visible.append([event.event_id for event in context.recent_events])
        return AgentProposal(
            patient_id=context.event.patient_id,
            intent_type=IntentType.FOLLOW_RESULT,
            goal="Follow the culture result",
            rationale="Synthetic test",
            expected_evidence=["blood_culture_result"],
            confidence=0.8,
        )


def test_worker_model_does_not_see_future_seeded_events(api_engine) -> None:
    provider = CapturingProvider()
    with session_scope(api_engine) as session:
        process_event(session, WorkflowAgent(provider=provider), main_case_events()[0])

    assert provider.visible == [["EVT-1001"]]


def test_database_worker_reads_lab_and_notes_before_raising_gap(api_engine) -> None:
    base = utcnow() - timedelta(minutes=10)
    original_note, original_lab, *_ = main_case_events()
    note = original_note.model_copy(
        update={
            "event_id": "EVT-LIVE-NOTE",
            "payload_ref": "NOTE-LIVE",
            "event_time": base,
            "source_time": base + timedelta(minutes=1),
        }
    )
    lab = original_lab.model_copy(
        update={
            "event_id": "EVT-LIVE-LAB",
            "payload_ref": "LAB-LIVE",
            "event_time": base + timedelta(minutes=5),
            "source_time": base + timedelta(minutes=6),
        }
    )
    provider = CapturingProvider()
    with session_scope(api_engine) as session:
        ClinicalEventRepository(session).add(note)
        ClinicalEventRepository(session).add(lab)
    with session_scope(api_engine) as session:
        note_run = process_event(session, WorkflowAgent(provider=provider), note)
        assert note_run.loop_id
    with session_scope(api_engine) as session:
        lab_run = process_event(session, WorkflowAgent(provider=provider), lab)

    assert lab_run.loop_id == note_run.loop_id
    assert [tool.tool_name for tool in lab_run.tool_calls] == ["get_labs", "get_progress_notes"]
    assert lab_run.finding_ids
