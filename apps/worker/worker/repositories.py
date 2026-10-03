from __future__ import annotations

from apps.worker.worker.run_models import AgentRunRecord
from packages.contracts import AgentRun


class AgentRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, AgentRunRecord] = {}
        self._by_event: dict[str, str] = {}

    def create(self, run: AgentRun) -> AgentRun:
        existing = self._runs.get(run.run_id)
        if existing:
            return existing.run
        if run.trigger_event_id in self._by_event and run.resumed_from_run_id is None:
            return self._runs[self._by_event[run.trigger_event_id]].run
        self._runs[run.run_id] = AgentRunRecord(run)
        if run.resumed_from_run_id is None:
            self._by_event[run.trigger_event_id] = run.run_id
        return run

    def save(self, run: AgentRun) -> AgentRun:
        """Persist a replacement contract for an existing run."""
        record = self._runs.get(run.run_id)
        if record is None:
            raise KeyError(f"unknown run_id: {run.run_id}")
        record.run = run
        return run

    def append_trace(self, run_id: str, **trace) -> AgentRun:
        record = self._runs[run_id]
        record.trace.append(trace)
        return record.run

    def get(self, run_id: str) -> AgentRun | None:
        record = self._runs.get(run_id)
        return record.run if record else None

    def all(self) -> list[AgentRun]:
        return [record.run for record in self._runs.values()]
