from __future__ import annotations

from collections.abc import Sequence

from apps.worker.worker.memory import WorkflowMemory
from apps.worker.worker.planner import plan_for_event
from apps.worker.worker.repositories import AgentRunRepository
from packages.contracts import (
    AgentRun,
    AgentStep,
    AgentStepKind,
    ClinicalEvent,
    EventType,
    Finding,
    FindingType,
    StopReason,
    new_id,
    utcnow,
)


class WorkflowAgent:
    def __init__(
        self,
        memory: WorkflowMemory | None = None,
        runs: AgentRunRepository | None = None,
        *,
        step_budget: int = 8,
    ) -> None:
        self.memory = memory or WorkflowMemory()
        self.runs = runs or AgentRunRepository()
        self.step_budget = step_budget
        self.findings: dict[str, Finding] = {}

    def handle_event(self, event: ClinicalEvent) -> AgentRun:
        self.memory.record_event(event)
        existing = next(
            (
                run
                for run in self.runs.all()
                if run.trigger_event_id == event.event_id and run.resumed_from_run_id is None
            ),
            None,
        )
        if existing:
            return existing
        return self._execute(event)

    def _execute(
        self,
        event: ClinicalEvent,
        *,
        parent: AgentRun | None = None,
        loop_id: str | None = None,
    ) -> AgentRun:
        run = self.runs.create(
            AgentRun(
                run_id=new_id("RUN"),
                loop_id=loop_id,
                intent_id=parent.intent_id if parent else None,
                trigger_event_id=event.event_id,
                resumed_from_run_id=parent.run_id if parent else None,
                plan=plan_for_event(event),
            )
        )
        steps = [
            AgentStep(
                step_id=new_id("STEP"),
                kind=kind,
                reason=f"{kind.value.lower()} event {event.event_id}",
                started_at=utcnow(),
                finished_at=utcnow(),
            )
            for kind in AgentStepKind
        ]
        stop = StopReason.WAITING_EXTERNAL_EVENT
        updates = {"steps": steps[: self.step_budget], "stop_reason": stop, "finished_at": utcnow()}
        if event.event_type is EventType.LAB_RESULT_CREATED:
            finding = Finding(
                finding_id=new_id("FND"),
                patient_id=event.patient_id,
                finding_type=FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
                claim="A lab result was found without a recorded acknowledgement in the searched workflow records.",
                supporting_evidence=[event.payload_ref],
                searched_sources=["LABS", "NOTES", "PROGRESS_NOTES"],
                source_run_id=run.run_id,
                confidence=0.8,
            )
            self.findings[finding.finding_id] = finding
            updates.update(
                finding_ids=[finding.finding_id], stop_reason=StopReason.REQUIRES_CLINICIAN_REVIEW
            )
        return self.runs.save(run.model_copy(update=updates))

    def resume_loop(self, loop_id: str, event: ClinicalEvent) -> AgentRun:
        prior = next(
            (run for run in reversed(self.runs.all()) if run.loop_id == loop_id),
            None,
        ) or (self.runs.all()[-1] if self.runs.all() else None)
        return self._execute(event, parent=prior, loop_id=loop_id)

    def replan(self, run_id: str, new_evidence: Sequence[object]) -> AgentRun:
        prior = self.runs.get(run_id)
        if prior is None:
            raise KeyError(run_id)
        evidence_refs = [
            item if isinstance(item, str) else getattr(item, "evidence_id", str(item))
            for item in new_evidence
        ]
        run = AgentRun(
            run_id=new_id("RUN"),
            trigger_event_id=prior.trigger_event_id,
            resumed_from_run_id=prior.run_id,
            loop_id=prior.loop_id,
            intent_id=prior.intent_id,
            plan=[
                *prior.plan,
                "replan_with_new_evidence",
                *(f"evidence:{ref}" for ref in evidence_refs),
            ],
            stop_reason=StopReason.WAITING_EXTERNAL_EVENT,
            finished_at=utcnow(),
        )
        return self.runs.create(run)
