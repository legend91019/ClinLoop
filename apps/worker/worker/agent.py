from __future__ import annotations

from collections.abc import Sequence

from apps.worker.worker.memory import WorkflowMemory
from apps.worker.worker.planner import plan_for_event
from apps.worker.worker.repositories import AgentRunRepository
from apps.worker.worker.skills.intent import extract_clinical_intent
from packages.contracts import (
    AgentRun,
    AgentStep,
    AgentStepKind,
    ClinicalEvent,
    EventType,
    Finding,
    FindingType,
    LoopState,
    OpenLoop,
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
        materialize_context: bool = True,
    ) -> None:
        self.memory = memory or WorkflowMemory()
        self.runs = runs or AgentRunRepository()
        self.step_budget = step_budget
        self.materialize_context = materialize_context
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
        loop_id = self._prepare_event_context(event)
        parent = self._latest_run_for_loop(loop_id) if loop_id else None
        return self._execute(event, parent=parent, loop_id=loop_id)

    def _latest_run_for_loop(self, loop_id: str | None) -> AgentRun | None:
        if loop_id is None:
            return None
        return next((run for run in reversed(self.runs.all()) if run.loop_id == loop_id), None)

    def _prepare_event_context(self, event: ClinicalEvent) -> str | None:
        """Materialize the small memory snapshot needed for this event.

        The worker owns proposals in memory only.  Persistence and state
        transitions remain API repository/Guard responsibilities.  Existing
        snapshots are reused so replaying a seeded case does not create a
        second intent or dependency loop.
        """
        if not self.materialize_context:
            return None

        if event.event_type is EventType.NOTE_CREATED:
            intent = next(
                (
                    candidate
                    for candidate in self.memory.intents.values()
                    if candidate.patient_id == event.patient_id
                    and candidate.source_event_id == event.event_id
                ),
                None,
            )
            if intent is None:
                intent = extract_clinical_intent(
                    str(event.payload.get("text", "")),
                    patient_id=event.patient_id,
                    encounter_id=event.encounter_id,
                    source_event_id=event.event_id,
                )
                if intent is not None:
                    self.memory.save_intent(intent)
            if intent is None:
                return None
            loop = next(
                (
                    candidate
                    for candidate in self.memory.loops.values()
                    if candidate.patient_id == event.patient_id
                    and candidate.intent_id == intent.intent_id
                    and candidate.goal.lower().startswith("follow up")
                ),
                None,
            )
            if loop is None:
                loop = OpenLoop(
                    loop_id=new_id("LOOP"),
                    patient_id=event.patient_id,
                    encounter_id=event.encounter_id,
                    intent_id=intent.intent_id,
                    goal="Follow up the repeat blood culture result",
                    state=LoopState.WAITING_EVENT,
                    waiting_for=[EventType.LAB_RESULT_CREATED],
                    priority="HIGH",
                    confidence=0.8,
                    last_plan="Wait for the blood culture result before planning the next step.",
                    last_planned_at=utcnow(),
                )
                self.memory.save_loop(loop)
            return loop.loop_id

        if event.event_type is EventType.LAB_RESULT_CREATED:
            loop = next(
                (
                    candidate
                    for candidate in self.memory.loops.values()
                    if candidate.patient_id == event.patient_id
                    and EventType.LAB_RESULT_CREATED in candidate.waiting_for
                ),
                None,
            )
            return loop.loop_id if loop else None

        if event.event_type is EventType.PROGRESS_NOTE_CREATED:
            intent = next(
                (
                    candidate
                    for candidate in self.memory.intents.values()
                    if candidate.patient_id == event.patient_id
                ),
                None,
            )
            if intent is None:
                return None
            dependency = next(
                (
                    candidate
                    for candidate in self.memory.loops.values()
                    if candidate.patient_id == event.patient_id
                    and "susceptibility" in candidate.goal.lower()
                ),
                None,
            )
            if dependency is None:
                parent_loop = next(
                    candidate
                    for candidate in self.memory.loops.values()
                    if candidate.patient_id == event.patient_id
                    and candidate.intent_id == intent.intent_id
                )
                dependency = OpenLoop(
                    loop_id=new_id("LOOP"),
                    patient_id=event.patient_id,
                    encounter_id=event.encounter_id,
                    intent_id=intent.intent_id,
                    goal="Await antimicrobial susceptibility result",
                    state=LoopState.WAITING_EVENT,
                    waiting_for=[EventType.LAB_RESULT_CREATED],
                    depends_on=[parent_loop.loop_id],
                    priority="HIGH",
                    confidence=0.8,
                    last_plan="Wait for the susceptibility panel before any plan change.",
                    last_planned_at=utcnow(),
                )
                self.memory.save_loop(dependency)
            return dependency.loop_id

        return None

    def _execute(
        self,
        event: ClinicalEvent,
        *,
        parent: AgentRun | None = None,
        loop_id: str | None = None,
    ) -> AgentRun:
        run_intent_id = parent.intent_id if parent else None
        if run_intent_id is None and loop_id is not None:
            loop = self.memory.loops.get(loop_id)
            run_intent_id = loop.intent_id if loop else None
        run = self.runs.create(
            AgentRun(
                run_id=new_id("RUN"),
                loop_id=loop_id,
                intent_id=run_intent_id,
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
                loop_id=loop_id,
                intent_id=run.intent_id,
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
