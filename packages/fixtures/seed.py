"""Seed script for the synthetic demo case.

Run with::

    python -m packages.fixtures.seed

Idempotency contract (task 3): running this twice must not create a
second patient, a second event or a second loop. Every identifier is a
fixed literal and every insert is guarded by an existence check, so the
seed is safe to call from ``make reset-db``, tests and CI alike.

The seed writes **only synthetic data** — see
:mod:`packages.fixtures.cases`.
"""

from __future__ import annotations

import sys
from datetime import timedelta

from sqlalchemy.orm import Session

from apps.api.app.db import build_engine, session_scope
from apps.api.app.repositories import (
    AuditRepository,
    ClinicalEventRepository,
    ClinicalIntentRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
    PatientRepository,
)
from packages.contracts import (
    ActorRef,
    ClinicalIntent,
    EventType,
    EvidenceNode,
    Finding,
    FindingType,
    IntentType,
    LoopState,
    OpenLoop,
    TrustLevel,
)
from packages.fixtures.cases import MAIN_CASE, at
from packages.fixtures.events import events_for_case

__all__ = [
    "seed_demo_case",
    "seed_demo_case_row_counts",
    "seed_all",
    "FIXTURE_INTENT_ID",
    "FIXTURE_LOOP_CULTURE_ID",
    "FIXTURE_EVIDENCE_CULTURE_ID",
    "FIXTURE_FINDING_ID",
]

# Fixed identifiers — never generated, so re-seeding is a no-op.
FIXTURE_INTENT_ID = "INT-1001"
FIXTURE_LOOP_CULTURE_ID = "LOOP-1001"
FIXTURE_LOOP_SUSCEPTIBILITY_ID = "LOOP-1002"
FIXTURE_EVIDENCE_NOTE_ID = "EVD-1001"
FIXTURE_EVIDENCE_CULTURE_ID = "EVD-1002"
FIXTURE_EVIDENCE_PROGRESS_ID = "EVD-1003"
FIXTURE_FINDING_ID = "FND-1001"

_SYSTEM_ACTOR = ActorRef(actor_id="SYS-SEED", role="SYSTEM", display_name="Fixture Seeder")


