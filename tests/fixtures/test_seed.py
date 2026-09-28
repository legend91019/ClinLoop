"""Seed and fixture tests (Task 3).

Acceptance criteria from the plan:

* the demo case contains ``NOTE_CREATED``, ``LAB_RESULT_CREATED``,
  ``PROGRESS_NOTE_CREATED`` and ``HANDOFF_STARTED``
* the expected gap is ``RESULT_WITHOUT_ACKNOWLEDGEMENT``
* re-seeding produces no duplicate ids
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from apps.api.app.db import build_engine, session_factory
from apps.api.app.repositories import (
    ClinicalEventRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
    PatientRepository,
)
from apps.api.app.testing import create_schema, drop_schema
from packages.contracts import EventType, FindingType, LoopState
from packages.fixtures import (
    FIXTURE_EVIDENCE_CULTURE_ID,
    FIXTURE_FINDING_ID,
    FIXTURE_LOOP_CULTURE_ID,
    MAIN_CASE,
    MAIN_PATIENT_ID,
    TIMELINE,
    events_for_case,
    main_case_events,
    seed_demo_case,
    seed_demo_case_row_counts,
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = os.environ.get("CLINLOOP_TEST_DATABASE_URL") or (
        f"sqlite+pysqlite:///{(Path.cwd() / '.pytest-clinloop-seed.sqlite3').as_posix()}"
    )
    eng = build_engine(url)
    drop_schema(eng)
    create_schema(eng)
    try:
        yield eng
    finally:
        drop_schema(eng)
        eng.dispose()


@pytest.fixture
def session(engine: Engine):  # type: ignore[no-untyped-def]
    factory = session_factory(engine)
    with factory() as sess:
        sess.begin_nested()
        yield sess
        sess.rollback()


# --------------------------------------------------------------------------
# Fixture shape
# --------------------------------------------------------------------------


def test_demo_case_declares_the_four_required_event_types() -> None:
    types = {beat.event_type for beat in MAIN_CASE.timeline}
    assert {
        "NOTE_CREATED",
        "LAB_RESULT_CREATED",
        "PROGRESS_NOTE_CREATED",
        "HANDOFF_STARTED",
    } <= types


def test_demo_case_expected_gap_is_result_without_acknowledgement() -> None:
    assert MAIN_CASE.expected.primary_gap == "RESULT_WITHOUT_ACKNOWLEDGEMENT"
    assert FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT.value == "RESULT_WITHOUT_ACKNOWLEDGEMENT"


def test_demo_case_anchors_the_gap_to_the_lab_result() -> None:
    assert MAIN_CASE.expected.anchor_evidence_source_id == "LAB-8821"


def test_timeline_follows_the_narrative_order() -> None:
    times = [beat.event_time for beat in MAIN_CASE.timeline]
    assert times == sorted(times)
    assert MAIN_CASE.timeline[0].event_time.hour == 9
    assert MAIN_CASE.timeline[1].event_time.hour == 14
    assert MAIN_CASE.timeline[2].event_time.hour == 18
    assert MAIN_CASE.timeline[3].event_time.hour == 20


def test_every_fixture_timestamp_is_timezone_aware() -> None:
    for beat in TIMELINE:
        assert beat.event_time.tzinfo is not None
        assert beat.source_time.tzinfo is not None


def test_fixture_ids_are_fixed_literals_not_generated() -> None:
    """Reproducibility depends on deterministic ids."""
    for beat in TIMELINE:
        assert beat.event_id.startswith("EVT-")
        uuid_like = len(beat.event_id.split("-")[-1]) == 12
        assert not uuid_like, f"{beat.event_id} looks generated, not fixed"


def test_events_for_case_is_ordered_and_complete() -> None:
    events = events_for_case(MAIN_CASE)
    assert [e.event_id for e in events] == [b.event_id for b in MAIN_CASE.timeline]
    assert all(e.patient_id == MAIN_PATIENT_ID for e in events)


def test_main_case_events_are_ingestible_contracts() -> None:
    events = main_case_events()
    assert len(events) == 4
    assert events[0].event_type is EventType.NOTE_CREATED


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------


def test_seed_loads_the_demo_case(session) -> None:  # type: ignore[no-untyped-def]
    seed_demo_case(session)
    session.flush()

    assert PatientRepository(session).exists(MAIN_PATIENT_ID)

    events = ClinicalEventRepository(session).list_for_patient(MAIN_PATIENT_ID)
    assert len(events) == 4
    assert [e.event_type for e in events] == [
        EventType.NOTE_CREATED,
        EventType.LAB_RESULT_CREATED,
        EventType.PROGRESS_NOTE_CREATED,
        EventType.HANDOFF_STARTED,
    ]


def test_seed_creates_the_canonical_finding_with_evidence_and_searched_sources(
    session,  # type: ignore[no-untyped-def]
) -> None:
    seed_demo_case(session)
    session.flush()

    finding = FindingRepository(session).get(FIXTURE_FINDING_ID)
    assert finding is not None
    assert finding.finding_type is FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT
    assert FIXTURE_EVIDENCE_CULTURE_ID in finding.supporting_evidence
    assert set(finding.searched_sources) >= {"LABS", "NOTES", "PROGRESS_NOTES"}
    assert finding.requires_review is True


def test_seed_finding_points_back_at_the_raw_lab_record(session) -> None:  # type: ignore[no-untyped-def]
    """The console must be able to jump from the finding to LAB-8821."""
    seed_demo_case(session)
    session.flush()

    evidence = EvidenceRepository(session).get(FIXTURE_EVIDENCE_CULTURE_ID)
    assert evidence is not None
    assert evidence.source_id == "LAB-8821"
    assert evidence.source_type == "LABS"


def test_seed_creates_two_loops_one_of_which_waits_for_a_lab(session) -> None:  # type: ignore[no-untyped-def]
    seed_demo_case(session)
    session.flush()

    loops = LoopRepository(session).list_for_patient(MAIN_PATIENT_ID)
    assert len(loops) == 2

    by_id = {loop.loop_id: loop for loop in loops}
    assert by_id[FIXTURE_LOOP_CULTURE_ID].state is LoopState.RESULT_AVAILABLE

    waiting = [loop for loop in loops if loop.state is LoopState.WAITING_EVENT]
    assert len(waiting) == 1
    assert EventType.LAB_RESULT_CREATED in waiting[0].waiting_for
    assert waiting[0].depends_on == [FIXTURE_LOOP_CULTURE_ID]


def test_seed_keeps_everything_open_for_clinician_review(session) -> None:  # type: ignore[no-untyped-def]
    """Nothing is auto-resolved: the spec forbids closing high-risk work."""
    seed_demo_case(session)
    session.flush()

    for loop in LoopRepository(session).list_for_patient(MAIN_PATIENT_ID):
        assert loop.state is not LoopState.RESOLVED
        assert loop.state is not LoopState.CANCELLED


def test_reseeding_does_not_duplicate_anything(session) -> None:  # type: ignore[no-untyped-def]
    seed_demo_case(session)
    session.flush()
    first = seed_demo_case_row_counts(session)

    seed_demo_case(session)
    session.flush()
    second = seed_demo_case_row_counts(session)

    assert first == second
    assert first["patients"] == 1
    assert first["clinical_events"] == 4
    assert first["open_loops"] == 2
    assert first["evidence_nodes"] == 3
    assert first["findings"] == 1


def test_seed_writes_an_audit_entry(session) -> None:  # type: ignore[no-untyped-def]
    from apps.api.app.repositories import AuditRepository

    seed_demo_case(session)
    session.flush()

    entries = AuditRepository(session).list_for_entity("patient", MAIN_PATIENT_ID)
    assert [entry.action for entry in entries] == ["seed_fixture"]


def test_seed_marks_the_patient_as_synthetic(session) -> None:  # type: ignore[no-untyped-def]
    """A safety property: fixtures must never masquerade as real data."""
    from apps.api.app.db_models import Patient as PatientRow

    seed_demo_case(session)
    session.flush()

    row = session.get(PatientRow, MAIN_PATIENT_ID)
    assert row is not None
    assert row.synthetic is True


def test_no_patient_reported_evidence_is_promoted_in_the_seed(session) -> None:  # type: ignore[no-untyped-def]
    from packages.contracts import TrustLevel

    seed_demo_case(session)
    session.flush()

    for node in EvidenceRepository(session).list_for_patient(MAIN_PATIENT_ID):
        if node.trust_level is TrustLevel.PATIENT_REPORTED:
            assert node.verified_at is None
