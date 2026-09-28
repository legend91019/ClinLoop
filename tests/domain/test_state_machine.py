"""State-machine policy tests (Task 2).

These tests pin the exact rules the Deterministic Guard will rely on.
They are the acceptance criteria from the plan:

* ``RESULT_AVAILABLE`` cannot jump straight to ``RESOLVED``
* ``ACKNOWLEDGED -> RESOLVED`` without clinician approval returns
  ``allowed=False, requires_review=True``
* unknown transitions raise :class:`InvalidTransition`
"""

from __future__ import annotations

import pytest

from packages.contracts import LoopState, TransitionResult
from packages.domain import (
    InvalidTransition,
    allowed_targets,
    can_transition,
    is_terminal,
    required_review_for,
    requires_evidence_for,
    validate_transition,
)

# --------------------------------------------------------------------------
# The three plan-mandated acceptance criteria
# --------------------------------------------------------------------------


def test_result_available_cannot_shortcut_to_resolved() -> None:
    """A result must be acknowledged before a loop can be closed."""
    with pytest.raises(InvalidTransition) as excinfo:
        validate_transition(LoopState.RESULT_AVAILABLE, LoopState.RESOLVED)

    assert "acknowledged" in str(excinfo.value).lower()
    assert excinfo.value.current is LoopState.RESULT_AVAILABLE
    assert excinfo.value.requested is LoopState.RESOLVED


def test_result_available_cannot_shortcut_to_resolved_even_when_approved() -> None:
    """Approval does not unlock an edge that does not exist."""
    with pytest.raises(InvalidTransition):
        validate_transition(
            LoopState.RESULT_AVAILABLE,
            LoopState.RESOLVED,
            evidence_ids=["EVD-001"],
            clinician_approved=True,
        )


def test_acknowledged_to_resolved_without_approval_blocks_with_review_required() -> None:
    """Not an error — a policy rejection the API can render as 403."""
    result = validate_transition(
        LoopState.ACKNOWLEDGED,
        LoopState.RESOLVED,
        evidence_ids=["EVD-001"],
        clinician_approved=False,
    )

    assert isinstance(result, TransitionResult)
    assert result.allowed is False
    assert result.requires_review is True
    assert result.current_state is LoopState.ACKNOWLEDGED
    assert result.requested_state is LoopState.RESOLVED
    assert result.reason


def test_acknowledged_to_resolved_with_approval_is_allowed() -> None:
    result = validate_transition(
        LoopState.ACKNOWLEDGED,
        LoopState.RESOLVED,
        evidence_ids=["EVD-001"],
        clinician_approved=True,
    )
    assert result.allowed is True
    assert result.requires_review is True


def test_unknown_transition_raises_invalid_transition() -> None:
    with pytest.raises(InvalidTransition):
        validate_transition(LoopState.CREATED, LoopState.RESOLVED)


def test_resolved_is_terminal_and_cannot_move() -> None:
    with pytest.raises(InvalidTransition):
        validate_transition(LoopState.RESOLVED, LoopState.IN_PROGRESS)


# --------------------------------------------------------------------------
# Evidence requirements
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,requested",
    [
        (LoopState.IN_PROGRESS, LoopState.RESULT_AVAILABLE),
        (LoopState.ORDERED, LoopState.RESULT_AVAILABLE),
        (LoopState.RESULT_AVAILABLE, LoopState.ACKNOWLEDGED),
    ],
)
def test_result_and_acknowledgement_require_evidence(
    current: LoopState, requested: LoopState
) -> None:
    result = validate_transition(current, requested, evidence_ids=[])
    assert result.allowed is False
    assert result.requires_review is False
    assert "evidence" in result.reason.lower()


@pytest.mark.parametrize(
    "current,requested",
    [
        (LoopState.IN_PROGRESS, LoopState.RESULT_AVAILABLE),
        (LoopState.RESULT_AVAILABLE, LoopState.ACKNOWLEDGED),
    ],
)
def test_result_and_acknowledgement_pass_with_evidence(
    current: LoopState, requested: LoopState
) -> None:
    result = validate_transition(current, requested, evidence_ids=["EVD-001"])
    assert result.allowed is True
    assert result.evidence_ids == ["EVD-001"]


def test_empty_string_evidence_ids_do_not_count() -> None:
    result = validate_transition(
        LoopState.IN_PROGRESS, LoopState.RESULT_AVAILABLE, evidence_ids=["", ""]
    )
    assert result.allowed is False


