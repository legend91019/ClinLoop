"""Durable Worker boundary between Agent memory and API repositories."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.db_models import EventPublicationRow
from apps.api.app.repositories import (
    AgentRunRepository as DbAgentRunRepository,
)
from apps.api.app.repositories import (
    AuditRepository,
    ClinicalEventRepository,
    ClinicalIntentRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
)
from apps.mcp_server.mcp_server.server import build_registry
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.memory import WorkflowMemory
from packages.contracts import ActorRef, ClinicalEvent, utcnow

WORKER_ACTOR = ActorRef(actor_id="WORKER", role="SYSTEM", display_name="ClinLoop Worker")


def publish_pending_events(session: Session, bus, *, limit: int = 100) -> int:
    """Repair API-to-Redis publication gaps; duplicate messages are event-idempotent."""
    pending = session.scalars(
        select(EventPublicationRow)
        .where(EventPublicationRow.published_at.is_(None))
        .order_by(EventPublicationRow.created_at, EventPublicationRow.event_id)
        .limit(limit)
    ).all()
    events = ClinicalEventRepository(session)
    count = 0
    for publication in pending:
        event = events.get(publication.event_id)
        if event is None:
            continue
        bus.publish(event)
        publication.published_at = utcnow()
        publication.attempts += 1
        count += 1
    return count


def hydrate_memory(session: Session, trigger: ClinicalEvent, memory: WorkflowMemory) -> None:
    """Load one patient's records available at the trigger's source time."""
    visible_events = [
        event
        for event in ClinicalEventRepository(session).list_for_patient(trigger.patient_id)
        if event.source_time <= trigger.source_time
    ]
    visible_ids = {event.event_id for event in visible_events}
    for event in visible_events:
        memory.record_event(event)
    for intent in ClinicalIntentRepository(session).list_for_patient(trigger.patient_id):
        if intent.source_event_id is None or intent.source_event_id in visible_ids:
            memory.save_intent(intent)
    for loop in LoopRepository(session).list_for_patient(trigger.patient_id):
        if loop.intent_id not in memory.intents:
            continue
        if loop.last_planned_at is not None and loop.last_planned_at > trigger.source_time:
            continue
        memory.save_loop(loop)
    evidence_repo = EvidenceRepository(session)
    for evidence in evidence_repo.list_for_patient(trigger.patient_id):
        if evidence.observed_at <= trigger.source_time:
            memory.append_evidence(evidence, loop_id=evidence.provenance.get("loop_id"))


def process_event(session: Session, agent: WorkflowAgent, event: ClinicalEvent):
    """Run one event and persist the resulting trace and candidates."""
    runs_repo = DbAgentRunRepository(session)
    existing = runs_repo.get_for_trigger(event.event_id)
    if existing is not None:
        return existing

    agent.memory = WorkflowMemory()
    hydrate_memory(session, event, agent.memory)
    run = agent.handle_event(event, tool_registry=build_registry(session))

    intent_repo = ClinicalIntentRepository(session)
    loop_repo = LoopRepository(session)
    for intent in agent.memory.intents.values():
        if intent.patient_id == event.patient_id:
            intent_repo.add(intent)
    for loop in agent.memory.loops.values():
        if loop.patient_id == event.patient_id:
            loop_repo.upsert(loop)

    finding_repo = FindingRepository(session)
    finding_ids: list[str] = []
    for finding_id in run.finding_ids:
        finding = agent.findings.get(finding_id)
        if finding is None or finding.patient_id != event.patient_id:
            continue
        finding_repo.add(finding)
        finding_ids.append(finding.finding_id)

    persisted = run.model_copy(update={"finding_ids": finding_ids})
    runs_repo.create(persisted)
    AuditRepository(session).append(
        entity_type="agent_run",
        entity_id=persisted.run_id,
        action="run",
        actor=WORKER_ACTOR,
        source_run_id=persisted.run_id,
        payload={
            "patient_id": event.patient_id,
            "trigger_event_id": event.event_id,
            "finding_ids": finding_ids,
            "stop_reason": persisted.stop_reason.value if persisted.stop_reason else None,
            "trace_metadata": persisted.trace_metadata,
        },
    )
    return persisted
