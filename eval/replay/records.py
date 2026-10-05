"""Derive observable provenance from source records, never from gold evidence."""

from packages.contracts import ClinicalEvent, EventType, EvidenceNode, TrustLevel

SOURCES = {
    EventType.NOTE_CREATED: "NOTES",
    EventType.ORDER_UPDATED: "ORDERS",
    EventType.LAB_RESULT_CREATED: "LABS",
    EventType.CONSULT_NOTE_CREATED: "CONSULTS",
    EventType.PROGRESS_NOTE_CREATED: "PROGRESS_NOTES",
    EventType.HANDOFF_STARTED: "HANDOFF",
    EventType.PATIENT_EVIDENCE_SUBMITTED: "PATIENT",
}


def observable_evidence(event: ClinicalEvent) -> EvidenceNode:
    return EvidenceNode(
        evidence_id=event.payload_ref,
        patient_id=event.patient_id,
        encounter_id=event.encounter_id,
        source_type=SOURCES[event.event_type],
        source_id=event.payload_ref,
        observed_at=event.event_time,
        claim=event.payload.get("text") or "Synthetic source record",
        provenance={
            "event_id": event.event_id,
            "item_id": event.payload.get("item_id"),
            "stage": event.payload.get("stage"),
        },
        trust_level=TrustLevel.PATIENT_REPORTED
        if event.event_type == EventType.PATIENT_EVIDENCE_SUBMITTED
        else TrustLevel.SYSTEM_VERIFIED,
        created_at=event.source_time,
    )
