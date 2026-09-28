"""Open Loop read endpoints.

``GET /api/v1/patients/{patient_id}/loops``  list the patient's loops
``GET /api/v1/loops/{loop_id}``             one loop + intent + evidence

Loop *writes* (state transitions) are not part of the foundation: they
arrive with the Guard in task 8, and must go through
:meth:`LoopRepository.apply_transition` so the deterministic policy and
the audit log cannot be bypassed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from apps.api.app.dependencies import SessionDep
from apps.api.app.repositories import (
    ClinicalIntentRepository,
    EvidenceRepository,
    FindingRepository,
    LoopRepository,
)
from packages.contracts import (
    EvidenceSummary,
    IntentSummary,
    LoopDetailResponse,
    LoopSummary,
    OpenLoop,
)

__all__ = ["router"]

router = APIRouter(tags=["loops"])


def _to_summary(loop: OpenLoop) -> LoopSummary:
    return LoopSummary(
        loop_id=loop.loop_id,
        intent_id=loop.intent_id,
        goal=loop.goal,
        state=loop.state,
        waiting_for=list(loop.waiting_for),
        depends_on=list(loop.depends_on),
        owner=loop.owner,
        priority=loop.priority,
        confidence=loop.confidence,
        next_check_at=loop.next_check_at,
    )


@router.get(
    "/patients/{patient_id}/loops",
    response_model=list[LoopSummary],
    summary="List a patient's open loops",
)
def list_loops(
    patient_id: str,
    session: SessionDep,
    active_only: Annotated[
        bool, Query(description="Return only loops that are still open")
    ] = False,
) -> list[LoopSummary]:
    """List loops for a patient. Pass ``active_only=true`` to hide closed work."""
    loops = LoopRepository(session).list_for_patient(patient_id, active_only=active_only)
    return [_to_summary(loop) for loop in loops]


@router.get(
    "/loops/{loop_id}",
    response_model=LoopDetailResponse,
    summary="Open loop detail with intent and evidence",
    responses={404: {"description": "Unknown loop"}},
)
def get_loop(loop_id: str, session: SessionDep) -> LoopDetailResponse:
    """Return a loop, its originating intent, its evidence and its findings."""
    loop = LoopRepository(session).get(loop_id)
    if loop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown loop_id: {loop_id}"
        )

    intent = ClinicalIntentRepository(session).get(loop.intent_id)
    evidence = EvidenceRepository(session).list_for_loop(loop_id)
    finding_ids = FindingRepository(session).ids_for_loop(loop_id)

    return LoopDetailResponse(
        loop=_to_summary(loop),
        intent=(
            IntentSummary(
                intent_id=intent.intent_id,
                intent_type=intent.intent_type.value,
                text=intent.text,
                expected_evidence=list(intent.expected_evidence),
                requires_clinician_review=intent.requires_clinician_review,
            )
            if intent
            else None
        ),
        evidence=[
            EvidenceSummary(
                evidence_id=node.evidence_id,
                source_type=node.source_type,
                source_id=node.source_id,
                observed_at=node.observed_at,
                claim=node.claim,
                trust_level=node.trust_level,
            )
            for node in evidence
        ],
        findings=finding_ids,
    )
