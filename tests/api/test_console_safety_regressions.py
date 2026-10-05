"""Isolated regressions for source ownership and concurrent handoff writes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.app.db import build_engine, get_session, session_factory
from apps.api.app.db_models import AuditLogRow, Encounter, FindingRow, HandoffReportRow, OpenLoopRow
from apps.api.app.main import create_app
from apps.api.app.repositories import ClinicalEventRepository, EvidenceRepository, FindingRepository
from apps.api.app.services.console_service import edit_handoff_draft
from apps.api.app.services.handoff_service import create_draft, seal_handoff
from apps.api.app.testing import create_schema
from packages.contracts import ActorRef, EventType, EvidenceNode, utcnow
from packages.contracts.console import HandoffDraftUpdate
from packages.fixtures import FIXTURE_FINDING_ID, seed_demo_case

ACTOR = ActorRef(actor_id="DR-REGRESSION", role="PHYSICIAN")


@pytest.fixture
def safety_db(tmp_path):
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'safety.db').as_posix()}")
    create_schema(engine)
    factory = session_factory(engine)
    try:
        with factory() as session:
            seed_demo_case(session)
            session.commit()
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def safety_client(safety_db):
    app = create_app()

    def isolated_session():
        with safety_db() as session:
            yield session

    app.dependency_overrides[get_session] = isolated_session
    # No lifespan is needed: every request uses the isolated seeded database.
    return TestClient(app)


def add_other_encounter(session, *, legacy=False):
    session.add(Encounter(encounter_id="ENC-OTHER", patient_id="P-1001", payload={}))
    session.add(
        OpenLoopRow(
            loop_id="LOOP-OTHER",
            patient_id="P-1001",
            encounter_id="ENC-OTHER",
            intent_id="INTENT-OTHER",
            goal="Other visit goal",
            state="ORDERED",
            priority="HIGH",
            payload={},
        )
    )
    original = ClinicalEventRepository(session).get("EVT-1002")
    ClinicalEventRepository(session).add(
        original.model_copy(
            update={
                "event_id": "EVT-OTHER",
                "encounter_id": "ENC-OTHER",
                "payload_ref": "LAB-OTHER",
            }
        )
    )
    EvidenceRepository(session).append(
        EvidenceNode(
            evidence_id="EVID-OTHER",
            patient_id="P-1001",
            encounter_id=None if legacy else "ENC-OTHER",
            source_type="LABS",
            source_id="LAB-OTHER",
            observed_at=utcnow(),
            claim="Other encounter evidence",
            provenance={"event_id": "EVT-OTHER"},
        ),
        loop_id="LOOP-OTHER",
    )
    original_finding = FindingRepository(session).get(FIXTURE_FINDING_ID)
    FindingRepository(session).add(
        original_finding.model_copy(
            update={
                "finding_id": "FIND-OTHER",
                "loop_id": "LOOP-OTHER",
                "intent_id": None,
                "claim": "Other encounter pending finding",
                "supporting_evidence": ["EVID-OTHER"],
            }
        )
    )
    session.commit()


@pytest.mark.parametrize("legacy", [False, True])
def test_draft_excludes_other_encounter_but_keeps_legacy_seed(safety_db, safety_client, legacy):
    with safety_db() as session:
        add_other_encounter(session, legacy=legacy)
    response = safety_client.post("/api/v1/patients/P-1001/handoff/draft")
    assert response.status_code == 200
    draft = response.json()
    assert "EVID-OTHER" not in draft["evidence_ids"]
    assert "Other encounter evidence" not in draft["background"]
    assert "LOOP-OTHER" not in draft["loop_ids"]
    assert not any("Other encounter pending finding" in item for item in draft["pending_items"])
    assert "Blood culture" in draft["background"]
    assert len(draft["evidence_ids"]) == 3
    with safety_db() as session:
        finding = FindingRepository(session).get(FIXTURE_FINDING_ID)
        assert any(finding.claim in item for item in draft["pending_items"])


def test_pending_finding_without_loop_uses_supporting_evidence_scope(safety_db, safety_client):
    with safety_db() as session:
        add_other_encounter(session, legacy=True)
        foreign = FindingRepository(session).get("FIND-OTHER")
        FindingRepository(session).add(
            foreign.model_copy(
                update={
                    "finding_id": "FIND-UNLINKED-OTHER",
                    "loop_id": None,
                    "claim": "Unlinked other visit",
                }
            )
        )
        session.commit()
    draft = safety_client.post("/api/v1/patients/P-1001/handoff/draft").json()
    assert not any("Unlinked other visit" in item for item in draft["pending_items"])


def test_seal_ignores_pending_findings_from_other_encounters(safety_db, safety_client):
    with safety_db() as session:
        add_other_encounter(session)
    assert (
        safety_client.post(
            f"/api/v1/findings/{FIXTURE_FINDING_ID}/review", json={"action": "ACCEPT"}
        ).status_code
        == 200
    )
    draft = safety_client.post("/api/v1/patients/P-1001/handoff/draft").json()
    assert safety_client.post(f"/api/v1/handoff/{draft['handoff_id']}/seal").status_code == 200


def test_seal_still_blocks_high_risk_finding_with_unresolved_ownership(safety_db, safety_client):
    with safety_db() as session:
        original = FindingRepository(session).get(FIXTURE_FINDING_ID)
        FindingRepository(session).add(
            original.model_copy(
                update={
                    "finding_id": "FIND-UNKNOWN-SCOPE",
                    "loop_id": None,
                    "intent_id": None,
                    "supporting_evidence": ["EVID-MISSING"],
                    "claim": "Ownership requires confirmation",
                }
            )
        )
        session.commit()
    assert (
        safety_client.post(
            f"/api/v1/findings/{FIXTURE_FINDING_ID}/review", json={"action": "ACCEPT"}
        ).status_code
        == 200
    )
    draft = safety_client.post("/api/v1/patients/P-1001/handoff/draft").json()
    assert not any("Ownership requires confirmation" in item for item in draft["pending_items"])
    assert safety_client.post(f"/api/v1/handoff/{draft['handoff_id']}/seal").status_code == 409


def test_source_prefers_explicit_event_over_repeated_payload_ref(safety_db, safety_client):
    with safety_db() as session:
        original = ClinicalEventRepository(session).get("EVT-1002")
        ClinicalEventRepository(session).add(
            original.model_copy(update={"event_id": "EVT-REPEATED"})
        )
        node = next(
            n
            for n in EvidenceRepository(session).list_for_patient("P-1001")
            if n.source_id == "LAB-8821"
        )
        session.commit()
    response = safety_client.get(f"/api/v1/evidence/{node.evidence_id}/source")
    assert response.status_code == 200
    assert response.json()["event_id"] == "EVT-1002"


@pytest.mark.parametrize(
    "bad_pointer",
    [
        "EVT-MISSING",
        "EVT-WRONG-PATIENT",
        "EVT-WRONG-TYPE",
        "EVT-WRONG-ENCOUNTER",
        "EVT-WRONG-RECORD",
    ],
)
def test_source_does_not_fallback_from_invalid_explicit_provenance(
    safety_db, safety_client, bad_pointer
):
    with safety_db() as session:
        original = ClinicalEventRepository(session).get("EVT-1002")
        changes = {
            "EVT-WRONG-PATIENT": {"patient_id": "P-OTHER"},
            "EVT-WRONG-TYPE": {"event_type": EventType.NOTE_CREATED},
            "EVT-WRONG-ENCOUNTER": {"encounter_id": "ENC-OTHER"},
            "EVT-WRONG-RECORD": {"payload_ref": "LAB-DIFFERENT"},
        }
        if bad_pointer in changes:
            ClinicalEventRepository(session).add(
                original.model_copy(
                    update={
                        "event_id": bad_pointer,
                        **changes[bad_pointer],
                    }
                )
            )
        EvidenceRepository(session).append(
            EvidenceNode(
                evidence_id="EVID-INVALID",
                patient_id="P-1001",
                encounter_id="ENC-2001",
                source_type="LABS",
                source_id="LAB-8821",
                observed_at=utcnow(),
                claim="Bound evidence",
                provenance={"event_id": bad_pointer},
            )
        )
        session.commit()
    assert safety_client.get("/api/v1/evidence/EVID-INVALID/source").status_code == 404


def test_source_fallback_filters_encounter_and_source_type(safety_db, safety_client):
    with safety_db() as session:
        original = ClinicalEventRepository(session).get("EVT-1002")
        ClinicalEventRepository(session).add(
            original.model_copy(
                update={
                    "event_id": "EVT-OTHER",
                    "encounter_id": "ENC-OTHER",
                }
            )
        )
        ClinicalEventRepository(session).add(
            original.model_copy(
                update={
                    "event_id": "EVT-NOTE",
                    "event_type": EventType.NOTE_CREATED,
                }
            )
        )
        EvidenceRepository(session).append(
            EvidenceNode(
                evidence_id="EVID-FALLBACK",
                patient_id="P-1001",
                encounter_id="ENC-2001",
                source_type="LABS",
                source_id="LAB-8821",
                observed_at=utcnow(),
                claim="Fallback evidence",
            )
        )
        session.commit()
    response = safety_client.get("/api/v1/evidence/EVID-FALLBACK/source")
    assert response.status_code == 200
    assert response.json()["event_id"] == "EVT-1002"


@pytest.mark.parametrize("operation", ["edit", "seal"])
def test_stale_write_after_concurrent_seal_returns_conflict(
    safety_db, safety_client, monkeypatch, operation
):
    with safety_db() as session:
        # Remove only the seeded review guard, leaving the real seal and audit paths intact.
        session.get(FindingRow, FIXTURE_FINDING_ID).requires_review = False
        draft = create_draft(session, "P-1001", "ENC-2001", ACTOR)
        session.commit()
    with safety_db() as stale_session:
        real_scalar = stale_session.scalar
        scheduled = False

        def scalar_with_concurrent_seal(statement, *args, **kwargs):
            nonlocal scheduled
            result = real_scalar(statement, *args, **kwargs)
            if isinstance(result, HandoffReportRow) and not scheduled:
                scheduled = True
                with safety_db() as other_session:
                    seal_handoff(other_session, draft.handoff_id, ACTOR)
                    other_session.commit()
            return result

        monkeypatch.setattr(stale_session, "scalar", scalar_with_concurrent_seal)
        app = safety_client.app

        def stale_dependency():
            yield stale_session

        app.dependency_overrides[get_session] = stale_dependency
        url = f"/api/v1/handoff/{draft.handoff_id}"
        response = (
            safety_client.patch(url, json={"situation": "Must never replace sealed text"})
            if operation == "edit"
            else safety_client.post(f"{url}/seal")
        )
        assert response.status_code == 409
    with safety_db() as session:
        row = session.get(HandoffReportRow, draft.handoff_id)
        assert row.status == "SEALED"
        assert row.situation == draft.situation
        actions = list(
            session.scalars(
                select(AuditLogRow.action).where(AuditLogRow.entity_id == draft.handoff_id)
            )
        )
        assert actions.count("seal") == 1
        assert "edit_draft" not in actions


@pytest.mark.parametrize("action", ["ACCEPT", "REJECT"])
def test_seal_refreshes_reviewed_pending_items_and_preserves_sbar(safety_db, safety_client, action):
    before = safety_client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    draft = safety_client.post("/api/v1/patients/P-1001/handoff/draft").json()
    assert any(before["claim"] in item for item in draft["pending_items"])
    text = {
        "situation": "Doctor situation",
        "background": "Doctor background",
        "assessment": "Doctor assessment",
        "recommendation": "Doctor recommendation",
    }
    assert (
        safety_client.patch(f"/api/v1/handoff/{draft['handoff_id']}", json=text).status_code == 200
    )
    assert (
        safety_client.post(
            f"/api/v1/findings/{FIXTURE_FINDING_ID}/review",
            json={"action": action, "reason": "Synthetic review rationale"},
        ).status_code
        == 200
    )
    response = safety_client.post(f"/api/v1/handoff/{draft['handoff_id']}/seal")
    assert response.status_code == 200
    sealed = response.json()
    assert not any(before["claim"] in item for item in sealed["pending_items"])
    assert before["claim"] not in sealed["confirmed_items"]
    assert all(sealed[field] == value for field, value in text.items())
    after = safety_client.get(f"/api/v1/findings/{FIXTURE_FINDING_ID}").json()
    for field in ("claim", "supporting_evidence", "searched_sources"):
        assert after[field] == before[field]
    with safety_db() as session:
        reviews = list(
            session.scalars(
                select(AuditLogRow).where(
                    AuditLogRow.entity_id == FIXTURE_FINDING_ID, AuditLogRow.action == "review"
                )
            )
        )
        assert len(reviews) == 1
        assert reviews[0].reason == "Synthetic review rationale"


def test_seal_refreshes_current_loops_and_confirmed_evidence_links(safety_db, safety_client):
    draft = safety_client.post("/api/v1/patients/P-1001/handoff/draft").json()
    assert "LOOP-1001" in draft["loop_ids"]
    assert (
        safety_client.post(
            f"/api/v1/findings/{FIXTURE_FINDING_ID}/review", json={"action": "ACCEPT"}
        ).status_code
        == 200
    )
    with safety_db() as session:
        session.get(OpenLoopRow, "LOOP-1001").state = "RESOLVED"
        original = ClinicalEventRepository(session).get("EVT-1002")
        ClinicalEventRepository(session).add(
            original.model_copy(
                update={
                    "event_id": "EVT-NEW-LAB",
                    "payload_ref": "LAB-NEW",
                }
            )
        )
        EvidenceRepository(session).append(
            EvidenceNode(
                evidence_id="EVID-NEW",
                patient_id="P-1001",
                source_type="LABS",
                source_id="LAB-NEW",
                observed_at=utcnow(),
                claim="New verified source fact",
                provenance={"event_id": "EVT-NEW-LAB"},
            )
        )
        session.commit()
    response = safety_client.post(f"/api/v1/handoff/{draft['handoff_id']}/seal")
    assert response.status_code == 200
    sealed = response.json()
    assert "LOOP-1001" not in sealed["loop_ids"]
    assert "EVID-NEW" in sealed["evidence_ids"]
    assert "New verified source fact" in sealed["confirmed_items"]
    assert all(
        sealed[field] == draft[field]
        for field in ("situation", "background", "assessment", "recommendation")
    )


@pytest.mark.parametrize("operation", ["edit", "seal"])
def test_stale_write_cannot_overwrite_concurrent_edit_even_when_clock_repeats(
    safety_db, safety_client, monkeypatch, operation
):
    from apps.api.app.db_time import as_utc
    from apps.api.app.services import handoff_write_service

    with safety_db() as session:
        session.get(FindingRow, FIXTURE_FINDING_ID).requires_review = False
        draft = create_draft(session, "P-1001", "ENC-2001", ACTOR)
        session.commit()
        version = as_utc(session.get(HandoffReportRow, draft.handoff_id).updated_at)
    monkeypatch.setattr(handoff_write_service, "utcnow", lambda: version)
    with safety_db() as stale_session:
        real_scalar = stale_session.scalar
        scheduled = False

        def scalar_with_concurrent_edit(statement, *args, **kwargs):
            nonlocal scheduled
            result = real_scalar(statement, *args, **kwargs)
            if isinstance(result, HandoffReportRow) and not scheduled:
                scheduled = True
                with safety_db() as other_session:
                    edit_handoff_draft(
                        other_session,
                        draft.handoff_id,
                        HandoffDraftUpdate(situation="Winning edit"),
                        ACTOR,
                    )
                    other_session.commit()
            return result

        monkeypatch.setattr(stale_session, "scalar", scalar_with_concurrent_edit)

        def stale_dependency():
            yield stale_session

        safety_client.app.dependency_overrides[get_session] = stale_dependency
        url = f"/api/v1/handoff/{draft.handoff_id}"
        response = (
            safety_client.patch(url, json={"situation": "Losing edit"})
            if operation == "edit"
            else safety_client.post(f"{url}/seal")
        )
        assert response.status_code == 409
    with safety_db() as session:
        row = session.get(HandoffReportRow, draft.handoff_id)
        assert row.status == "DRAFT"
        assert row.situation == "Winning edit"
        edits = list(
            session.scalars(
                select(AuditLogRow).where(
                    AuditLogRow.entity_id == draft.handoff_id, AuditLogRow.action == "edit_draft"
                )
            )
        )
        assert len(edits) == 1
        assert edits[0].payload["changes"]["situation"]["old"] == draft.situation
