from __future__ import annotations

from fastapi import APIRouter

from apps.api.app.dependencies import SessionDep
from apps.api.app.services.audit_service import patient_audit

router = APIRouter(tags=["audit"])


@router.get("/patients/{patient_id}/audit")
def audit(patient_id: str, session: SessionDep):
    return [
        {
            "audit_id": row.audit_id,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "action": row.action,
            "actor_id": row.actor_id,
            "old_state": row.old_state,
            "new_state": row.new_state,
            "reason": row.reason,
            "source_run_id": row.source_run_id,
            "created_at": row.created_at,
        }
        for row in patient_audit(session, patient_id)
    ]
