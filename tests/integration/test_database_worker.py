from __future__ import annotations

from sqlalchemy import select

from apps.api.app.db import session_scope
from apps.api.app.db_models import EventPublicationRow
from apps.api.app.repositories import ClinicalEventRepository
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import ProviderMetadata
from apps.worker.worker.service import process_pending_database_events
from packages.contracts import IntentType
from packages.fixtures import main_case_events


class CapturingProvider:
    kind = "real"
    name = "capture"
    metadata = ProviderMetadata(provider="capture", model="test")

    def __init__(self) -> None:
        self.visible: list[list[str]] = []

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


def test_database_worker_processes_outbox_once_and_marks_delivery(api_engine) -> None:
    event = main_case_events()[0].model_copy(
        update={"event_id": "EVT-LOCAL-OUTBOX", "payload_ref": "NOTE-LOCAL-OUTBOX"}
    )
    with session_scope(api_engine) as session:
        ClinicalEventRepository(session).add(event)
        session.add(EventPublicationRow(event_id=event.event_id, payload={}))

    provider = CapturingProvider()
    with session_scope(api_engine) as session:
        runs = process_pending_database_events(session, WorkflowAgent(provider=provider), limit=10)
        assert len(runs) == 1
        assert runs[0].trigger_event_id == event.event_id

    with session_scope(api_engine) as session:
        assert process_pending_database_events(session, WorkflowAgent(provider=provider)) == []
        publication = session.scalar(select(EventPublicationRow))
        assert publication.published_at is not None
        assert publication.attempts == 1
    assert len(provider.visible) == 1
    assert provider.visible[0][-1] == event.event_id
