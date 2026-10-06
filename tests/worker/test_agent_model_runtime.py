from __future__ import annotations

from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import ModelProviderError, ProviderMetadata
from apps.worker.worker.repositories import AgentRunRepository
from packages.contracts import EventType, IntentType, StopReason
from packages.fixtures import main_case_events


class ProposalProvider:
    kind = "real"
    name = "fake-deepseek"

    def __init__(self) -> None:
        self.metadata = ProviderMetadata(provider=self.name, model="fake-model")

    def analyze(self, context: AgentContext) -> AgentProposal:
        event = context.event
        if event.event_type is EventType.NOTE_CREATED:
            return AgentProposal(
                patient_id=event.patient_id,
                intent_type=IntentType.FOLLOW_RESULT,
                goal="Follow the model-selected culture result",
                rationale="The model identified a result follow-up intent.",
                expected_evidence=["blood_culture_result"],
                waiting_for=[EventType.LAB_RESULT_CREATED],
                priority="HIGH",
                confidence=0.93,
            )
        return AgentProposal(
            patient_id=event.patient_id,
            intent_type=None,
            goal="Review the current event",
            rationale="The model selected evidence review.",
            confidence=0.7,
            evidence_refs=[event.payload_ref],
        )


class FailingProvider(ProposalProvider):
    def analyze(self, context: AgentContext) -> AgentProposal:
        raise ModelProviderError("MODEL_TIMEOUT")


def test_model_proposal_changes_loop_and_is_visible_in_trace() -> None:
    runs = AgentRunRepository()
    agent = WorkflowAgent(runs=runs, provider=ProposalProvider())

    run = agent.handle_event(main_case_events()[0])

    loop = agent.memory.loops[run.loop_id]
    assert loop.goal == "Follow the model-selected culture result"
    assert run.trace_metadata["provider"] == "fake-deepseek"
    assert run.trace_metadata["model"] == "fake-model"
    assert "model-selected" in run.trace_metadata["proposal_summary"]


def test_model_error_stops_without_loop_or_finding() -> None:
    agent = WorkflowAgent(provider=FailingProvider())

    run = agent.handle_event(main_case_events()[0])

    assert run.stop_reason is StopReason.MODEL_ERROR
    assert run.finding_ids == []
    assert agent.memory.loops == {}
    assert run.trace_metadata["error_code"] == "MODEL_TIMEOUT"
