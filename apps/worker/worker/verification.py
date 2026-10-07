"""Conservative matching and acknowledgement checks for result follow-up."""

from __future__ import annotations

from collections.abc import Iterable

from packages.contracts import ClinicalEvent, ClinicalIntent, EventType, LoopState, OpenLoop


def _tokens(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum()).removesuffix("result")


def match_result_loop(
    event: ClinicalEvent,
    loops: Iterable[OpenLoop],
    intents: dict[str, ClinicalIntent],
) -> OpenLoop | None:
    """Choose a single loop; ambiguous or unrelated results do not create a gap."""
    if event.event_type is not EventType.LAB_RESULT_CREATED:
        return None
    panel = _tokens(str(event.payload.get("panel", "")))
    if not panel:
        return None
    matches = []
    for loop in loops:
        intent = intents.get(loop.intent_id)
        if (
            loop.patient_id != event.patient_id
            or loop.encounter_id != event.encounter_id
            or loop.state is not LoopState.WAITING_EVENT
            or (loop.waiting_for and EventType.LAB_RESULT_CREATED not in loop.waiting_for)
            or intent is None
        ):
            continue
        if loop.depends_on and panel not in _tokens(loop.goal):
            continue
        if any(panel == _tokens(expected) for expected in intent.expected_evidence):
            matches.append(loop)
    return matches[0] if len(matches) == 1 else None


def has_explicit_ack(event: ClinicalEvent, records: Iterable[ClinicalEvent]) -> bool:
    """Only a linked clinician note visible at the result time counts as an acknowledgement."""
    for record in records:
        if (
            record.event_type is EventType.PROGRESS_NOTE_CREATED
            and record.patient_id == event.patient_id
            and record.encounter_id == event.encounter_id
            and record.payload.get("acknowledges_event_id") == event.event_id
            and record.source_time <= event.source_time
            and record.actor.role in {"PHYSICIAN", "CLINICIAN"}
        ):
            return True
    return False
