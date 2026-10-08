"""Authenticated, read-only evidence tools for a published AgentArts workflow."""

from __future__ import annotations

from hmac import compare_digest
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from apps.api.app.dependencies import SessionDep
from apps.api.app.repositories import ClinicalEventRepository
from apps.api.app.settings import get_settings
from apps.mcp_server.mcp_server.adapters import RepositoryTools
from apps.mcp_server.mcp_server.tools import READ_TOOLS, PatientNotFound

router = APIRouter(tags=["agentarts-tools"])


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    trigger_event_id: str


@router.post("/agentarts/tools/{tool_name}")
def call_read_tool(
    tool_name: str,
    request: ToolRequest,
    session: SessionDep,
    x_clinloop_tool_key: Annotated[str | None, Header(alias="X-ClinLoop-Tool-Key")] = None,
) -> dict:
    """A trigger ID fixes the patient and cutoff time; callers cannot choose a future snapshot."""
    key = get_settings().agentarts_tool_key
    if not key or not x_clinloop_tool_key or not compare_digest(key, x_clinloop_tool_key):
        raise HTTPException(status_code=401, detail="invalid tool credential")
    if tool_name not in READ_TOOLS:
        raise HTTPException(status_code=404, detail="unknown read tool")
    trigger = ClinicalEventRepository(session).get(request.trigger_event_id)
    if trigger is None or trigger.patient_id != request.patient_id:
        raise HTTPException(status_code=404, detail="unknown trigger")
    adapter = RepositoryTools(session, as_of=trigger.source_time)
    try:
        result = getattr(adapter, tool_name)(patient_id=request.patient_id)
    except PatientNotFound:
        raise HTTPException(status_code=404, detail="unknown patient") from None
    return {"tool_name": tool_name, "trigger_event_id": trigger.event_id, "result": result}
