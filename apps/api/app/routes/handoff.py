from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from apps.api.app.dependencies import ActorDep, SessionDep
from apps.api.app.services.handoff_service import create_draft, seal_handoff
from packages.contracts import HandoffResponse

router = APIRouter(tags=["handoff"])


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
    report = create_draft(session, patient_id, encounter_id, actor)
    session.commit()
    return _response(report)


@router.post("/handoff/{handoff_id}/seal", response_model=HandoffResponse)
def seal(handoff_id: str, session: SessionDep, actor: ActorDep):
    try:
        report = seal_handoff(session, handoff_id, actor)
        session.commit()
    except (KeyError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _response(report)
