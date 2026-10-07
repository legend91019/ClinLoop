from __future__ import annotations

from datetime import timedelta

from apps.api.app.db import session_scope
from apps.api.app.repositories import (
    ClinicalEventRepository,
    ClinicalIntentRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
)
from apps.api.app.services.evidence_source_service import resolve_source_event
from apps.api.app.services.handoff_service import create_draft
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import ProviderMetadata
from apps.worker.worker.service import process_event
from packages.contracts import IntentType, LoopState, utcnow
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
        assert LoopRepository(session).get(note_run.loop_id).priority == "HIGH"
        assert note_run.loop_id
    with session_scope(api_engine) as session:
        lab_run = process_event(session, WorkflowAgent(provider=provider), lab)

    assert lab_run.loop_id == note_run.loop_id
    assert lab_run.resumed_from_run_id == note_run.run_id
    assert [tool.tool_name for tool in lab_run.tool_calls] == ["get_labs", "get_progress_notes"]
    assert lab_run.finding_ids
    with session_scope(api_engine) as session:
        finding = FindingRepository(session).get(lab_run.finding_ids[0])
        assert finding is not None
        evidence = EvidenceRepository(session).get(finding.supporting_evidence[0])
        assert evidence is not None
        assert evidence.source_id == lab.payload_ref
        assert evidence.encounter_id == lab.encounter_id
        assert resolve_source_event(session, evidence).event_id == lab.event_id
        assert LoopRepository(session).get(note_run.loop_id).state is LoopState.RESULT_AVAILABLE


def test_clinician_acknowledgement_replans_only_its_result_loop(api_engine) -> None:
    base = utcnow() - timedelta(minutes=20)
    original_note, original_lab, original_progress, *_ = main_case_events()
    note = original_note.model_copy(
        update={
            "event_id": "EVT-ACK-NOTE",
            "payload_ref": "NOTE-ACK",
            "event_time": base,
            "source_time": base,
        }
    )
    lab = original_lab.model_copy(
        update={
            "event_id": "EVT-ACK-LAB",
            "payload_ref": "LAB-ACK",
            "event_time": base + timedelta(minutes=5),
            "source_time": base + timedelta(minutes=5),
        }
    )
    progress = original_progress.model_copy(
        update={
            "event_id": "EVT-ACK-PROGRESS",
            "payload_ref": "NOTE-ACK-PROGRESS",
            "event_time": base + timedelta(minutes=10),
            "source_time": base + timedelta(minutes=10),
            "payload": {
                **original_progress.payload,
                "acknowledges_event_id": lab.event_id,
                "creates_dependency": "susceptibility_result",
            },
        }
    )
    with session_scope(api_engine) as session:
        for event in (note, lab, progress):
            ClinicalEventRepository(session).add(event)
    provider = CapturingProvider()
    with session_scope(api_engine) as session:
        note_run = process_event(session, WorkflowAgent(provider=provider), note)
    with session_scope(api_engine) as session:
        lab_run = process_event(session, WorkflowAgent(provider=provider), lab)
    with session_scope(api_engine) as session:
        progress_run = process_event(session, WorkflowAgent(provider=provider), progress)

    assert progress_run.loop_id == note_run.loop_id
    assert progress_run.resumed_from_run_id == lab_run.run_id
    with session_scope(api_engine) as session:
        loops = LoopRepository(session).list_for_patient(note.patient_id)
        parent = LoopRepository(session).get(note_run.loop_id)
        assert parent.state is LoopState.ACKNOWLEDGED
        dependencies = [loop for loop in loops if loop.depends_on == [parent.loop_id]]
        assert len(dependencies) == 1
        dependent_intent = ClinicalIntentRepository(session).get(dependencies[0].intent_id)
        assert dependent_intent.expected_evidence == ["susceptibility_result"]
        assert dependent_intent.source_event_id == progress.event_id

    susceptibility = original_lab.model_copy(
        update={
            "event_id": "EVT-ACK-SUSCEPTIBILITY",
            "payload_ref": "LAB-ACK-SUSCEPTIBILITY",
            "event_time": base + timedelta(minutes=15),
            "source_time": base + timedelta(minutes=15),
            "payload": {"panel": "susceptibility_result", "result": "synthetic_pending_review"},
        }
    )
    with session_scope(api_engine) as session:
        ClinicalEventRepository(session).add(susceptibility)
    with session_scope(api_engine) as session:
        susceptibility_run = process_event(
            session, WorkflowAgent(provider=provider), susceptibility
        )
    assert susceptibility_run.loop_id == dependencies[0].loop_id
    assert susceptibility_run.finding_ids
    with session_scope(api_engine) as session:
        assert (
            LoopRepository(session).get(dependencies[0].loop_id).state is LoopState.RESULT_AVAILABLE
        )
        handoff = create_draft(session, note.patient_id, note.encounter_id, progress.actor)
        assert dependencies[0].loop_id in handoff.loop_ids
        assert handoff.pending_items