# --------------------------------------------------------------------------
# System-driven edges
# --------------------------------------------------------------------------


def test_system_event_can_drive_ordered_to_in_progress() -> None:
    """An execution event may advance an ordered loop without a reviewer."""
    result = validate_transition(LoopState.ORDERED, LoopState.IN_PROGRESS)
    assert result.allowed is True
    assert result.requires_review is False


def test_planned_can_be_ordered_by_the_system() -> None:
    assert can_transition(LoopState.PLANNED, LoopState.ORDERED) is True


def test_planned_can_be_action_requested_without_review() -> None:
    result = validate_transition(LoopState.PLANNED, LoopState.ACTION_REQUESTED)
    assert result.allowed is True
    assert result.requires_review is False


def test_active_loop_can_enter_waiting_event() -> None:
    result = validate_transition(LoopState.IN_PROGRESS, LoopState.WAITING_EVENT)
    assert result.allowed is True


# --------------------------------------------------------------------------
# Review requirements
# --------------------------------------------------------------------------


def test_resolving_requires_review_regardless_of_path() -> None:
    assert required_review_for(LoopState.RESOLVED) is True


def test_cancelling_requires_review() -> None:
    assert required_review_for(LoopState.CANCELLED) is True


def test_ordinary_progress_does_not_require_review() -> None:
    for target in (LoopState.PLANNED, LoopState.ORDERED, LoopState.IN_PROGRESS):
        assert required_review_for(target) is False


def test_requires_evidence_helper_matches_policy() -> None:
    assert requires_evidence_for(LoopState.RESULT_AVAILABLE) is True
    assert requires_evidence_for(LoopState.ACKNOWLEDGED) is True
    assert requires_evidence_for(LoopState.PLANNED) is False


# --------------------------------------------------------------------------
# Structural properties
# --------------------------------------------------------------------------


def test_pending_review_can_be_left_after_a_decision() -> None:
    for target in (LoopState.PLANNED, LoopState.IN_PROGRESS, LoopState.RESOLVED):
        assert can_transition(LoopState.PENDING_REVIEW, target, clinician_approved=True)


def test_terminal_states_have_no_outgoing_edges() -> None:
    for state in (LoopState.RESOLVED, LoopState.CANCELLED):
        assert is_terminal(state) is True
        assert allowed_targets(state) == frozenset()


def test_happy_path_is_walkable_end_to_end() -> None:
    """CREATED -> PLANNED -> ORDERED -> IN_PROGRESS -> RESULT_AVAILABLE
    -> ACKNOWLEDGED -> RESOLVED, with evidence and approval supplied."""
    path = [
        (LoopState.CREATED, LoopState.PLANNED, False),
        (LoopState.PLANNED, LoopState.ORDERED, False),
        (LoopState.ORDERED, LoopState.IN_PROGRESS, False),
        (LoopState.IN_PROGRESS, LoopState.RESULT_AVAILABLE, False),
        (LoopState.RESULT_AVAILABLE, LoopState.ACKNOWLEDGED, False),
        (LoopState.ACKNOWLEDGED, LoopState.RESOLVED, True),
    ]
    state = LoopState.CREATED
    for current, target, approved in path:
        assert current is state, f"path drift at {current}"
        result = validate_transition(
            current, target, evidence_ids=["EVD-001"], clinician_approved=approved
        )
        assert result.allowed is True, f"{current} -> {target}: {result.reason}"
        state = target
    assert state is LoopState.RESOLVED


def test_no_op_transition_is_rejected_not_raised() -> None:
    result = validate_transition(LoopState.IN_PROGRESS, LoopState.IN_PROGRESS)
    assert result.allowed is False
    assert "already" in result.reason.lower()


def test_transition_accepts_plain_strings() -> None:
    result = validate_transition("ORDERED", "IN_PROGRESS")
    assert result.allowed is True
    assert result.requested_state is LoopState.IN_PROGRESS


def test_can_transition_swallows_structural_errors() -> None:
    assert can_transition(LoopState.CREATED, LoopState.RESOLVED) is False
    assert can_transition(LoopState.RESOLVED, LoopState.IN_PROGRESS) is False


def test_every_state_has_a_policy_entry() -> None:
    for state in LoopState:
        # Must not raise.
        allowed_targets(state)
