from __future__ import annotations

from typing import Any, Protocol


class ToolRegistryPort(Protocol):
    def call(self, name: str, **arguments: Any) -> Any: ...
