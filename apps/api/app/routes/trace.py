from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from apps.api.app.db_models import AgentRunRow, ClinicalEventRow
from apps.api.app.dependencies import SessionDep

router = APIRouter(tags=["agent"])


def _serialize(row: AgentRunRow) -> dict:
    return {
        "run_id": row.run_id,
        "loop_id": row.loop_id,
        "intent_id": row.intent_id,
        "trigger_event_id": row.trigger_event_id,
        "steps": row.steps or [],
        "tool_calls": row.tool_calls or [],
        "stop_reason": row.stop_reason,
        "trace_metadata": (row.payload or {}).get("trace_metadata", {}),
    }


@router.get("/loops/{loop_id}/trace")
def trace(loop_id: str, session: SessionDep):
    rows = session.scalars(select(AgentRunRow).where(AgentRunRow.loop_id == loop_id)).all()
    return [_serialize(row) for row in rows]


@router.get("/patients/{patient_id}/runs")
def patient_runs(patient_id: str, session: SessionDep):
    rows = session.scalars(
        select(AgentRunRow)
        .join(ClinicalEventRow, ClinicalEventRow.event_id == AgentRunRow.trigger_event_id)
        .where(ClinicalEventRow.patient_id == patient_id)
        .order_by(AgentRunRow.started_at.desc(), AgentRunRow.run_id.desc())
    ).all()
    return [_serialize(row) for row in rows]
