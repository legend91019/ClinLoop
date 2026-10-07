from __future__ import annotations

from datetime import datetime

from apps.mcp_server.mcp_server.adapters import RepositoryTools
from apps.mcp_server.mcp_server.tools import READ_TOOLS, ToolRegistry


def build_registry(session, *, as_of: datetime | None = None) -> ToolRegistry:
    adapter = RepositoryTools(session, as_of=as_of)
    registry = ToolRegistry()
    for name in READ_TOOLS:
        registry.register(name, getattr(adapter, name))
    registry.register("record_review_decision", adapter.record_review_decision)
    registry.register("seal_handoff_report", adapter.seal_handoff_report)
    return registry
