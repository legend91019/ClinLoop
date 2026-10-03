from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: str | None = None
    loop_id: str | None = None
    finding_id: str | None = None
    payload: dict[str, Any] = {}
