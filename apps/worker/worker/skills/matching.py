from __future__ import annotations

from packages.contracts import ClinicalEvent, IntentType


def match_intent_to_execution(intent, event: ClinicalEvent) -> bool:
    return (
        intent.intent_type is IntentType.FOLLOW_RESULT
        and event.event_type.value == "LAB_RESULT_CREATED"
    )
