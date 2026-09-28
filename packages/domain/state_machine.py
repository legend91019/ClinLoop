"""Deterministic Open Loop state machine.

``validate_transition`` is the single gate every loop state change must
pass. It is pure, synchronous and side-effect free: it performs **no
database writes** (spec §3, task 2).

Contract::

    validate_transition(current, requested, evidence_ids, clinician_approved)
        -> TransitionResult

Semantics:

* Structurally impossible edges raise :class:`InvalidTransition` — the
  caller has a bug and must be told loudly.
* Legal edges that are merely *not yet approved* return
  ``TransitionResult(allowed=False, requires_review=True, reason=...)``
  so the API can answer 403/409 with a structured body instead of 500.
* ``RESULT_AVAILABLE -> RESOLVED`` is **not** a legal shortcut, even with
  approval: a result must be explicitly acknowledged first.
"""

from __future__ import annotations

from collections.abc import Iterable

from packages.contracts.enums import LoopState
from packages.contracts.models import TransitionResult
from packages.domain.errors import InvalidTransition
from packages.domain.transition_policy import (
    is_edge_allowed,
    is_terminal,
    required_review_for,
    requires_evidence_for,
)

__all__ = [
    "validate_transition",
    "can_transition",
    "next_states",
    "required_review_for",
]


def validate_transition(
    current: LoopState | str,
    requested: LoopState | str,
    evidence_ids: Iterable[str] | None = None,
    clinician_approved: bool = False,
) -> TransitionResult:
    """Validate a proposed loop state change.

    Args:
        current: the loop's present state.
        requested: the state the agent (or system) wants to enter.
        evidence_ids: evidence bound to this change. Required for
            ``RESULT_AVAILABLE`` and ``ACKNOWLEDGED``.
        clinician_approved: whether a clinician reviewer has approved the
            change. Required for high-risk targets such as ``RESOLVED``.

    Returns:
        A :class:`TransitionResult`. ``allowed=True`` means the caller may
        persist the change.

    Raises:
        InvalidTransition: the edge does not exist in the state machine.
    """
    current_state = LoopState(current)
    requested_state = LoopState(requested)
    evidence = [e for e in (evidence_ids or []) if e]
    needs_review = required_review_for(requested_state)

    # --- 0. no-op ---------------------------------------------------------
    if current_state is requested_state:
        return TransitionResult(
            allowed=False,
            current_state=current_state,
            requested_state=requested_state,
            requires_review=False,
            reason=f"loop is already in {current_state}",
        )

    # --- 1. a terminal loop cannot move ----------------------------------
    if is_terminal(current_state):
        raise InvalidTransition(
            current_state,
            requested_state,
            f"{current_state} is terminal; a loop cannot leave it (requested {requested_state})",
        )

    # --- 2. the edge must exist ------------------------------------------
    if not is_edge_allowed(current_state, requested_state):
        # The canonical illegal shortcut: a result is never equivalent to
        # a resolution. Call this out explicitly so the error is teachable.
        if current_state is LoopState.RESULT_AVAILABLE and requested_state is LoopState.RESOLVED:
            raise InvalidTransition(
                current_state,
                requested_state,
                "RESULT_AVAILABLE cannot transition directly to RESOLVED; "
                "the result must be acknowledged first "
                "(RESULT_AVAILABLE -> ACKNOWLEDGED -> RESOLVED)",
            )
        raise InvalidTransition(current_state, requested_state)

    # --- 3. evidence requirement -----------------------------------------
    if requires_evidence_for(requested_state) and not evidence:
        return TransitionResult(
            allowed=False,
            current_state=current_state,
            requested_state=requested_state,
            requires_review=False,
            reason=(
                f"{requested_state} requires supporting evidence; none was supplied. "
                "Attach at least one evidence_id."
            ),
            evidence_ids=evidence,
        )

    # --- 4. review requirement -------------------------------------------
    if needs_review and not clinician_approved:
        return TransitionResult(
            allowed=False,
            current_state=current_state,
            requested_state=requested_state,
            requires_review=True,
            reason=(
                f"{current_state} -> {requested_state} is a high-risk transition and "
                "requires explicit clinician approval."
            ),
            evidence_ids=evidence,
        )

    # --- 5. allowed -------------------------------------------------------
    return TransitionResult(
        allowed=True,
        current_state=current_state,
        requested_state=requested_state,
        requires_review=needs_review,
        reason=f"{current_state} -> {requested_state} permitted",
        evidence_ids=evidence,
    )


def can_transition(
    current: LoopState | str,
    requested: LoopState | str,
    evidence_ids: Iterable[str] | None = None,
    clinician_approved: bool = False,
) -> bool:
    """Convenience boolean wrapper around :func:`validate_transition`.

    Structural impossibilities return ``False`` rather than raising.
    """
    try:
        return validate_transition(
            current,
            requested,
            evidence_ids=evidence_ids,
            clinician_approved=clinician_approved,
        ).allowed
    except InvalidTransition:
        return False


def next_states(current: LoopState | str) -> frozenset[LoopState]:
    """Legal one-step targets from ``current``."""
    from packages.domain.transition_policy import allowed_targets

    return allowed_targets(LoopState(current))
