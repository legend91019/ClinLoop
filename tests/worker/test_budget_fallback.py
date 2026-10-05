from __future__ import annotations

from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.policies import ExecutionPolicy
from packages.contracts import EventType, StopReason
from packages.fixtures import main_case_events


def test_budget_exceeded_preserves_completed_steps_without_new_state_change() -> None:
    agent = WorkflowAgent(policy=ExecutionPolicy(max_steps=2))

    run = agent.handle_event(main_case_events()[0])

    assert run.stop_reason is StopReason.BUDGET_EXCEEDED
    assert len(run.steps) == 2
    assert run.candidate_state_changes == {}


def test_budget_exceeded_does_not_issue_a_partial_finding() -> None:
    agent = WorkflowAgent(policy=ExecutionPolicy(max_steps=2))
    event = next(
        item for item in main_case_events() if item.event_type is EventType.LAB_RESULT_CREATED
    )

    run = agent.handle_event(event)

    assert run.stop_reason is StopReason.BUDGET_EXCEEDED
    assert run.finding_ids == []
    assert agent.findings == {}
