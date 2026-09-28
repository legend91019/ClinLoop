"""Schema and migration tests (Task 3).

Runs against whatever ``CLINLOOP_TEST_DATABASE_URL`` points at. When it is
unset the suite falls back to a scratch SQLite file so the foundation can
be verified without Docker; CI sets it to PostgreSQL 16.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, inspect, text

from apps.api.app.db import Base, build_engine, session_factory
from apps.api.app.repositories import (
    AuditRepository,
    ClinicalEventRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
    PatientRepository,
)
from apps.api.app.testing import create_schema, drop_schema
from packages.contracts import (
    ActorRef,
    ClinicalEvent,
    EventType,
    EvidenceNode,
    Finding,
    FindingType,
    LoopState,
    OpenLoop,
    TrustLevel,
    utcnow,
)
from packages.domain import validate_transition

EXPECTED_TABLES = {
    "patients",
    "encounters",
    "clinical_events",
    "clinical_intents",
    "open_loops",
    "evidence_nodes",
    "findings",
    "agent_runs",
    "review_decisions",
    "handoff_reports",
    "audit_logs",
}

T0 = utcnow()


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = os.environ.get("CLINLOOP_TEST_DATABASE_URL") or (
        f"sqlite+pysqlite:///{(Path.cwd() / '.pytest-clinloop.sqlite3').as_posix()}"
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
        yield sess


def actor() -> ActorRef:
    return ActorRef(actor_id="DR-001", role="PHYSICIAN", display_name="Dr. Synth")


# --------------------------------------------------------------------------
# Schema shape
# --------------------------------------------------------------------------


def test_all_eleven_core_tables_exist(engine: Engine) -> None:
    inspector = inspect(engine)
    present = set(inspector.get_table_names())
    missing = EXPECTED_TABLES - present
    assert not missing, f"missing tables: {sorted(missing)}"


@pytest.mark.parametrize("table", sorted(EXPECTED_TABLES))
def test_core_tables_carry_timestamps_and_payload(engine: Engine, table: str) -> None:
    columns = {c["name"] for c in inspect(engine).get_columns(table)}
    assert "created_at" in columns, f"{table}.created_at is required"
    assert "updated_at" in columns, f"{table}.updated_at is required"
    # Every core table keeps the original JSON payload for auditability.
    assert {"payload", "raw_payload"} & columns, f"{table} must keep a raw JSON payload"


def test_indexes_are_declared_for_the_hot_paths(engine: Engine) -> None:
    inspector = inspect(engine)
    index_names = {
        index["name"] for table in EXPECTED_TABLES for index in inspector.get_indexes(table)
    }
    for required in (
        "ix_clinical_events_patient_event_time",
        "ix_open_loops_patient_state",
        "ix_evidence_nodes_loop_observed_at",
        "ix_audit_logs_entity_time",
    ):
        assert required in index_names, f"missing index: {required}"


# --------------------------------------------------------------------------
# Repositories round-trip contracts through the database
# --------------------------------------------------------------------------


def test_event_round_trip_preserves_contract_fidelity(session) -> None:  # type: ignore[no-untyped-def]
    repo = ClinicalEventRepository(session)
    event = ClinicalEvent(
        event_id="EVT-RT-001",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        event_type=EventType.NOTE_CREATED,
        event_time=T0,
        source_time=T0,
        payload_ref="NOTE-5001",
        actor=actor(),
        payload={"text": "复查血培养"},
    )
    repo.add(event)
    session.commit()

    restored = repo.get("EVT-RT-001")
    assert restored is not None
    assert restored.event_type is EventType.NOTE_CREATED
    assert restored.event_time == event.event_time
    assert restored.actor.actor_id == "DR-001"
    assert restored.payload == {"text": "复查血培养"}


def test_duplicate_event_is_detected(session) -> None:  # type: ignore[no-untyped-def]
    repo = ClinicalEventRepository(session)
    event = ClinicalEvent(
        event_id="EVT-DUP-001",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        event_type=EventType.ORDER_UPDATED,
        event_time=T0,
        source_time=T0,
        payload_ref="ORD-7001",
        actor=actor(),
    )
    repo.add(event)
    session.commit()

    assert repo.exists("EVT-DUP-001") is True
    assert repo.exists("EVT-NEVER") is False


def test_loop_round_trip_and_state_query(session) -> None:  # type: ignore[no-untyped-def]
    patient_repo = PatientRepository(session)
    patient_repo.ensure(patient_id="P-1001", encounter_id="ENC-2001", display_name="Synth Patient")

    loop_repo = LoopRepository(session)
    loop = OpenLoop(
        loop_id="LOOP-RT-001",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        intent_id="INT-RT-001",
        goal="Follow up blood culture",
        state=LoopState.WAITING_EVENT,
        waiting_for=[EventType.LAB_RESULT_CREATED],
        priority="HIGH",
    )
    loop_repo.add(loop)
    session.commit()

    restored = loop_repo.get("LOOP-RT-001")
    assert restored is not None
    assert restored.state is LoopState.WAITING_EVENT
    assert restored.waiting_for == [EventType.LAB_RESULT_CREATED]

    active = loop_repo.list_for_patient("P-1001")
    assert [item.loop_id for item in active] == ["LOOP-RT-001"]


def test_evidence_round_trip_keeps_trust_level(session) -> None:  # type: ignore[no-untyped-def]
    repo = EvidenceRepository(session)
    node = EvidenceNode(
        evidence_id="EVD-RT-001",
        patient_id="P-1001",
        source_type="PATIENT",
        source_id="PAT-9001",
        observed_at=T0,
        claim="患者自述发热。",
        trust_level=TrustLevel.PATIENT_REPORTED,
    )
    repo.append(node, loop_id="LOOP-RT-001")
    session.commit()

    restored = repo.get("EVD-RT-001")
    assert restored is not None
    assert restored.trust_level is TrustLevel.PATIENT_REPORTED

    by_loop = repo.list_for_loop("LOOP-RT-001")
    assert [e.evidence_id for e in by_loop] == ["EVD-RT-001"]


def test_finding_round_trip_carries_searched_sources(session) -> None:  # type: ignore[no-untyped-def]
    repo = FindingRepository(session)
    finding = Finding(
        finding_id="FND-RT-001",
        patient_id="P-1001",
        loop_id="LOOP-RT-001",
        finding_type=FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
        claim="血培养阳性结果未确认。",
        supporting_evidence=["EVD-RT-001"],
        searched_sources=["LABS", "NOTES"],
        source_run_id="RUN-RT-001",
    )
    repo.add(finding)
    session.commit()

    restored = repo.get("FND-RT-001")
    assert restored is not None
    assert restored.searched_sources == ["LABS", "NOTES"]
    assert restored.supporting_evidence == ["EVD-RT-001"]


def test_audit_log_is_append_only_and_queryable_by_entity(session) -> None:  # type: ignore[no-untyped-def]
    repo = AuditRepository(session)
    repo.append(
        entity_type="open_loop",
        entity_id="LOOP-RT-001",
        action="state_transition",
        actor=actor(),
        old_state=LoopState.RESULT_AVAILABLE.value,
        new_state=LoopState.ACKNOWLEDGED.value,
        reason="clinician acknowledged the positive culture",
        source_run_id="RUN-RT-001",
    )
    session.commit()

    entries = repo.list_for_entity("open_loop", "LOOP-RT-001")
    assert len(entries) == 1
    assert entries[0].new_state == "ACKNOWLEDGED"
    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")


def test_state_machine_and_repository_agree_on_a_valid_transition(session) -> None:  # type: ignore[no-untyped-def]
    """The repository must refuse to persist a state the policy rejects."""
    loop_repo = LoopRepository(session)
    loop = OpenLoop(
        loop_id="LOOP-RT-002",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        intent_id="INT-RT-002",
        goal="Confirm the plan",
        state=LoopState.ACKNOWLEDGED,
    )
    loop_repo.add(loop)
    session.commit()

    decision = validate_transition(
        LoopState.ACKNOWLEDGED, LoopState.RESOLVED, evidence_ids=["EVD-RT-001"]
    )
    assert decision.allowed is False
    with pytest.raises(PermissionError):
        loop_repo.apply_transition(loop.loop_id, LoopState.RESOLVED, reviewer=None)


def test_apply_transition_writes_an_audit_entry(session) -> None:  # type: ignore[no-untyped-def]
    loop_repo = LoopRepository(session)
    loop = OpenLoop(
        loop_id="LOOP-RT-003",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        intent_id="INT-RT-003",
        goal="Order the repeat culture",
        state=LoopState.PLANNED,
    )
    loop_repo.add(loop)
    session.commit()

    loop_repo.apply_transition(loop.loop_id, LoopState.ORDERED, reviewer=actor())
    session.commit()

    updated = loop_repo.get("LOOP-RT-003")
    assert updated is not None
    assert updated.state is LoopState.ORDERED

    audit = AuditRepository(session).list_for_entity("open_loop", "LOOP-RT-003")
    assert [entry.new_state for entry in audit] == ["ORDERED"]


def test_session_factory_yields_usable_sessions(engine: Engine) -> None:
    factory = session_factory(engine)
    with factory() as sess:
        assert sess.execute(text("SELECT 1")).scalar() == 1


def test_base_metadata_is_exported() -> None:
    assert Base.metadata.tables
    assert EXPECTED_TABLES <= set(Base.metadata.tables)
