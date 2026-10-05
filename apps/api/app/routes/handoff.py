from __future__ import annotations

from fastapi import APIRouter, HTTPException

from apps.api.app.dependencies import ActorDep, SessionDep
from apps.api.app.repositories import HandoffRepository
from apps.api.app.services.console_service import edit_handoff_draft
from apps.api.app.services.handoff_service import create_draft, seal_handoff
from packages.contracts import HandoffResponse
from packages.contracts.console import HandoffDraftUpdate

router = APIRouter(tags=["handoff"])


@router.get("/handoff/{handoff_id}", response_model=HandoffResponse)
def read_handoff(handoff_id: str, session: SessionDep):
    report = HandoffRepository(session).get(handoff_id)
    if report is None:
        raise HTTPException(status_code=404, detail="unknown handoff")
    return _response(report)


@router.patch(
    "/handoff/{handoff_id}",
    response_model=HandoffResponse,
    responses={
        403: {"description": "Clinician role required"},
        404: {"description": "Unknown handoff"},
        409: {"description": "Handoff is not a draft or changed concurrently; reload and retry"},
    },
)
def edit_draft(handoff_id: str, body: HandoffDraftUpdate, session: SessionDep, actor: ActorDep):
    try:
        report = edit_handoff_draft(session, handoff_id, body, actor)
        session.commit()
    except (KeyError, ValueError, PermissionError) as exc:
        session.rollback()
        code = (
            403 if isinstance(exc, PermissionError) else 404 if isinstance(exc, KeyError) else 409
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return _response(report)


def _response(report) -> HandoffResponse:
    return HandoffResponse(
        handoff_id=report.handoff_id,
        patient_id=report.patient_id,
        encounter_id=report.encounter_id,
        status=report.status.value if hasattr(report.status, "value") else report.status,
        situation=report.situation,
        background=report.background,
        assessment=report.assessment,
        recommendation=report.recommendation,
        loop_ids=report.loop_ids,
        evidence_ids=report.evidence_ids,
        pending_items=report.pending_items,
        confirmed_items=report.confirmed_items,
    )


@router.post("/patients/{patient_id}/handoff/draft", response_model=HandoffResponse)
def draft(patient_id: str, session: SessionDep, actor: ActorDep, encounter_id: str = "ENC-2001"):
    try:
        report = create_draft(session, patient_id, encounter_id, actor)
        session.commit()
    except (KeyError, PermissionError) as exc:
        session.rollback()
        raise HTTPException(
            status_code=403 if isinstance(exc, PermissionError) else 404, detail=str(exc)
        ) from exc
    return _response(report)


@router.post(
    "/handoff/{handoff_id}/seal",
    response_model=HandoffResponse,
    description=(
        "Refresh encounter-scoped derived links and review-labelled collections before sealing. "
        "Preserve the four SBAR text fields; accepted findings are not confirmed clinical facts."
    ),
    responses={
        403: {"description": "Clinician role required"},
        404: {"description": "Unknown handoff"},
        409: {"description": "Pending high-risk review, non-draft status, or concurrent change"},
    },
)
def seal(handoff_id: str, session: SessionDep, actor: ActorDep):
    try:
        report = seal_handoff(session, handoff_id, actor)
        session.commit()
    except (KeyError, ValueError, PermissionError) as exc:
        session.rollback()
        code = (
            403 if isinstance(exc, PermissionError) else 404 if isinstance(exc, KeyError) else 409
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return _response(report)
