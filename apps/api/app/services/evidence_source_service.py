"""Resolve evidence to its original event without guessing across source scopes."""

from sqlalchemy.orm import Session

from apps.api.app.db_models import Encounter
from apps.api.app.repositories import ClinicalEventRepository
from packages.contracts import ClinicalEvent, EventType, EvidenceNode

_SOURCE_EVENT_TYPES = {
    "NOTES": {EventType.NOTE_CREATED, EventType.PROGRESS_NOTE_CREATED},
    "PROGRESS_NOTES": {EventType.PROGRESS_NOTE_CREATED},
    "ORDERS": {EventType.ORDER_UPDATED},
    "LABS": {EventType.LAB_RESULT_CREATED},
    "CONSULTS": {EventType.CONSULT_NOTE_CREATED},
    "HANDOFF": {EventType.HANDOFF_STARTED},
    "PATIENT": {EventType.PATIENT_EVIDENCE_SUBMITTED},
}


def resolve_source_event(session: Session, node: EvidenceNode) -> ClinicalEvent | None:
    """An explicit pointer is authoritative; an invalid one never falls back."""
    repository = ClinicalEventRepository(session)

    def matches(event: ClinicalEvent) -> bool:
        return (
            event.patient_id == node.patient_id
            and (node.encounter_id is None or event.encounter_id == node.encounter_id)
            and event.event_type in _SOURCE_EVENT_TYPES.get(node.source_type, set())
            and node.source_id in {event.payload_ref, event.event_id}
        )

    if "event_id" in node.provenance:
        event_id = node.provenance["event_id"]
        if not isinstance(event_id, str) or not event_id.strip():
            return None
        event = repository.get(event_id)
        return event if event is not None and matches(event) else None

    candidates = [event for event in repository.list_for_patient(node.patient_id) if matches(event)]
    return candidates[0] if len(candidates) == 1 else None


def evidence_encounter_id(session: Session, node: EvidenceNode) -> str | None:
    """Recover legacy seed ownership from the original event, never from patient alone."""
    encounter_id = node.encounter_id
    if encounter_id is None or "event_id" in node.provenance:
        event = resolve_source_event(session, node)
        if event is None:
            return None
        encounter_id = event.encounter_id
    encounter = session.get(Encounter, encounter_id)
    if encounter is None or encounter.patient_id != node.patient_id:
        return None
    return encounter_id
