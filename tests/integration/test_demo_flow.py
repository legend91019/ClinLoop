from __future__ import annotations

from pathlib import Path

from apps.api.app.db import build_engine, create_schema, session_scope
from apps.api.app.db_models import AuditLogRow, OpenLoopRow
from apps.api.app.repositories import (
    ClinicalIntentRepository,
    FindingRepository,
    HandoffRepository,
    LoopRepository,
)
from packages.contracts import LoopState
from packages.fixtures.seed import FIXTURE_FINDING_ID, seed_demo_case
from scripts.run_demo import run_demo


def _engine(tmp_path: Path):
    return build_engine(f"sqlite+pysqlite:///{(tmp_path / 'demo.sqlite3').as_posix()}")


def test_demo_flow_keeps_gap_open_until_review_then_seals(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    create_schema(engine)
    with session_scope(engine) as session:
        seed_demo_case(session)

    result = run_demo("P-1001", engine=engine, auto_review=False)

    assert [item["event_id"] for item in result["events"]] == [
        "EVT-1001",
        "EVT-1002",
        "EVT-1003",
        "EVT-1004",
    ]
    assert result["final_action"] == "DRAFT_PENDING_REVIEW"
    assert "LOOP-1002" in result["loop_ids"]
    assert any("LAB-8821" in item["supporting_evidence"] for item in result["findings"])

    with session_scope(engine) as session:
        loops = LoopRepository(session).list_for_patient("P-1001")
        intents = ClinicalIntentRepository(session).list_for_patient("P-1001")
        assert any(intent.intent_type.value == "FOLLOW_RESULT" for intent in intents)
        assert all(loop.state is not LoopState.RESOLVED for loop in loops)
        assert session.query(OpenLoopRow).filter_by(loop_id="LOOP-1002").one().state == (
            LoopState.WAITING_EVENT.value
        )
        assert FindingRepository(session).get(FIXTURE_FINDING_ID).review_status == "PENDING_REVIEW"

    reviewed = run_demo("P-1001", engine=engine, auto_review=True)

    assert reviewed["final_action"] == "SEALED_AFTER_REVIEW"
    assert reviewed["handoff_id"]
    with session_scope(engine) as session:
        handoff = HandoffRepository(session).get(reviewed["handoff_id"])
        assert handoff is not None
        assert handoff.status.value == "SEALED"
        actions = session.query(AuditLogRow.action).all()
        assert {action for (action,) in actions} >= {"run", "review", "seal"}


def test_demo_rejects_unknown_patient(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    create_schema(engine)
    with session_scope(engine) as session:
        seed_demo_case(session)

    try:
        run_demo("P-404", engine=engine)
    except ValueError as exc:
        assert "unknown demo patient" in str(exc)
    else:  # pragma: no cover - keeps the assertion explicit for the CLI contract
        raise AssertionError("unknown patients must fail before publishing events")
