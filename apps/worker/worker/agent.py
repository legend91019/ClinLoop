from __future__ import annotations

import json
import re
from collections.abc import Sequence
from hashlib import sha256
from time import monotonic
from typing import Any

from apps.api.app.settings import get_settings
from apps.mcp_server.mcp_server.tools import READ_TOOLS
from apps.worker.worker.memory import WorkflowMemory
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.planner import plan_for_event
from apps.worker.worker.policies import ExecutionPolicy
from apps.worker.worker.providers import ModelProvider, ModelProviderError, build_model_provider
from apps.worker.worker.repositories import AgentRunRepository
from apps.worker.worker.skills.intent import extract_clinical_intent
from apps.worker.worker.verification import (
    has_explicit_ack,
    match_acknowledged_loop,
    match_result_loop,
)
from packages.contracts import (
    AgentRun,
    AgentStep,
    AgentStepKind,
    ClinicalEvent,
    ClinicalIntent,
    EventType,
    EvidenceNode,
    Finding,
    FindingType,
    IntentType,
    LoopState,
    OpenLoop,
    StopReason,
    ToolCall,
    TrustLevel,
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
        self.policy = policy or ExecutionPolicy(
            max_steps=step_budget, allowed_tools=frozenset(READ_TOOLS)
        )
        self.step_budget = self.policy.max_steps
        self.materialize_context = materialize_context
        self.provider = provider or build_model_provider(get_settings())
        self.findings: dict[str, Finding] = {}

    def handle_event(self, event: ClinicalEvent, *, tool_registry: Any | None = None) -> AgentRun:
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
            tool_registry=tool_registry,
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

        if event.event_type is EventType.LAB_RESULT_CREATED and loop_id is None:
            matched = match_result_loop(event, self.memory.loops.values(), self.memory.intents)
            loop_id = matched.loop_id if matched else None
        if event.event_type is EventType.PROGRESS_NOTE_CREATED and loop_id is None:
            matched = match_acknowledged_loop(
                event,
                self.memory.events,
                self.memory.loops.values(),
                self.memory.evidence.values(),
            )
            loop_id = matched.loop_id if matched else None
        proposal, model_error = self._model_proposal(event, loop_id=loop_id)
        if model_error:
            return loop_id, None, model_error

        if event.event_type is EventType.NOTE_CREATED:
            model_priority = proposal.priority if proposal is not None else "HIGH"
            source_priority = str(event.payload.get("priority", "")).upper()
            priority_order = {"LOW": 0, "NORMAL": 1, "HIGH": 2, "CRITICAL": 3}
            priority = (
                source_priority
                if source_priority in priority_order
                and priority_order[source_priority] > priority_order[model_priority]
                else model_priority
            )
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
                        requires_clinician_review=priority in {"HIGH", "CRITICAL"},
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
                    priority=priority,
                    confidence=proposal.confidence if proposal is not None else 0.8,
                    last_plan=(
                        proposal.rationale
                        if proposal is not None
                        else "Wait for the blood culture result before planning the next step."
                    ),
                    last_planned_at=event.source_time,
                )
                self.memory.save_loop(loop)
            return loop.loop_id, proposal, None

        if event.event_type is EventType.LAB_RESULT_CREATED:
            return loop_id, proposal, None

        if event.event_type is EventType.PROGRESS_NOTE_CREATED:
            if loop_id is None:
                return None, proposal, None
            parent_loop = self.memory.loops[loop_id]
            dependency_kind = event.payload.get("creates_dependency")
            if not isinstance(dependency_kind, str) or not re.fullmatch(
                r"[A-Za-z0-9_]{1,64}", dependency_kind
            ):
                return loop_id, proposal, None
            dependency = next(
                (
                    candidate
                    for candidate in self.memory.loops.values()
                    if candidate.patient_id == event.patient_id
                    and candidate.encounter_id == event.encounter_id
                    and loop_id in candidate.depends_on
                    and (
                        dependency_kind
                        in self.memory.intents[candidate.intent_id].expected_evidence
                        or dependency_kind.replace("_", " ") in candidate.goal.lower()
                    )
                ),
                None,
            )
            if dependency is None:
                dependent_intent = ClinicalIntent(
                    intent_id=new_id("INT"),
                    patient_id=event.patient_id,
                    encounter_id=event.encounter_id,
                    intent_type=IntentType.FOLLOW_RESULT,
                    text=str(event.payload.get("text", dependency_kind)),
                    expected_evidence=[dependency_kind],
                    source_event_id=event.event_id,
                )
                self.memory.save_intent(dependent_intent)
                dependency = OpenLoop(
                    loop_id=new_id("LOOP"),
                    patient_id=event.patient_id,
                    encounter_id=event.encounter_id,
                    intent_id=dependent_intent.intent_id,
                    goal=f"Await {dependency_kind.replace('_', ' ')}",
                    state=LoopState.WAITING_EVENT,
                    waiting_for=[EventType.LAB_RESULT_CREATED],
                    depends_on=[loop_id],
                    priority=parent_loop.priority,
                    confidence=proposal.confidence
                    if proposal is not None
                    else parent_loop.confidence,
                    last_plan=(
                        proposal.rationale
                        if proposal is not None
                        else f"Wait for the {dependency_kind.replace('_', ' ')} before replanning."
                    ),
                    last_planned_at=event.source_time,
                )
                self.memory.save_loop(dependency)
            return loop_id, proposal, None

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
        visible_refs.update(
            ref for recent in context.recent_events for ref in (recent.event_id, recent.payload_ref)
        )
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
        tool_registry: Any | None = None,
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
        tool_calls: list[ToolCall] = []
        tool_records: list[ClinicalEvent] = []
        tool_error: str | None = None
        lab_verified = tool_registry is None
        if tool_registry is not None and model_error is None:
            selected = list(dict.fromkeys(model_proposal.requested_tools if model_proposal else []))
            if event.event_type is EventType.LAB_RESULT_CREATED and loop_id:
                selected = list(dict.fromkeys([*selected, "get_labs", "get_progress_notes"]))
            for name in selected[: self.policy.max_steps]:
                started = monotonic()
                try:
                    rows = self.policy.call(tool_registry, name, patient_id=event.patient_id)
                    digest = sha256(
                        json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
                    ).hexdigest()[:16]
                    tool_calls.append(
                        ToolCall(
                            tool_name=name,
                            arguments={"patient_id": event.patient_id},
                            result_ref=f"sha256:{digest}",
                            duration_ms=int((monotonic() - started) * 1000),
                            started_at=utcnow(),
                        )
                    )
                    if name == "get_progress_notes" and isinstance(rows, list):
                        for item in rows:
                            try:
                                tool_records.append(ClinicalEvent.model_validate(item))
                            except (ValueError, TypeError):
                                continue
                    if name == "get_labs" and isinstance(rows, list):
                        for item in rows:
                            try:
                                found = ClinicalEvent.model_validate(item)
                            except (ValueError, TypeError):
                                continue
                            if (
                                found.event_id == event.event_id
                                and found.patient_id == event.patient_id
                                and found.encounter_id == event.encounter_id
                                and found.payload_ref == event.payload_ref
                                and found.source_time <= event.source_time
                            ):
                                lab_verified = True
                except (PermissionError, TimeoutError, KeyError, ValueError):
                    tool_error = "TOOL_QUERY_FAILED"
                    tool_calls.append(
                        ToolCall(
                            tool_name=name,
                            arguments={"patient_id": event.patient_id},
                            ok=False,
                            error_code=tool_error,
                            duration_ms=int((monotonic() - started) * 1000),
                            started_at=utcnow(),
                        )
                    )
                    break
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
        if tool_error:
            stop = StopReason.CONFLICTED_EVIDENCE
        if not model_error and len(steps) > self.policy.max_steps:
            stop = StopReason.BUDGET_EXCEEDED
        updates = {
            "steps": steps[: self.step_budget],
            "tool_calls": tool_calls,
            "stop_reason": stop,
            "finished_at": utcnow(),
        }
        result_evidence_id: str | None = None
        if (
            event.event_type is EventType.LAB_RESULT_CREATED
            and loop_id
            and lab_verified
            and stop is StopReason.WAITING_EXTERNAL_EVENT
        ):
            existing_evidence = next(
                (
                    node
                    for node in self.memory.evidence.values()
                    if node.patient_id == event.patient_id
                    and node.encounter_id in {None, event.encounter_id}
                    and node.source_type == "LABS"
                    and node.source_id == event.payload_ref
                    and node.provenance.get("event_id") == event.event_id
                ),
                None,
            )
            if existing_evidence is None:
                existing_evidence = EvidenceNode(
                    evidence_id=new_id("EVD"),
                    patient_id=event.patient_id,
                    encounter_id=event.encounter_id,
                    source_type="LABS",
                    source_id=event.payload_ref,
                    observed_at=event.source_time,
                    claim=f"Lab result recorded for {event.payload.get('panel', 'unspecified panel')}.",
                    provenance={"event_id": event.event_id, "loop_id": loop_id},
                    trust_level=TrustLevel.SYSTEM_VERIFIED,
                    verified_at=event.source_time,
                )
                self.memory.append_evidence(existing_evidence, loop_id=loop_id)
            result_evidence_id = existing_evidence.evidence_id
        if (
            event.event_type is EventType.PROGRESS_NOTE_CREATED
            and loop_id
            and stop is StopReason.WAITING_EXTERNAL_EVENT
            and match_acknowledged_loop(
                event,
                self.memory.events,
                self.memory.loops.values(),
                self.memory.evidence.values(),
            )
        ):
            acknowledgement = next(
                (
                    node
                    for node in self.memory.evidence.values()
                    if node.provenance.get("event_id") == event.event_id
                    and node.provenance.get("loop_id") == loop_id
                    and node.source_type == "PROGRESS_NOTES"
                ),
                None,
            )
            if acknowledgement is None:
                acknowledgement = EvidenceNode(
                    evidence_id=new_id("EVD"),
                    patient_id=event.patient_id,
                    encounter_id=event.encounter_id,
                    source_type="PROGRESS_NOTES",
                    source_id=event.payload_ref,
                    observed_at=event.source_time,
                    claim="Clinician note explicitly acknowledged the linked lab result.",
                    provenance={
                        "event_id": event.event_id,
                        "acknowledges_event_id": event.payload["acknowledges_event_id"],
                        "loop_id": loop_id,
                    },
                    trust_level=TrustLevel.CLINICIAN_CONFIRMED,
                    verified_at=event.source_time,
                )
                self.memory.append_evidence(acknowledgement, loop_id=loop_id)
        if (
            event.event_type is EventType.LAB_RESULT_CREATED
            and loop_id
            and stop
            not in {
                StopReason.BUDGET_EXCEEDED,
                StopReason.MODEL_ERROR,
                StopReason.CONFLICTED_EVIDENCE,
            }
            and lab_verified
            and result_evidence_id is not None
            and not has_explicit_ack(event, [*self.memory.events, *tool_records])
        ):
            finding = Finding(
                finding_id=new_id("FND"),
                patient_id=event.patient_id,
                loop_id=loop_id,
                intent_id=run.intent_id,
                finding_type=FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
                claim="A lab result was found without a recorded acknowledgement in the searched workflow records.",
                supporting_evidence=[result_evidence_id],
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
