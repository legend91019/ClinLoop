from __future__ import annotations

from dataclasses import replace
from packages.contracts import AgentRun, AgentStep, ClinicalEvent, EventType, Finding, FindingType, StopReason, new_id, utcnow
from apps.worker.worker.memory import WorkflowMemory
from apps.worker.worker.planner import plan_for_event
from apps.worker.worker.repositories import AgentRunRepository


class WorkflowAgent:
    def __init__(self, memory: WorkflowMemory | None = None, runs: AgentRunRepository | None = None, *, step_budget: int = 8) -> None:
        self.memory = memory or WorkflowMemory()
        self.runs = runs or AgentRunRepository()
        self.step_budget = step_budget
        self.findings: dict[str, Finding] = {}

    def handle_event(self, event: ClinicalEvent) -> AgentRun:
        self.memory.record_event(event)
        existing = next((run for run in self.runs.all() if run.trigger_event_id == event.event_id and run.resumed_from_run_id is None), None)
        if existing:
            return existing
        run = AgentRun(run_id=new_id("RUN"), trigger_event_id=event.event_id, plan=plan_for_event(event))
        run = self.runs.create(run)
        steps = []
        for kind in ("OBSERVE", "REASON", "PLAN", "ACT", "VERIFY"):
            steps.append(AgentStep(step_id=new_id("STEP"), kind=kind, reason=f"{kind.lower()} event {event.event_id}", started_at=utcnow(), finished_at=utcnow()))
        stop = StopReason.WAITING_EXTERNAL_EVENT
        if event.event_type is EventType.LAB_RESULT_CREATED:
            finding = Finding(finding_id=new_id("FND"), patient_id=event.patient_id, finding_type=FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT, claim="A lab result was found without a recorded acknowledgement in the searched workflow records.", supporting_evidence=[event.payload_ref], searched_sources=["LABS", "NOTES", "PROGRESS_NOTES"] , source_run_id=run.run_id, confidence=0.8)
            self.findings[finding.finding_id] = finding
            run = replace(run, finding_ids=[finding.finding_id], stop_reason=StopReason.REQUIRES_CLINICIAN_REVIEW, finished_at=utcnow())
        else:
            run = replace(run, stop_reason=stop, finished_at=utcnow())
        run = replace(run, steps=steps[: self.step_budget])
        self.runs._runs[run.run_id].run = run
        return run

    def resume_loop(self, loop_id: str, event: ClinicalEvent) -> AgentRun:
        run = self.handle_event(event)
        return replace(run, loop_id=loop_id, resumed_from_run_id=run.run_id)

    def replan(self, run_id: str, new_evidence: list) -> AgentRun:
        prior = self.runs.get(run_id)
        if prior is None:
            raise KeyError(run_id)
        run = AgentRun(run_id=new_id("RUN"), trigger_event_id=prior.trigger_event_id, resumed_from_run_id=prior.run_id, loop_id=prior.loop_id, intent_id=prior.intent_id, plan=[*prior.plan, "replan_with_new_evidence"], stop_reason=StopReason.WAITING_EXTERNAL_EVENT, finished_at=utcnow())
        return self.runs.create(run)
