from __future__ import annotations

from eval.baselines.providers import MockModelProvider, ModelProvider, validate_provider
from eval.models import CasePrediction, HandlerResult, VisibleContext
from packages.contracts import ClinicalEvent, EventType


class DirectLLM:
    method = "direct_llm"

    def __init__(self, provider: ModelProvider | None = None):
        self.provider = provider if provider is not None else MockModelProvider()
        validate_provider(self.provider)
        self.provider_kind = self.provider.kind
        self.limitations = (
            [
                "MOCK provider: deterministic abstention; no model inference or LLM-quality measurement."
            ]
            if self.provider.kind == "mock"
            else ["External model provider; reproducibility depends on provider/version/settings."]
        )
        self.limitations.append(
            "Handoff-time assessment only; no autonomous clinical state changes."
        )

    def build_request(self, context: VisibleContext):
        return {
            "method": self.method,
            "patient_id": context.patient_id,
            "as_of": context.as_of.isoformat(),
            "instruction": "Assess gaps in the visible workflow records; cite source IDs. Return CasePrediction JSON. Missing records are not proof of nonexistence. Do not diagnose, recommend treatment or close tasks.",
            "response_schema": CasePrediction.model_json_schema(),
            "records": [e.model_dump(mode="json") for e in context.events],
        }

    def handle_event(self, event: ClinicalEvent, context: VisibleContext) -> HandlerResult:
        if event.event_type != EventType.HANDOFF_STARTED:
            return HandlerResult()
        prediction = CasePrediction.model_validate(
            self.provider.generate(self.build_request(context))
        )
        if prediction.patient_id != context.patient_id:
            raise ValueError("provider returned another patient's predictions")
        if any(f.detected_at > context.as_of for f in prediction.findings):
            raise ValueError("provider returned future findings")
        if prediction.handoff and prediction.handoff.generated_at > context.as_of:
            raise ValueError("provider returned future handoff")
        return HandlerResult(
            findings=prediction.findings,
            handoff=prediction.handoff,
            model_calls=[
                {
                    "method": self.method,
                    "provider": self.provider.name,
                    "kind": self.provider.kind,
                    "trigger_event_id": event.event_id,
                    "record_count": len(context.events),
                }
            ],
        )

    def final_states(self):
        return {"clinical_state_changes": {}}
