from __future__ import annotations

from typing import Any, Callable


class PatientNotFound(LookupError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._tools[name] = fn

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name](**kwargs)

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)


READ_TOOLS = ("get_patient_snapshot", "get_recent_events", "get_orders", "get_labs", "get_consults", "get_progress_notes", "get_handoff", "get_patient_evidence")
WRITE_TOOLS = ("record_review_decision", "seal_handoff_report")
