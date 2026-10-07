from apps.worker.worker.agent import WorkflowAgent
from eval.models import FindingPrediction, HandlerResult, HandoffPrediction
from packages.contracts import EventType


class ClinLoopAdapter:
    provider_kind = "worker_runtime"
    limitations = [
        "Actual existing WorkflowAgent, in-memory runtime; no replacement detector or gold access.",
        "The conservative Worker requires a matched intent/loop; this context-free adapter has neither and abstains.",
        "Worker emits five step labels but no actual tool calls; trace tool_calls is honestly empty.",
        "Worker does not populate intent/loop/evidence memory or produce handoff content; omission remains measurable.",
        "This runtime has no model provider, durable transport, timer, autonomous resume routing or clinician review in eval.",
    ]

    def __init__(self):
        # Evaluation intentionally measures the existing worker behavior on
        # the visible event stream. Context materialization belongs to the
        # production runtime/demo path and must not create hidden gold access
        # for synthetic benchmark cases.
        self.agent = WorkflowAgent(materialize_context=False)

    def handle_event(self, event, context):
        # Only now-available events have reached this adapter. Do not preload
        # memory with the case, annotations or gold evidence.
        run = self.agent.handle_event(event)
        predictions = []
        for finding_id in run.finding_ids:
            finding = self.agent.findings[finding_id]
            # Bind an unbound worker finding to its trigger record's observable
            # item. This changes representation only, not detection behavior.
            predictions.append(
                FindingPrediction(
                    patient_id=finding.patient_id,
                    item_id=event.payload.get("item_id") or event.payload_ref,
                    finding_type=finding.finding_type,
                    evidence_ids=finding.supporting_evidence,
                    detected_at=context.as_of,
                    claim=finding.claim,
                    searched_sources=finding.searched_sources,
                )
            )
        return HandlerResult(
            runs=[run],
            tool_calls=run.tool_calls,
            findings=predictions,
            handoff=HandoffPrediction(
                patient_id=event.patient_id, item_ids=[], generated_at=context.as_of
            )
            if event.event_type == EventType.HANDOFF_STARTED
            else None,
        )

    def final_states(self):
        return {
            "loops": {k: v.model_dump(mode="json") for k, v in self.agent.memory.loops.items()},
            "intents": {k: v.model_dump(mode="json") for k, v in self.agent.memory.intents.items()},
            "evidence_ids": sorted(self.agent.memory.evidence),
            "recorded_event_ids": [e.event_id for e in self.agent.memory.events],
        }
