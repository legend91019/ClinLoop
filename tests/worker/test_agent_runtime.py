from __future__ import annotations

from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.repositories import AgentRunRepository
from packages.contracts import AgentStepKind, EventType, IntentType, StopReason
from packages.fixtures import main_case_events


def test_handle_event_records_a_trace_and_finding() -> None:
    event = next(e for e in main_case_events() if e.event_type is EventType.LAB_RESULT_CREATED)
    runs = AgentRunRepository()

    run = WorkflowAgent(runs=runs).handle_event(event)

    assert run.is_finished
    assert run.stop_reason is StopReason.REQUIRES_CLINICIAN_REVIEW
    assert [step.kind for step in run.steps] == list(AgentStepKind)
    assert run.finding_ids
    assert runs.get(run.run_id) == run


def test_resume_loop_persists_a_child_run_with_lineage() -> None:
    events = main_case_events()
    runs = AgentRunRepository()
    agent = WorkflowAgent(runs=runs)
    first = agent.handle_event(events[0])

    resumed = agent.resume_loop("LOOP-1001", events[1])

    assert resumed.run_id != first.run_id
    assert resumed.resumed_from_run_id == first.run_id
    assert resumed.loop_id == "LOOP-1001"
    assert runs.get(resumed.run_id) == resumed
    assert len(runs.all()) == 2


def test_replan_persists_new_evidence_in_the_child_plan() -> None:
    event = main_case_events()[0]
    runs = AgentRunRepository()
    agent = WorkflowAgent(runs=runs)
    first = agent.handle_event(event)

    replanned = agent.replan(first.run_id, ["EVIDENCE-NEW"])

    assert replanned.run_id != first.run_id
    assert replanned.resumed_from_run_id == first.run_id
    assert "replan_with_new_evidence" in replanned.plan
    assert "evidence:EVIDENCE-NEW" in replanned.plan
    assert runs.get(replanned.run_id) == replanned


def test_note_event_creates_follow_result_intent_and_waiting_loop() -> None:
    event = main_case_events()[0]
    agent = WorkflowAgent()

    run = agent.handle_event(event)

    context = agent.memory.get_context(event.patient_id, run.loop_id)
    assert context.intents[0].intent_type is IntentType.FOLLOW_RESULT
    assert context.intents[0].source_event_id == event.event_id
    assert context.loops[0].loop_id == run.loop_id
    assert context.loops[0].waiting_for == [EventType.LAB_RESULT_CREATED]
