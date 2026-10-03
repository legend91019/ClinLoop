from __future__ import annotations

from apps.api.app.db_models import FindingRow, ReviewDecisionRow
from apps.api.app.repositories import AuditRepository
from packages.contracts import ActorRef, ReviewAction, ReviewDecision, new_id


def review_finding(
    session, finding_id: str, action: ReviewAction, reviewer: ActorRef, reason: str | None = None
) -> ReviewDecision:
    row = session.get(FindingRow, finding_id)
    if row is None:
        raise KeyError(finding_id)
    decision = ReviewDecision(
        decision_id=new_id("REV"),
        finding_id=finding_id,
        action=action,
        reviewer=reviewer,
        reason=reason,
    )
    old = row.review_status
    row.review_status = (
        "ACCEPTED"
        if action is ReviewAction.ACCEPT
        else "REJECTED"
        if action is ReviewAction.REJECT
        else "EDITED"
    )
    row.requires_review = False if action is ReviewAction.ACCEPT else True
    session.add(
        ReviewDecisionRow(
            decision_id=decision.decision_id,
            finding_id=finding_id,
            action=action.value,
            reviewer_id=reviewer.actor_id,
            reviewer_role=reviewer.role,
            reviewer_name=reviewer.display_name,
            reason=reason,
            decided_at=decision.decided_at,
            payload=decision.model_dump(mode="json"),
        )
    )
    AuditRepository(session).append(
        entity_type="finding",
        entity_id=finding_id,
        action="review",
        actor=reviewer,
        old_state=old,
        new_state=row.review_status,
        reason=reason,
    )
    session.flush()
    return decision
