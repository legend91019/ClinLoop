"""Build :class:`ClinicalEvent` contracts from fixture timeline beats.

Deterministic event ids (``EVT-1001``, ``EVT-1002``, ...) are what make
the demo and the evaluation replay reproducible. They are fixed literals,
never random.
"""

from __future__ import annotations

from packages.contracts import ActorRef, ClinicalEvent, EventType
from packages.fixtures.cases import TIMELINE, CaseDefinition, TimelineBeat, case_by_id

__all__ = [
    "build_event",
    "events_for_case",
    "events_for_patient",
    "main_case_events",
]


def build_event(beat: TimelineBeat, *, case: CaseDefinition) -> ClinicalEvent:
    """Convert one scripted beat into an ingestible event contract."""
    return ClinicalEvent(
        event_id=beat.event_id,
        patient_id=case.patient_id,
        encounter_id=case.encounter_id,
        event_type=EventType(beat.event_type),
        event_time=beat.event_time,
        source_time=beat.source_time,
        payload_ref=beat.payload_ref,
        actor=ActorRef(
            actor_id=beat.actor_id,
            role=beat.actor_role,
            display_name=beat.actor_name,
        ),
        payload=dict(beat.payload),
    )


def events_for_case(case: CaseDefinition) -> list[ClinicalEvent]:
    """Every event of a case, in timeline order."""
    ordered = sorted(case.timeline, key=lambda beat: (beat.event_time, beat.event_id))
    return [build_event(beat, case=case) for beat in ordered]


def events_for_patient(patient_id: str) -> list[ClinicalEvent]:
    """Events for a patient id, resolving the case that owns it."""
    for case in (case_by_id("CASE-BLOOD-CULTURE"),):
        if case.patient_id == patient_id:
            return events_for_case(case)
    return []


def main_case_events() -> list[ClinicalEvent]:
    """The canonical demo trajectory."""
    from packages.fixtures.cases import MAIN_CASE

    return events_for_case(MAIN_CASE)


def timeline_beat_by_key(key: str) -> TimelineBeat:
    """Look up a scripted beat by its semantic key."""
    for beat in TIMELINE:
        if beat.key == key:
            return beat
    raise KeyError(f"unknown timeline beat: {key}")
