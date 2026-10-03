from __future__ import annotations

from apps.mcp_server.mcp_server.adapters import RepositoryTools
from apps.mcp_server.mcp_server.tools import READ_TOOLS, ToolRegistry


def build_registry(session) -> ToolRegistry:
    adapter = RepositoryTools(session)
    registry = ToolRegistry()
    for name in READ_TOOLS:
        registry.register(name, getattr(adapter, name))
    registry.register("record_review_decision", adapter.record_review_decision)
    registry.register("seal_handoff_report", adapter.seal_handoff_report)
    return registry
