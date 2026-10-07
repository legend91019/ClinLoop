"""Deterministic transition policy for Open Loops.

This module is pure data + pure functions. It performs **no database
writes** and calls no model. The policy answers three questions:

1. Is ``current -> requested`` a legal edge at all? (:data:`ALLOWED_TRANSITIONS`)
2. Does entering ``requested`` require clinician review? (:func:`required_review_for`)
3. Does entering ``requested`` require supporting evidence? (:func:`requires_evidence_for`)

The Agent may propose any state; only this policy — applied by
``packages.domain.state_machine.validate_transition`` — decides what is
acceptable.
"""

from __future__ import annotations

from packages.contracts.enums import HIGH_RISK_STATES, TERMINAL_LOOP_STATES, LoopState

__all__ = [
    "ALLOWED_TRANSITIONS",
    "REVIEW_REQUIRED_TARGETS",
    "EVIDENCE_REQUIRED_TARGETS",
    "SYSTEM_DRIVEN_EDGES",
    "allowed_targets",
    "is_edge_allowed",
    "required_review_for",
    "requires_evidence_for",
    "is_system_driven",
    "is_terminal",
]

_HAPPY_PATH = (
    LoopState.CREATED,
    LoopState.PLANNED,
    LoopState.ORDERED,
    LoopState.IN_PROGRESS,
    LoopState.RESULT_AVAILABLE,
    LoopState.ACKNOWLEDGED,
    LoopState.RESOLVED,
)

_EXCEPTION_STATES = (
    LoopState.WAITING_EVENT,
    LoopState.OVERDUE,
    LoopState.ORPHANED,
    LoopState.CONFLICTED,
    LoopState.STALE,
    LoopState.PENDING_REVIEW,
)


def _build_allowed_transitions() -> dict[LoopState, frozenset[LoopState]]:
    """Derive the legal edge set.

    The happy path is a strict chain, with ``ACTION_REQUESTED`` as an
    alias sibling of ``ORDERED``. Exception states are reachable from any
    non-terminal state that is still doing work, and can be left back into
    the happy path. Terminal states are sinks.
    """
    allowed: dict[LoopState, set[LoopState]] = {state: set() for state in LoopState}

    # --- strict happy path ---
    for current, nxt in zip(_HAPPY_PATH, _HAPPY_PATH[1:], strict=False):
        allowed[current].add(nxt)

    # ORDERED and ACTION_REQUESTED are equivalent ordering outcomes.
    allowed[LoopState.PLANNED].add(LoopState.ACTION_REQUESTED)
    allowed[LoopState.ACTION_REQUESTED].add(LoopState.IN_PROGRESS)

    # A result can arrive directly from execution without an explicit
    # IN_PROGRESS checkpoint (labs often return asynchronously).
    allowed[LoopState.ORDERED].add(LoopState.RESULT_AVAILABLE)
    allowed[LoopState.ACTION_REQUESTED].add(LoopState.RESULT_AVAILABLE)

    # --- exception edges ---
    # Anything still active may fall into a waiting/exception state.
    for state in LoopState:
        if state in TERMINAL_LOOP_STATES:
            continue
        if state in _EXCEPTION_STATES:
            continue
        allowed[state].update(_EXCEPTION_STATES)
        # Ordering can be requested straight after planning.
        allowed[state].add(LoopState.ORDERED)

    # Exception states can be recovered into planned/in-progress work.
    for state in _EXCEPTION_STATES:
        if state is LoopState.PENDING_REVIEW:
            # After review the loop either resumes or is closed.
            allowed[state].update(
                {LoopState.PLANNED, LoopState.IN_PROGRESS, LoopState.RESOLVED, LoopState.CANCELLED}
            )
            continue
        allowed[state].update({LoopState.PLANNED, LoopState.IN_PROGRESS})
        if state is LoopState.WAITING_EVENT:
            allowed[state].add(LoopState.RESULT_AVAILABLE)
        if state is LoopState.CONFLICTED:
            # A conflict resolves by re-acknowledging or escalating to review.
            allowed[state].add(LoopState.PENDING_REVIEW)
            allowed[state].add(LoopState.ACKNOWLEDGED)

    # Terminal states are sinks.
    for state in TERMINAL_LOOP_STATES:
        allowed[state].clear()

    return {state: frozenset(targets) for state, targets in allowed.items()}


#: The complete legal edge set of the loop state machine.
ALLOWED_TRANSITIONS: dict[LoopState, frozenset[LoopState]] = _build_allowed_transitions()

#: Entering these states always requires an explicit clinician decision.
#: ``RESOLVED`` is included because closing clinical work is a
#: high-consequence act; ``CANCELLED`` likewise. ``PENDING_REVIEW`` is a
#: request *for* review, so it is excluded here.
REVIEW_REQUIRED_TARGETS: frozenset[LoopState] = frozenset(
    {LoopState.RESOLVED, LoopState.CANCELLED}
) | (HIGH_RISK_STATES - {LoopState.PENDING_REVIEW, LoopState.CONFLICTED})

#: Entering these states requires at least one supporting evidence node.
EVIDENCE_REQUIRED_TARGETS: frozenset[LoopState] = frozenset(
    {LoopState.RESULT_AVAILABLE, LoopState.ACKNOWLEDGED}
)

#: Edges that a *system* event may drive without a clinician in the loop.
#: Everything else must originate from an agent proposal under review.
SYSTEM_DRIVEN_EDGES: frozenset[tuple[LoopState, LoopState]] = frozenset(
    {
        (LoopState.PLANNED, LoopState.ORDERED),
        (LoopState.PLANNED, LoopState.ACTION_REQUESTED),
        (LoopState.ORDERED, LoopState.IN_PROGRESS),
        (LoopState.ACTION_REQUESTED, LoopState.IN_PROGRESS),
        (LoopState.ORDERED, LoopState.RESULT_AVAILABLE),
        (LoopState.ACTION_REQUESTED, LoopState.RESULT_AVAILABLE),
        (LoopState.IN_PROGRESS, LoopState.RESULT_AVAILABLE),
        (LoopState.WAITING_EVENT, LoopState.RESULT_AVAILABLE),
        (LoopState.IN_PROGRESS, LoopState.WAITING_EVENT),
        (LoopState.RESULT_AVAILABLE, LoopState.WAITING_EVENT),
    }
)


def allowed_targets(current: LoopState) -> frozenset[LoopState]:
    """Return the states reachable from ``current`` in one transition."""
    return ALLOWED_TRANSITIONS.get(current, frozenset())


def is_edge_allowed(current: LoopState, requested: LoopState) -> bool:
    """True when ``current -> requested`` is a legal edge."""
    return requested in allowed_targets(current)


def required_review_for(requested_state: LoopState) -> bool:
    """True when entering ``requested_state`` requires a clinician reviewer."""
    return requested_state in REVIEW_REQUIRED_TARGETS


def requires_evidence_for(requested_state: LoopState) -> bool:
    """True when entering ``requested_state`` requires supporting evidence."""
    return requested_state in EVIDENCE_REQUIRED_TARGETS


def is_system_driven(current: LoopState, requested: LoopState) -> bool:
    """True when a system event may drive this edge without a reviewer."""
    return (current, requested) in SYSTEM_DRIVEN_EDGES


def is_terminal(state: LoopState) -> bool:
    """True when no further transition may occur from ``state``."""
    return state in TERMINAL_LOOP_STATES
