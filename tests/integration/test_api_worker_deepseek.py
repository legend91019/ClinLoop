from __future__ import annotations

from datetime import UTC, datetime

from apps.api.app.db import session_scope
from apps.api.app.repositories import AgentRunRepository, ClinicalEventRepository, FindingRepository
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import ProviderMetadata
from apps.worker.worker.service import process_event
from packages.contracts import ActorRef, ClinicalEvent, EventType, IntentType, StopReason


class FakeProvider:
    kind = "real"
    name = "fake-deepseek"

    def __init__(self) -> None:
        self.metadata = ProviderMetadata(provider=self.name, model="fake-model")

    def analyze(self, context: AgentContext) -> AgentProposal:
        return AgentProposal(
            patient_id=context.event.patient_id,
            intent_type=IntentType.FOLLOW_RESULT,
            goal="Follow the model-proposed result",
            rationale="The fake provider exercises the real provider boundary.",
            expected_evidence=["blood_culture_result"],
            waiting_for=[EventType.LAB_RESULT_CREATED],
            priority="HIGH",
            confidence=0.88,
        )


def test_worker_persists_model_trace_and_candidates(api_engine) -> None:
    now = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
    event = ClinicalEvent(
        event_id="EVT-WORKER-1",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        event_type=EventType.NOTE_CREATED,
        event_time=now,
        source_time=now,
        payload_ref="NOTE-WORKER-1",
        actor=ActorRef(actor_id="DR-TEST", role="PHYSICIAN"),
        payload={"text": "复查血培养"},
    )
    with session_scope(api_engine) as session:
        before_findings = {
            item.finding_id for item in FindingRepository(session).list_for_patient("P-1001")
        }
        ClinicalEventRepository(session).add(event)
        persisted = process_event(session, WorkflowAgent(provider=FakeProvider()), event)

    with session_scope(api_engine) as session:
        loaded = AgentRunRepository(session).get(persisted.run_id)
        assert loaded is not None
        assert loaded.trace_metadata["provider"] == "fake-deepseek"
        after_findings = {
            item.finding_id for item in FindingRepository(session).list_for_patient("P-1001")
        }
        assert after_findings == before_findings


def test_worker_persists_model_error_without_finding(api_engine) -> None:
    now = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
    event = ClinicalEvent(
        event_id="EVT-WORKER-ERROR",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        event_type=EventType.NOTE_CREATED,
        event_time=now,
        source_time=now,
        payload_ref="NOTE-WORKER-ERROR",
        actor=ActorRef(actor_id="DR-TEST", role="PHYSICIAN"),
        payload={"text": "复查血培养"},
    )

    class ErrorProvider(FakeProvider):
        def analyze(self, context: AgentContext):
            from apps.worker.worker.providers import ModelProviderError

            raise ModelProviderError("MODEL_TIMEOUT")

    with session_scope(api_engine) as session:
        ClinicalEventRepository(session).add(event)
        persisted = process_event(session, WorkflowAgent(provider=ErrorProvider()), event)
        assert persisted.stop_reason is StopReason.MODEL_ERROR
        assert persisted.finding_ids == []
