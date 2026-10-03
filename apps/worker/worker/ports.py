from __future__ import annotations
from typing import Protocol, Any


class ToolRegistryPort(Protocol):
    def call(self, name: str, **arguments: Any) -> Any: ...
