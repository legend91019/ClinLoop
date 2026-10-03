from __future__ import annotations

from dataclasses import dataclass, field

from packages.contracts import AgentRun


@dataclass
class AgentRunRecord:
    run: AgentRun
    trace: list[dict] = field(default_factory=list)
