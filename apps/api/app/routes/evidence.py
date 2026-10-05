"""Finding and Evidence read endpoints.

``GET /api/v1/findings/{finding_id}``    one finding, with its evidence
``GET /api/v1/evidence/{evidence_id}``   one evidence node, resolvable
                                         back to its raw source record

Both are read-only. Review writes arrive in task 8 with the Guard.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from apps.api.app.dependencies import SessionDep
from apps.api.app.repositories import EvidenceRepository, FindingRepository
from apps.api.app.services.evidence_source_service import resolve_source_event
from packages.contracts import ClinicalEvent, EvidenceSummary, FindingResponse

__all__ = ["router"]

router = APIRouter(tags=["findings"])


@router.get("/patients/{patient_id}/findings", response_model=list[FindingResponse])
def list_findings(patient_id: str, session: SessionDep) -> list[FindingResponse]:
    return [
        get_finding(item.finding_id, session)
        for item in FindingRepository(session).list_for_patient(patient_id)
    ]


@router.get(
    "/evidence/{evidence_id}/source",
    response_model=ClinicalEvent,
    description=(
        "Resolve explicit provenance.event_id first, validating patient, encounter and source type. "
        "Without an explicit pointer, return only an unambiguous source in the same scope."
    ),
    responses={
        404: {"description": "Unknown evidence or unavailable, invalid or ambiguous source"}
    },
)
def get_evidence_source(evidence_id: str, session: SessionDep) -> ClinicalEvent:
    """Resolve a source pointer within the evidence patient's event store."""
    node = EvidenceRepository(session).get(evidence_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown evidence")
    event = resolve_source_event(session, node)
    if event is None:
        raise HTTPException(status_code=404, detail="original source unavailable or ambiguous")
    return event


@router.get(
    "/findings/{finding_id}",
    response_model=FindingResponse,
    summary="Workflow gap detail",
    responses={404: {"description": "Unknown finding"}},
)
def get_finding(finding_id: str, session: SessionDep) -> FindingResponse:
    """Return a finding.

    ``supporting_evidence`` and ``searched_sources`` are always included:
    the console must be able to show *what was searched*, so that a gap in
    coverage is never presented as proof of absence.
    """
    finding = FindingRepository(session).get(finding_id)
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown finding_id: {finding_id}"
        )

    return FindingResponse(
        finding_id=finding.finding_id,
        patient_id=finding.patient_id,
        loop_id=finding.loop_id,
        intent_id=finding.intent_id,
        finding_type=finding.finding_type,
        claim=finding.claim,
        supporting_evidence=list(finding.supporting_evidence),
        searched_sources=list(finding.searched_sources),
        confidence=finding.confidence,
        requires_review=finding.requires_review,
        review_status=finding.review_status,
        detected_at=finding.detected_at,
    )


@router.get(
    "/evidence/{evidence_id}",
    response_model=EvidenceSummary,
    summary="Evidence node with its raw source pointer",
    responses={404: {"description": "Unknown evidence"}},
)
def get_evidence(evidence_id: str, session: SessionDep) -> EvidenceSummary:
    """Return one evidence node.

    ``source_type`` + ``source_id`` are the pointer back to the original
    record (e.g. ``LABS`` / ``LAB-8821``) that the evidence drawer opens.
    """
    node = EvidenceRepository(session).get(evidence_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown evidence_id: {evidence_id}"
        )

    return EvidenceSummary(
        evidence_id=node.evidence_id,
        source_type=node.source_type,
        source_id=node.source_id,
        observed_at=node.observed_at,
        claim=node.claim,
        trust_level=node.trust_level,
    )
