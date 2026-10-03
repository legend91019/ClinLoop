from __future__ import annotations

from packages.contracts import ClinicalEvent, EventType


def plan_for_event(event: ClinicalEvent) -> list[str]:
    if event.event_type is EventType.NOTE_CREATED:
        return ["extract_clinical_intent", "create_follow_result_loop", "wait_for_result"]
    if event.event_type is EventType.LAB_RESULT_CREATED:
        return ["get_labs", "verify_workflow_continuity", "record_finding"]
    if event.event_type is EventType.PROGRESS_NOTE_CREATED:
        return ["match_intent_to_execution", "create_dependency_loop", "wait_for_next_result"]
    if event.event_type is EventType.HANDOFF_STARTED:
        return ["verify_workflow_continuity", "draft_handoff"]
    return ["observe_event", "verify_workflow_continuity"]
