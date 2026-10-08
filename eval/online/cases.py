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


# Frozen, authored phrases. Keep labels here, never in ClinicalEvent payloads.
_FOLLOWUP_NOTES = (
    "血培养结果出来以后请通知我。",
    "请追踪今天送检的血培养回报。",
    "复查血培养，结果回报后复核。",
    "今天抽血培，报告出来提醒值班医师。",
    "血培尚在处理中，出结果后请确认。",
    "待血培养报告返回时联系主管医生。",
    "请在血培养完成后查看报告并记录处理。",
    "血培养送检后，需持续跟进检验结果。",
    "夜班请查看血培回报是否已收到。",
    "留意今日血培养结果，回报后复核。",
    "血培结果若已发布，请通知接班团队核对。",
    "请追踪血培养最终报告并完成回看。",
    "Follow up the blood culture result when available.",
    "Please review the pending blood culture report.",
    "Notify the team after blood cultures are reported.",
    "Blood culture is pending; check the final result.",
    "Track the blood culture report and confirm receipt.",
    "Please check today's culture result once posted.",
    "The blood culture needs a follow-up review.",
    "When the blood culture is back, alert the covering clinician.",
    "Keep this blood culture result on the follow-up list.",
    "Review the culture report after the lab releases it.",
    "Document acknowledgement of the blood culture result.",
    "Blood culture sent today; follow its result overnight.",
    "Pending blood culture: ensure the result is reviewed.",
)

_UNRELATED_NOTES = (
    "查房记录：继续观察体温。",
    "患者今日饮食尚可，继续常规观察。",
    "请记录本班生命体征变化。",
    "今日讨论出院宣教安排。",
    "夜班关注睡眠情况。",
    "继续观察疼痛评分。",
    "已经向家属说明明日查房时间。",
    "补充护理记录，暂无新增检验随访任务。",
    "Continue routine vital sign monitoring.",
    "Discuss discharge education with the family.",
    "Record oral intake during the next shift.",
    "Observe the patient's comfort overnight.",
)


def contest_cases() -> list[OnlineCase]:
    """50 fixed synthetic result-follow-up cases; no gold field enters Worker input."""
    note, lab, *_ = main_case_events()
    definitions: list[tuple[str, str | None, str, bool]] = [
        ("followup", phrase, "BLOOD_CULTURE", True) for phrase in _FOLLOWUP_NOTES
    ]
    definitions.extend(
        ("unrelated_note", phrase, "BLOOD_CULTURE", False) for phrase in _UNRELATED_NOTES
    )
    definitions.extend(
        ("other_lab", phrase, "METABOLIC_PANEL", False) for phrase in _FOLLOWUP_NOTES[:12]
    )
    definitions.append(("no_note", None, "BLOOD_CULTURE", False))
    cases: list[OnlineCase] = []
    for index, (cohort, text, panel, label) in enumerate(definitions, start=1):
        suffix = f"CONTEST-{index:03d}"
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
                case_id=f"CONTEST-{index:03d}",
                cohort=cohort,
                patient_id=note.patient_id,
                expected_alert=label,
                events=tuple(events),
            )
        )
    return cases
