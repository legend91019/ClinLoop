"""Frozen data-contract tests (Task 2).

These tests are the contract. If one of them fails, a downstream branch
is about to break — fix the contract deliberately, do not loosen the test.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from packages.contracts import (
    ActorRef,
    ClinicalEvent,
    ClinicalIntent,
    EventType,
    EvidenceNode,
    Finding,
    FindingType,
    HandoffReport,
    HandoffStatus,
    IntentType,
    LoopState,
    OpenLoop,
    ReviewAction,
    ReviewDecision,
    TrustLevel,
)

UTC = UTC
T0 = datetime(2026, 9, 28, 9, 10, tzinfo=UTC)


def make_actor() -> ActorRef:
    return ActorRef(actor_id="DR-001", role="PHYSICIAN", display_name="Dr. Synth")


def make_event(**overrides: object) -> ClinicalEvent:
    payload: dict[str, object] = {
        "event_id": "EVT-001",
        "patient_id": "P-1001",
        "encounter_id": "ENC-2001",
        "event_type": EventType.NOTE_CREATED,
        "event_time": T0,
        "source_time": T0 + timedelta(minutes=1),
        "payload_ref": "NOTE-5001",
        "actor": make_actor(),
    }
    payload.update(overrides)
    return ClinicalEvent(**payload)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# ClinicalEvent
# --------------------------------------------------------------------------


def test_clinical_event_accepts_valid_payload() -> None:
    event = make_event()
    assert event.event_type is EventType.NOTE_CREATED
    assert event.patient_id == "P-1001"


def test_clinical_event_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_event(unexpected_field="nope")


def test_clinical_event_rejects_naive_event_time() -> None:
    with pytest.raises(ValidationError):
        make_event(event_time=datetime(2026, 9, 28, 9, 10))


def test_naive_datetime_raises_validation_error_not_type_error() -> None:
    """Regression: a naive value must fail cleanly, not crash a comparison.

    ``source_time`` and ``event_time`` are compared by a model validator.
    If the naive check ran too late, that comparison would raise a bare
    ``TypeError`` and FastAPI would answer 500 instead of 422.
    """
    with pytest.raises(ValidationError) as excinfo:
        make_event(source_time=datetime(2026, 9, 28, 9, 10))
    assert "timezone-aware" in str(excinfo.value)


def test_naive_datetime_from_iso_string_is_rejected() -> None:
    """The same guarantee must hold for raw JSON payloads."""
    with pytest.raises(ValidationError):
        ClinicalEvent.model_validate(
            {
                "event_id": "EVT-NAIVE",
                "patient_id": "P-1001",
                "encounter_id": "ENC-2001",
                "event_type": "NOTE_CREATED",
                "event_time": "2026-09-28T09:10:00",
                "source_time": "2026-09-28T09:11:00",
                "payload_ref": "NOTE-1",
                "actor": {"actor_id": "DR-1", "role": "PHYSICIAN"},
            }
        )


def test_clinical_event_rejects_empty_id() -> None:
    with pytest.raises(ValidationError):
        make_event(event_id="")


def test_clinical_event_rejects_source_time_far_before_event_time() -> None:
    with pytest.raises(ValidationError):
        make_event(source_time=T0 - timedelta(hours=2))


def test_all_seven_event_types_are_declared() -> None:
    assert len(EventType) == 7
    for name in (
        "NOTE_CREATED",
        "ORDER_UPDATED",
        "LAB_RESULT_CREATED",
        "CONSULT_NOTE_CREATED",
        "PROGRESS_NOTE_CREATED",
        "HANDOFF_STARTED",
        "PATIENT_EVIDENCE_SUBMITTED",
    ):
        assert hasattr(EventType, name)


# --------------------------------------------------------------------------
# EvidenceNode / trust levels
# --------------------------------------------------------------------------


def test_patient_reported_evidence_keeps_its_own_trust_level() -> None:
    node = EvidenceNode(
        evidence_id="EVD-001",
        patient_id="P-1001",
        source_type="PATIENT",
        source_id="PAT-9001",
        observed_at=T0,
        claim="Patient reports feeling more short of breath.",
        trust_level=TrustLevel.PATIENT_REPORTED,
    )
    assert node.trust_level is TrustLevel.PATIENT_REPORTED
    assert node.trust_level is not TrustLevel.SYSTEM_VERIFIED


def test_patient_reported_evidence_cannot_be_pre_verified() -> None:
    with pytest.raises(ValidationError):
        EvidenceNode(
            evidence_id="EVD-002",
            patient_id="P-1001",
            source_type="PATIENT",
            source_id="PAT-9001",
            observed_at=T0,
            claim="Patient reports chest pain.",
            trust_level=TrustLevel.PATIENT_REPORTED,
            verified_at=T0,
        )


# --------------------------------------------------------------------------
# OpenLoop
# --------------------------------------------------------------------------


def make_loop(**overrides: object) -> OpenLoop:
    payload: dict[str, object] = {
        "loop_id": "LOOP-001",
        "patient_id": "P-1001",
        "encounter_id": "ENC-2001",
        "intent_id": "INT-001",
        "goal": "Follow up blood culture result",
        "state": LoopState.CREATED,
    }
    payload.update(overrides)
    return OpenLoop(**payload)  # type: ignore[arg-type]


def test_loop_confidence_must_be_a_probability() -> None:
    with pytest.raises(ValidationError):
        make_loop(confidence=1.4)


def test_waiting_event_loop_must_declare_what_it_waits_for() -> None:
    with pytest.raises(ValidationError):
        make_loop(state=LoopState.WAITING_EVENT)


def test_waiting_event_loop_with_declared_event_is_valid() -> None:
    loop = make_loop(state=LoopState.WAITING_EVENT, waiting_for=[EventType.LAB_RESULT_CREATED])
    assert loop.waiting_for == [EventType.LAB_RESULT_CREATED]


def test_loop_rejects_unknown_priority() -> None:
    with pytest.raises(ValidationError):
        make_loop(priority="URGENTISH")


def test_all_loop_states_are_declared() -> None:
    """7 happy-path + 6 exception/waiting + ACTION_REQUESTED = 15.

    ``ACTION_REQUESTED`` is the spec's ``ORDERED/ACTION_REQUESTED`` sibling:
    a plan can be fulfilled either by an order or by a non-order action.
    """
    assert {
        "CREATED",
        "PLANNED",
        "ORDERED",
        "ACTION_REQUESTED",
        "IN_PROGRESS",
        "RESULT_AVAILABLE",
        "ACKNOWLEDGED",
        "RESOLVED",
        "WAITING_EVENT",
        "OVERDUE",
        "ORPHANED",
        "CONFLICTED",
        "STALE",
        "PENDING_REVIEW",
        "CANCELLED",
    } == {s.value for s in LoopState}


# --------------------------------------------------------------------------
# Finding
# --------------------------------------------------------------------------


def test_finding_requires_both_evidence_and_searched_sources() -> None:
    with pytest.raises(ValidationError):
        Finding(
            finding_id="FND-001",
            patient_id="P-1001",
            finding_type=FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
            claim="Positive blood culture was never acknowledged.",
            searched_sources=["LABS", "NOTES"],
        )

    with pytest.raises(ValidationError):
        Finding(
            finding_id="FND-002",
            patient_id="P-1001",
            finding_type=FindingType.PLAN_WITHOUT_ORDER,
            claim="No order was found for the documented plan.",
            supporting_evidence=["EVD-001"],
        )

    finding = Finding(
        finding_id="FND-003",
        patient_id="P-1001",
        finding_type=FindingType.PLAN_WITHOUT_ORDER,
        claim="No order was found for the documented plan.",
        supporting_evidence=["EVD-001"],
        searched_sources=["ORDERS", "NOTES", "PROGRESS_NOTES"],
    )
    assert finding.supporting_evidence == ["EVD-001"]
    assert finding.searched_sources == ["ORDERS", "NOTES", "PROGRESS_NOTES"]


def test_finding_type_taxonomy_has_at_least_four_gap_classes() -> None:
    assert len(FindingType) >= 4


# --------------------------------------------------------------------------
# ClinicalIntent
# --------------------------------------------------------------------------


def test_intent_dedupes_expected_evidence_preserving_order() -> None:
    intent = ClinicalIntent(
        intent_id="INT-001",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        intent_type=IntentType.FOLLOW_RESULT,
        text="今天复查血培养，结果出来后再决定下一步。",
        expected_evidence=["blood_culture_result", "blood_culture_result", "vitals"],
    )
    assert intent.expected_evidence == ["blood_culture_result", "vitals"]


def test_intent_taxonomy_is_finite_and_named() -> None:
    assert {t.value for t in IntentType} == {
        "FOLLOW_RESULT",
        "FOLLOW_CONSULT",
        "EXECUTE_ORDER",
        "UPDATE_PLAN",
    }


# --------------------------------------------------------------------------
# ReviewDecision / HandoffReport
# --------------------------------------------------------------------------


def test_reject_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(
            decision_id="DEC-001",
            finding_id="FND-001",
            action=ReviewAction.REJECT,
            reviewer=make_actor(),
        )


def test_accept_does_not_require_a_reason() -> None:
    decision = ReviewDecision(
        decision_id="DEC-002",
        finding_id="FND-001",
        action=ReviewAction.ACCEPT,
        reviewer=make_actor(),
    )
    assert decision.action is ReviewAction.ACCEPT


def test_edit_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(
            decision_id="DEC-003",
            finding_id="FND-001",
            action=ReviewAction.EDIT,
            reviewer=make_actor(),
        )


def test_handoff_draft_is_editable_and_unsealed() -> None:
    report = HandoffReport(
        handoff_id="HOF-001",
        patient_id="P-1001",
        encounter_id="ENC-2001",
    )
    assert report.status is HandoffStatus.DRAFT
    assert report.is_editable is True


def test_sealed_handoff_is_not_editable() -> None:
    report = HandoffReport(
        handoff_id="HOF-002",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        status=HandoffStatus.SEALED,
        sealed_at=T0,
    )
    assert report.is_editable is False


def test_sealed_handoff_requires_sealed_at() -> None:
    with pytest.raises(ValidationError):
        HandoffReport(
            handoff_id="HOF-003",
            patient_id="P-1001",
            encounter_id="ENC-2001",
            status=HandoffStatus.SEALED,
        )


# --------------------------------------------------------------------------
# new_id
# --------------------------------------------------------------------------


def test_new_id_is_prefixed_and_unique() -> None:
    from packages.contracts import new_id

    first, second = new_id("EVT"), new_id("EVT")
    assert first.startswith("EVT-")
    assert first != second
