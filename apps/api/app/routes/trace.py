from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from apps.api.app.db_models import AgentRunRow
from apps.api.app.dependencies import SessionDep

router = APIRouter(tags=["agent"])


@router.get("/loops/{loop_id}/trace")
def trace(loop_id: str, session: SessionDep):
    rows = session.scalars(select(AgentRunRow).where(AgentRunRow.loop_id == loop_id)).all()
    return [
        {
            "run_id": row.run_id,
            "loop_id": row.loop_id,
            "intent_id": row.intent_id,
            "trigger_event_id": row.trigger_event_id,
            "steps": row.steps or [],
            "tool_calls": row.tool_calls or [],
            "stop_reason": row.stop_reason,
            "trace_metadata": (row.payload or {}).get("trace_metadata", {}),
        }
        for row in rows
    ]
