"""Deterministic execution limits for Worker tool calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any


class ToolTimeoutError(TimeoutError):
    """A tool exceeded the configured wall-clock budget."""

    error_code = "TOOL_TIMEOUT"


@dataclass(frozen=True)
class ExecutionPolicy:
    """Allowlisted tools and bounded execution settings."""

    max_steps: int = 8
    timeout_seconds: float = 30.0
    allowed_tools: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if self.timeout_seconds < 0:
            raise ValueError("timeout_seconds cannot be negative")

    def call(self, registry: Any, name: str, **arguments: Any) -> Any:
        """Call one explicitly allowlisted tool and enforce its time budget."""
        if name not in self.allowed_tools:
            raise PermissionError(f"tool {name!r} is not allowlisted")
        if self.timeout_seconds == 0:
            raise ToolTimeoutError(f"tool {name!r} exceeded execution timeout")
        started = monotonic()
        result = registry.call(name, **arguments)
        if monotonic() - started > self.timeout_seconds:
            raise ToolTimeoutError(f"tool {name!r} exceeded execution timeout")
        return result
