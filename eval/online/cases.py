"""Small synthetic corpus for the online result-follow-up workflow."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import ClinicalEvent
from packages.fixtures import main_case_events


@dataclass(frozen=True)
class OnlineCase:
    case_id: str
    cohort: str
    patient_id: str
    expected_alert: bool
    events: tuple[ClinicalEvent, ...]


def online_cases() -> list[OnlineCase]:
    """Return labeled cases; labels are never copied into event payloads."""
    note, lab, *_ = main_case_events()
    definitions = (
        ("direct_zh", "今天复查血培养，结果出来后通知我。", "BLOOD_CULTURE", True),
        ("paraphrase_zh", "血培结果回报后请复核。", "BLOOD_CULTURE", True),
        ("direct_en", "Follow the blood culture result when it arrives.", "BLOOD_CULTURE", True),
        ("unrelated_note", "查房记录：继续观察体温，暂无化验随访计划。", "BLOOD_CULTURE", False),
        ("unrelated_lab", "今天复查血培养，结果出来后通知我。", "METABOLIC_PANEL", False),
        ("no_note", None, "BLOOD_CULTURE", False),
    )
    cases = []
    for index, (cohort, text, panel, expected_alert) in enumerate(definitions, start=1):
        case_id = f"CASE-{index:03d}"
        suffix = f"ONLINE-{index:03d}"
        events = []
        if text is not None:
            events.append(
                note.model_copy(
                    update={
                        "event_id": f"EVT-{suffix}-NOTE",
                        "payload_ref": f"NOTE-{suffix}",
                        "payload": {"note_type": "PROGRESS_NOTE", "text": text, "priority": "HIGH"},
                        "ingested_at": note.source_time,
                    }
                )
            )
        events.append(
            lab.model_copy(
                update={
                    "event_id": f"EVT-{suffix}-LAB",
                    "payload_ref": f"LAB-{suffix}",
                    "payload": {**lab.payload, "panel": panel},
                    "ingested_at": lab.source_time,
                }
            )
        )
        cases.append(
            OnlineCase(
                case_id=case_id,
                cohort=cohort,
                patient_id=note.patient_id,
                expected_alert=expected_alert,
                events=tuple(events),
            )
        )
    return cases
