from __future__ import annotations

from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.bus import InMemoryEventBus


def run_once(bus: InMemoryEventBus, agent: WorkflowAgent, count: int = 10):
    return [agent.handle_event(event) for event in bus.consume(count=count)]
