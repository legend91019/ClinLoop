from __future__ import annotations

import pytest

from apps.api.app.middleware import redact_sensitive
from apps.mcp_server.mcp_server.tools import ToolRegistry
from apps.worker.worker.policies import ExecutionPolicy, ToolTimeoutError


def test_unregistered_tool_is_rejected_before_call() -> None:
    registry = ToolRegistry()
    registry.register("get_labs", lambda **_: ["synthetic"])
    policy = ExecutionPolicy(allowed_tools=frozenset({"get_labs"}))

    with pytest.raises(PermissionError, match="not allowlisted"):
        policy.call(registry, "seal_handoff_report", patient_id="P-1001")


def test_tool_timeout_is_explicit_and_does_not_claim_missing_data() -> None:
    registry = ToolRegistry()
    registry.register("slow", lambda **_: "done")
    policy = ExecutionPolicy(allowed_tools=frozenset({"slow"}), timeout_seconds=0.0)

    with pytest.raises(ToolTimeoutError) as exc_info:
        policy.call(registry, "slow")
    assert exc_info.value.error_code == "TOOL_TIMEOUT"


def test_sensitive_values_are_redacted_recursively() -> None:
    payload = {
        "patient_id": "P-1001",
        "api_key": "secret",
        "nested": {"authorization": "Bearer secret"},
    }

    redacted = redact_sensitive(payload)

    assert redacted == {
        "patient_id": "P-1001",
        "api_key": "[REDACTED]",
        "nested": {"authorization": "[REDACTED]"},
    }
