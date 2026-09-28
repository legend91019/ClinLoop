"""Synthetic case definitions.

**All data in this module is fabricated.** There is no real patient, no
real hospital and no real clinician. The main demo case is
``CASE-BLOOD-CULTURE`` / patient ``P-1001``.

Clinical narrative (see the plan, task 3):

    09:10  Ward round: repeat the blood culture, decide next steps
           once the result is back.            -> NOTE_CREATED
    14:30  Blood culture comes back positive.  -> LAB_RESULT_CREATED
           ...no acknowledgement...
    18:00  Doctor confirms the result and waits for susceptibility.
                                                -> PROGRESS_NOTE_CREATED
    20:00  Night shift handoff.                -> HANDOFF_STARTED

The expected workflow gap on this trajectory is
``RESULT_WITHOUT_ACKNOWLEDGEMENT``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

__all__ = [
    "CasDefinition",
    "CaseDefinition",
    "MAIN_CASE_ID",
    "MAIN_PATIENT_ID",
    "MAIN_ENCOUNTER_ID",
    "MAIN_CASE",
    "DEMO_DAY",
    "TIMELINE",
    "case_by_id",
    "all_cases",
]

UTC = UTC

#: The synthetic demo day. Every fixture timestamp is anchored to this
#: date so that replayed runs are byte-for-byte reproducible.
DEMO_DAY = datetime(2026, 9, 28, 0, 0, tzinfo=UTC)

MAIN_CASE_ID = "CASE-BLOOD-CULTURE"
MAIN_PATIENT_ID = "P-1001"
MAIN_ENCOUNTER_ID = "ENC-2001"


def at(hour: int, minute: int, *, day_offset: int = 0) -> datetime:
    """A timezone-aware timestamp on the demo day."""
    return DEMO_DAY + timedelta(days=day_offset, hours=hour, minutes=minute)


@dataclass(frozen=True)
class TimelineBeat:
    """One scripted moment in the demo trajectory."""

    key: str
    event_id: str
    event_type: str
    event_time: datetime
    source_time: datetime
    payload_ref: str
    actor_id: str
    actor_role: str
    actor_name: str
    payload: dict[str, Any] = field(default_factory=dict)
    note: str = ""


#: The canonical demo trajectory, in narrative order.
TIMELINE: tuple[TimelineBeat, ...] = (
    TimelineBeat(
        key="ward_round_repeat_culture",
        event_id="EVT-1001",
        event_type="NOTE_CREATED",
        event_time=at(9, 10),
        source_time=at(9, 12),
        payload_ref="NOTE-5001",
        actor_id="DR-001",
        actor_role="PHYSICIAN",
        actor_name="Dr. Synth (fictional)",
        note="Morning round: repeat blood culture; decide next step on result.",
        payload={
            "note_type": "PROGRESS_NOTE",
            "text": "今天复查血培养，结果出来后再决定下一步。",
            "intent_hint": "FOLLOW_RESULT",
            "expected_evidence": ["blood_culture_result"],
            "priority": "HIGH",
        },
    ),
    TimelineBeat(
        key="culture_result_positive",
        event_id="EVT-1002",
        event_type="LAB_RESULT_CREATED",
        event_time=at(14, 30),
        source_time=at(14, 33),
        payload_ref="LAB-8821",
        actor_id="LAB-001",
        actor_role="LABORATORY",
        actor_name="Synthetic Lab System",
        note="Positive blood culture. Never acknowledged before the handoff.",
        payload={
            "panel": "BLOOD_CULTURE",
            "result": "POSITIVE",
            "organism": "Gram-positive cocci in clusters (synthetic)",
            "critical": True,
            "collected_at": at(9, 20).isoformat(),
            "specimen_id": "SPEC-3001",
        },
    ),
    TimelineBeat(
        key="clinician_acknowledges_and_awaits_susceptibility",
        event_id="EVT-1003",
        event_type="PROGRESS_NOTE_CREATED",
        event_time=at(18, 0),
        source_time=at(18, 4),
        payload_ref="NOTE-5002",
        actor_id="DR-001",
        actor_role="PHYSICIAN",
        actor_name="Dr. Synth (fictional)",
        note="Doctor confirms the positive culture and now waits for susceptibility.",
        payload={
            "note_type": "PROGRESS_NOTE",
            "text": "已确认血培养阳性，等待药敏结果后再调整方案。",
            "acknowledges_event_id": "EVT-1002",
            "creates_dependency": "susceptibility_result",
        },
    ),
    TimelineBeat(
        key="night_handoff",
        event_id="EVT-1004",
        event_type="HANDOFF_STARTED",
        event_time=at(20, 0),
        source_time=at(20, 1),
        payload_ref="HANDOFF-7001",
        actor_id="DR-001",
        actor_role="PHYSICIAN",
        actor_name="Dr. Synth (fictional)",
        note="Night shift handoff; the still-open susceptibility loop must appear.",
        payload={
            "shift": "NIGHT",
            "receiving_role": "PHYSICIAN",
            "text": "交班：血培养已确认阳性，药敏未回，需继续跟进。",
        },
    ),
)


@dataclass(frozen=True)
class ExpectedOutcome:
    """What the demo trajectory must produce. Asserted by the tests."""

    #: The gap the agent must surface for this case.
    primary_gap: str = "RESULT_WITHOUT_ACKNOWLEDGEMENT"

    #: The evidence the gap must point back at.
    anchor_evidence_source_id: str = "LAB-8821"

    #: Loops that must exist by the end of the trajectory.
    expected_loop_goals: tuple[str, ...] = (
        "Follow up the repeat blood culture result",
        "Await antimicrobial susceptibility result",
    )

    #: Whether the final state must still be open (not auto-resolved).
    remains_open: bool = True


@dataclass(frozen=True)
class CasDefinition:  # noqa: N801 - kept as an alias for readability
    """Alias kept for callers that prefer the singular spelling."""


@dataclass(frozen=True)
class CaseDefinition:
    """A complete synthetic case: patients, intents, timeline, expectations."""

    case_id: str
    patient_id: str
    encounter_id: str
    display_name: str
    ward: str
    summary: str
    timeline: tuple[TimelineBeat, ...]
    expected: ExpectedOutcome = field(default_factory=ExpectedOutcome)

    @property
    def event_ids(self) -> tuple[str, ...]:
        return tuple(beat.event_id for beat in self.timeline)

    @property
    def event_types(self) -> tuple[str, ...]:
        return tuple(beat.event_type for beat in self.timeline)


MAIN_CASE = CaseDefinition(
    case_id=MAIN_CASE_ID,
    patient_id=MAIN_PATIENT_ID,
    encounter_id=MAIN_ENCOUNTER_ID,
    display_name="Synthetic Patient One",
    ward="SYNTH-WARD-A",
    summary=(
        "Ward round requests a repeat blood culture; the result returns positive "
        "and is never acknowledged before the night handoff."
    ),
    timeline=TIMELINE,
    expected=ExpectedOutcome(),
)


def all_cases() -> tuple[CaseDefinition, ...]:
    """Every synthetic case known to the fixtures package."""
    return (MAIN_CASE,)


def case_by_id(case_id: str) -> CaseDefinition:
    """Look up a case by id.

    Raises:
        KeyError: unknown case id.
    """
    for case in all_cases():
        if case.case_id == case_id:
            return case
    raise KeyError(f"unknown case_id: {case_id}")
