"""Strict, minimal contracts exchanged with an optional model provider."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from packages.contracts import (
    ClinicalEvent,
    ClinicalIntent,
    EventType,
    EvidenceNode,
    IntentType,
    OpenLoop,
)
from packages.contracts.models import StrictModel

__all__ = ["AgentContext", "AgentProposal"]


class AgentContext(StrictModel):
    """Only the workflow records visible at the current event time."""

    event: ClinicalEvent
    current_loop: OpenLoop | None = None
    current_intent: ClinicalIntent | None = None
    recent_events: list[ClinicalEvent] = Field(default_factory=list)
    visible_evidence: list[EvidenceNode] = Field(default_factory=list)


class AgentProposal(StrictModel):
    """A model suggestion that still requires deterministic validation."""

    patient_id: str
    intent_type: IntentType | None = None
    goal: str
    rationale: str
    expected_evidence: list[str] = Field(default_factory=list)
    waiting_for: list[EventType] = Field(default_factory=list)
    priority: Literal["LOW", "NORMAL", "HIGH", "CRITICAL"] = "NORMAL"
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