def seed_demo_case(session: Session) -> None:
    """Load the ``CASE-BLOOD-CULTURE`` scenario into ``session``.

    Idempotent: every write is guarded, so a second call changes nothing.
    """
    case = MAIN_CASE

    # --- patient / encounter ----------------------------------------------
    PatientRepository(session).ensure(
        patient_id=case.patient_id,
        encounter_id=case.encounter_id,
        display_name=case.display_name,
        ward=case.ward,
    )

    # --- events ------------------------------------------------------------
    event_repo = ClinicalEventRepository(session)
    for event in events_for_case(case):
        if not event_repo.exists(event.event_id):
            event_repo.add(event)

    # --- intent ------------------------------------------------------------
    intent = ClinicalIntent(
        intent_id=FIXTURE_INTENT_ID,
        patient_id=case.patient_id,
        encounter_id=case.encounter_id,
        intent_type=IntentType.FOLLOW_RESULT,
        text="今天复查血培养，结果出来后再决定下一步。",
        expected_evidence=["blood_culture_result"],
        source_event_id="EVT-1001",
        requires_clinician_review=False,
    )
    ClinicalIntentRepository(session).add(intent)

    # --- open loops --------------------------------------------------------
    loop_repo = LoopRepository(session)

    # Loop 1: the original follow-up. Still WAITING_EVENT at the handoff
    # because the positive result was never acknowledged within the window.
    loop_repo.add(
        OpenLoop(
            loop_id=FIXTURE_LOOP_CULTURE_ID,
            patient_id=case.patient_id,
            encounter_id=case.encounter_id,
            intent_id=FIXTURE_INTENT_ID,
            goal="Follow up the repeat blood culture result",
            state=LoopState.RESULT_AVAILABLE,
            priority="HIGH",
            confidence=0.9,
            last_plan="Query labs for the blood culture result and bind it to this loop.",
            last_planned_at=at(14, 35),
        )
    )

    # Loop 2: the re-planned dependency created when the doctor confirmed
    # the positive result and asked to wait for susceptibility.
    loop_repo.add(
        OpenLoop(
            loop_id=FIXTURE_LOOP_SUSCEPTIBILITY_ID,
            patient_id=case.patient_id,
            encounter_id=case.encounter_id,
            intent_id=FIXTURE_INTENT_ID,
            goal="Await antimicrobial susceptibility result",
            state=LoopState.WAITING_EVENT,
            waiting_for=[EventType.LAB_RESULT_CREATED],
            depends_on=[FIXTURE_LOOP_CULTURE_ID],
            priority="HIGH",
            confidence=0.85,
            last_plan="Wait for the susceptibility panel before any plan change.",
            last_planned_at=at(18, 2),
            next_check_at=at(18, 2) + timedelta(hours=12),
        )
    )

    # --- evidence ----------------------------------------------------------
    evidence_repo = EvidenceRepository(session)
    evidence_repo.append(
        EvidenceNode(
            evidence_id=FIXTURE_EVIDENCE_NOTE_ID,
            patient_id=case.patient_id,
            source_type="NOTES",
            source_id="NOTE-5001",
            observed_at=at(9, 10),
            claim="Ward round documented a plan to repeat the blood culture.",
            trust_level=TrustLevel.SYSTEM_VERIFIED,
            provenance={"event_id": "EVT-1001"},
        ),
        loop_id=FIXTURE_LOOP_CULTURE_ID,
    )
    evidence_repo.append(
        EvidenceNode(
            evidence_id=FIXTURE_EVIDENCE_CULTURE_ID,
            patient_id=case.patient_id,
            source_type="LABS",
            source_id="LAB-8821",
            observed_at=at(14, 30),
            claim="Blood culture returned POSITIVE (synthetic Gram-positive cocci).",
            trust_level=TrustLevel.SYSTEM_VERIFIED,
            provenance={"event_id": "EVT-1002", "critical": True},
        ),
        loop_id=FIXTURE_LOOP_CULTURE_ID,
    )
    evidence_repo.append(
        EvidenceNode(
            evidence_id=FIXTURE_EVIDENCE_PROGRESS_ID,
            patient_id=case.patient_id,
            source_type="NOTES",
            source_id="NOTE-5002",
            observed_at=at(18, 0),
            claim="Clinician confirmed the positive culture and is awaiting susceptibility.",
            trust_level=TrustLevel.CLINICIAN_CONFIRMED,
            provenance={"event_id": "EVT-1003", "acknowledges": "EVT-1002"},
        ),
        loop_id=FIXTURE_LOOP_SUSCEPTIBILITY_ID,
    )

    # --- the canonical finding for this case -------------------------------
    FindingRepository(session).add(
        Finding(
            finding_id=FIXTURE_FINDING_ID,
            patient_id=case.patient_id,
            loop_id=FIXTURE_LOOP_CULTURE_ID,
            intent_id=FIXTURE_INTENT_ID,
            finding_type=FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
            claim=(
                "The positive blood culture result was available at 14:30 but no "
                "acknowledgement was recorded before the 20:00 handoff."
            ),
            supporting_evidence=[FIXTURE_EVIDENCE_CULTURE_ID],
            searched_sources=["LABS", "NOTES", "PROGRESS_NOTES", "ORDERS"],
            confidence=0.92,
            requires_review=True,
            review_status="PENDING_REVIEW",
        )
    )

    AuditRepository(session).append(
        entity_type="patient",
        entity_id=case.patient_id,
        action="seed_fixture",
        actor=_SYSTEM_ACTOR,
        reason="loaded synthetic demo case CASE-BLOOD-CULTURE",
        payload={"patient_id": case.patient_id, "case_id": case.case_id},
    )

    session.flush()


def seed_demo_case_row_counts(session: Session) -> dict[str, int]:
    """Row counts for the demo case, used by idempotency tests."""
    from sqlalchemy import func, select

    from apps.api.app.db_models import (
        ClinicalEventRow,
        EvidenceNodeRow,
        FindingRow,
        OpenLoopRow,
        Patient,
    )

    counts: dict[str, int] = {}
    for name, column in (
        ("patients", Patient.patient_id),
        ("clinical_events", ClinicalEventRow.event_id),
        ("open_loops", OpenLoopRow.loop_id),
        ("evidence_nodes", EvidenceNodeRow.evidence_id),
        ("findings", FindingRow.finding_id),
    ):
        counts[name] = int(session.scalar(select(func.count(column))) or 0)
    return counts


def seed_all(engine=None) -> None:  # type: ignore[no-untyped-def]
    """Seed every known fixture case inside one transaction."""
    with session_scope(engine) as session:
        seed_demo_case(session)


def main() -> int:
    """CLI entry point: ``python -m packages.fixtures.seed``."""
    engine = build_engine()
    dialect = "postgresql" if str(engine.url).startswith("postgresql") else "sqlite"
    print(f"[seed] target: {dialect}")
    with session_scope(engine) as session:
        seed_demo_case(session)
        counts = seed_demo_case_row_counts(session)
    print(f"[seed] case={MAIN_CASE.case_id} patient={MAIN_CASE.patient_id}")
    for table, count in counts.items():
        print(f"[seed]   {table}: {count}")
    print("[seed] synthetic data only — no real patient information.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
