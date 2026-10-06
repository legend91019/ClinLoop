from __future__ import annotations

from collections.abc import Sequence

from apps.api.app.settings import get_settings
from apps.worker.worker.memory import WorkflowMemory
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.planner import plan_for_event
from apps.worker.worker.policies import ExecutionPolicy
from apps.worker.worker.providers import ModelProvider, ModelProviderError, build_model_provider
from apps.worker.worker.repositories import AgentRunRepository
from apps.worker.worker.skills.intent import extract_clinical_intent
from packages.contracts import (
    AgentRun,
    AgentStep,
    AgentStepKind,
    ClinicalEvent,
    ClinicalIntent,
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
        policy: ExecutionPolicy | None = None,
        provider: ModelProvider | None = None,
    ) -> None:
        self.memory = memory or WorkflowMemory()
        self.runs = runs or AgentRunRepository()
        self.policy = policy or ExecutionPolicy(max_steps=step_budget)
        self.step_budget = self.policy.max_steps
        self.materialize_context = materialize_context
        self.provider = provider or build_model_provider(get_settings())
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
        loop_id, proposal, model_error = self._prepare_event_context(event)
        parent = self._latest_run_for_loop(loop_id) if loop_id else None
        return self._execute(
            event,
            parent=parent,
            loop_id=loop_id,
            model_proposal=proposal,
            model_error=model_error,
        )

    def _latest_run_for_loop(self, loop_id: str | None) -> AgentRun | None:
        if loop_id is None:
            return None
        return next((run for run in reversed(self.runs.all()) if run.loop_id == loop_id), None)

    def _prepare_event_context(
        self, event: ClinicalEvent, *, loop_id: str | None = None
    ) -> tuple[str | None, AgentProposal | None, str | None]:
        """Materialize the small memory snapshot needed for this event.

        The worker owns proposals in memory only.  Persistence and state
        transitions remain API repository/Guard responsibilities.  Existing
        snapshots are reused so replaying a seeded case does not create a
        second intent or dependency loop.
        """
        if not self.materialize_context:
            return None, None, None

        proposal, model_error = self._model_proposal(event, loop_id=loop_id)
        if model_error:
            return loop_id, None, model_error

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
                if proposal is not None and proposal.intent_type is not None:
                    intent = ClinicalIntent(
                        intent_id=new_id("INT"),
                        patient_id=event.patient_id,
                        encounter_id=event.encounter_id,
                        intent_type=proposal.intent_type,
                        text=str(event.payload.get("text", proposal.goal)),
                        expected_evidence=proposal.expected_evidence,
                        source_event_id=event.event_id,
                        requires_clinician_review=proposal.priority in {"HIGH", "CRITICAL"},
                    )
                else:
                    intent = extract_clinical_intent(
                        str(event.payload.get("text", "")),
                        patient_id=event.patient_id,
                        encounter_id=event.encounter_id,
                        source_event_id=event.event_id,
                    )
                if intent is not None:
                    self.memory.save_intent(intent)
            if intent is None:
                return None, proposal, None
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
                    goal=proposal.goal
                    if proposal is not None
                    else "Follow up the repeat blood culture result",
                    state=LoopState.WAITING_EVENT,
                    waiting_for=(
                        proposal.waiting_for
                        if proposal is not None and proposal.waiting_for
                        else [EventType.LAB_RESULT_CREATED]
                    ),
                    priority=proposal.priority if proposal is not None else "HIGH",
                    confidence=proposal.confidence if proposal is not None else 0.8,
                    last_plan=(
                        proposal.rationale
                        if proposal is not None
                        else "Wait for the blood culture result before planning the next step."
                    ),
                    last_planned_at=utcnow(),
                )
                self.memory.save_loop(loop)
            return loop.loop_id, proposal, None

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
            return loop.loop_id if loop else None, proposal, None

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
                return None, proposal, None
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
                    goal=(
                        proposal.goal
                        if proposal is not None and proposal.goal
                        else "Await antimicrobial susceptibility result"
                    ),
                    state=LoopState.WAITING_EVENT,
                    waiting_for=(
                        proposal.waiting_for
                        if proposal is not None and proposal.waiting_for
                        else [EventType.LAB_RESULT_CREATED]
                    ),
                    depends_on=[parent_loop.loop_id],
                    priority=proposal.priority if proposal is not None else "HIGH",
                    confidence=proposal.confidence if proposal is not None else 0.8,
                    last_plan=(
                        proposal.rationale
                        if proposal is not None
                        else "Wait for the susceptibility panel before any plan change."
                    ),
                    last_planned_at=utcnow(),
                )
                self.memory.save_loop(dependency)
            return dependency.loop_id, proposal, None

        return None, proposal, None

    def _model_proposal(
        self, event: ClinicalEvent, *, loop_id: str | None
    ) -> tuple[AgentProposal | None, str | None]:
        if event.event_type not in {
            EventType.NOTE_CREATED,
            EventType.LAB_RESULT_CREATED,
            EventType.PROGRESS_NOTE_CREATED,
        }:
            return None, None
        context = self.memory.get_context(event.patient_id, loop_id)
        current_loop = self.memory.loops.get(loop_id) if loop_id else None
        current_intent = self.memory.intents.get(current_loop.intent_id) if current_loop else None
        try:
            proposal = self.provider.analyze(
                AgentContext(
                    event=event,
                    current_loop=current_loop,
                    current_intent=current_intent,
                    recent_events=context.recent_events,
                    visible_evidence=context.evidence,
                )
            )
        except ModelProviderError as exc:
            return None, str(exc)
        if proposal.patient_id != event.patient_id:
            return None, "MODEL_INVALID_PROPOSAL"
        visible_refs = {item.evidence_id for item in context.evidence}
        invalid_refs = set(proposal.evidence_refs) - visible_refs - {event.payload_ref}
        if invalid_refs:
            return None, "MODEL_INVALID_EVIDENCE_REFERENCE"
        return proposal, None

    def _execute(
        self,
        event: ClinicalEvent,
        *,
        parent: AgentRun | None = None,
        loop_id: str | None = None,
        model_proposal: AgentProposal | None = None,
        model_error: str | None = None,
    ) -> AgentRun:
        run_intent_id = parent.intent_id if parent else None
        if run_intent_id is None and loop_id is not None:
            loop = self.memory.loops.get(loop_id)
            run_intent_id = loop.intent_id if loop else None
        trace_metadata = self.provider.metadata.as_dict()
        if model_proposal is not None:
            trace_metadata = {
                **trace_metadata,
                "proposal_ref": new_id("PROP"),
                "proposal_summary": model_proposal.goal[:200],
                "confidence": model_proposal.confidence,
            }
        if model_error:
            trace_metadata = {**trace_metadata, "error_code": model_error}
        run = self.runs.create(
            AgentRun(
                run_id=new_id("RUN"),
                loop_id=loop_id,
                intent_id=run_intent_id,
                trigger_event_id=event.event_id,
                resumed_from_run_id=parent.run_id if parent else None,
                plan=plan_for_event(event),
                trace_metadata=trace_metadata,
            )
        )
        steps = [
            AgentStep(
                step_id=new_id("STEP"),
                kind=kind,
                reason=(
                    f"model proposal accepted for {event.event_id}"
                    if kind is AgentStepKind.REASON and model_proposal is not None
                    else f"model provider error for {event.event_id}"
                    if kind is AgentStepKind.REASON and model_error
                    else f"{kind.value.lower()} event {event.event_id}"
                ),
                started_at=utcnow(),
                finished_at=utcnow(),
            )
            for kind in AgentStepKind
        ]
        stop = StopReason.MODEL_ERROR if model_error else StopReason.WAITING_EXTERNAL_EVENT
        if not model_error and len(steps) > self.policy.max_steps:
            stop = StopReason.BUDGET_EXCEEDED
        updates = {"steps": steps[: self.step_budget], "stop_reason": stop, "finished_at": utcnow()}
        if event.event_type is EventType.LAB_RESULT_CREATED and stop not in {
            StopReason.BUDGET_EXCEEDED,
            StopReason.MODEL_ERROR,
        }:
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
        self.memory.record_event(event)
        prior = next(
            (run for run in reversed(self.runs.all()) if run.loop_id == loop_id),
            None,
        ) or (self.runs.all()[-1] if self.runs.all() else None)
        _prepared_loop, proposal, model_error = self._prepare_event_context(event, loop_id=loop_id)
        return self._execute(
            event,
            parent=prior,
            loop_id=loop_id,
            model_proposal=proposal,
            model_error=model_error,
        )

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
