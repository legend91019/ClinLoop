from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from apps.api.app.dependencies import ActorDep, SessionDep
from apps.api.app.services.review_service import review_finding
from packages.contracts import ReviewAction, ReviewRequest, ReviewResponse

router = APIRouter(tags=["findings"])


@router.post("/findings/{finding_id}/review", response_model=ReviewResponse)
def review(
    finding_id: str, body: ReviewRequest, session: SessionDep, actor: ActorDep
) -> ReviewResponse:
    try:
        decision = review_finding(session, finding_id, body.action, actor, body.reason)
        session.commit()
    except KeyError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    row_status = (
        "ACCEPTED"
        if decision.action is ReviewAction.ACCEPT
        else "REJECTED"
        if decision.action is ReviewAction.REJECT
        else "EDITED"
    )
    return ReviewResponse(
        decision_id=decision.decision_id,
        finding_id=finding_id,
        action=decision.action.value,
        review_status=row_status,
    )
