"""Evaluation DTOs. Annotations never cross the EventHandler boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from packages.contracts import AgentRun, ClinicalEvent, EvidenceNode, FindingType, ToolCall
from packages.contracts.models import AwareDatetime, NonEmptyStr, StrictModel

GAP_TYPES = (
    FindingType.PLAN_WITHOUT_ORDER,
    FindingType.ORDER_WITHOUT_EXECUTION,
    FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
    FindingType.LOOP_MISSING_FROM_HANDOFF,
)


class Opportunity(StrictModel):
    item_id: NonEmptyStr
    finding_type: FindingType


class ExpectedGap(Opportunity):
    evidence_ids: list[NonEmptyStr]


class Annotation(StrictModel):
    defect_type: FindingType | None = None
    gaps: list[ExpectedGap] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    eligible_handoff_items: list[NonEmptyStr] = Field(default_factory=list)


class SyntheticCase(StrictModel):
    case_id: NonEmptyStr
    patient_id: NonEmptyStr
    synthetic: Literal[True] = True
    events: list[ClinicalEvent]
    evidence: list[EvidenceNode]
    annotation: Annotation

    @model_validator(mode="after")
    def validate_events(self):
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("duplicate event IDs")
        if any(e.patient_id != self.patient_id for e in self.events):
            raise ValueError("events belong to another patient")
        if len({e.evidence_id for e in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate evidence IDs")
        return self


class FindingPrediction(Opportunity):
    patient_id: NonEmptyStr
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    detected_at: AwareDatetime
    claim: str = "Requires review of the searched records."
    searched_sources: list[NonEmptyStr] = Field(default_factory=list)


class HandoffPrediction(StrictModel):
    patient_id: NonEmptyStr
    item_ids: list[NonEmptyStr] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    generated_at: AwareDatetime


class CasePrediction(StrictModel):
    patient_id: NonEmptyStr
    findings: list[FindingPrediction] = Field(default_factory=list)
    handoff: HandoffPrediction | None = None

    @model_validator(mode="after")
    def validate_patient(self):
        if any(f.patient_id != self.patient_id for f in self.findings):
            raise ValueError("cross-patient finding")
        if self.handoff and self.handoff.patient_id != self.patient_id:
            raise ValueError("cross-patient handoff")
        return self


class VisibleContext(StrictModel):
    patient_id: NonEmptyStr
    as_of: AwareDatetime
    available_at: AwareDatetime
    events: list[ClinicalEvent]
    evidence: list[EvidenceNode]


class HandlerResult(StrictModel):
    runs: list[AgentRun] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    findings: list[FindingPrediction] = Field(default_factory=list)
    handoff: HandoffPrediction | None = None
    model_calls: list[dict[str, Any]] = Field(default_factory=list)


class ReplayResult(StrictModel):
    patient_id: NonEmptyStr
    event_ids: list[NonEmptyStr]
    runs: list[AgentRun]
    tool_calls: list[ToolCall]
    model_calls: list[dict[str, Any]]
    prediction: CasePrediction
    final_states: dict[str, Any]
