from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from packages.contracts import ActorRef, ClinicalEvent, EventType, IntentType


def _event() -> ClinicalEvent:
    now = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
    return ClinicalEvent(
        event_id="EVT-MODEL-1",
        patient_id="P-1001",
        encounter_id="ENC-2001",
        event_type=EventType.NOTE_CREATED,
        event_time=now,
        source_time=now,
        payload_ref="NOTE-MODEL-1",
        actor=ActorRef(actor_id="DR-TEST", role="PHYSICIAN"),
        payload={"text": "复查血培养"},
    )


def test_agent_proposal_accepts_structured_candidate() -> None:
    proposal = AgentProposal(
        patient_id="P-1001",
        intent_type=IntentType.FOLLOW_RESULT,
        goal="Follow up the blood culture result",
        rationale="The note explicitly asks for a result follow-up.",
        expected_evidence=["blood_culture_result"],
        waiting_for=[EventType.LAB_RESULT_CREATED],
        priority="HIGH",
        confidence=0.91,
        evidence_refs=[],
    )

    assert proposal.model_dump(mode="json")["priority"] == "HIGH"
    assert proposal.patient_id == "P-1001"


def test_agent_context_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AgentContext(event=_event(), hidden_gold_label="RESULT_WITHOUT_ACKNOWLEDGEMENT")


@pytest.mark.parametrize(
    "field,value",
    [("priority", "URGENT"), ("confidence", 1.1), ("waiting_for", ["NOT_AN_EVENT"])],
)
def test_agent_proposal_rejects_untrusted_values(field: str, value: object) -> None:
    payload = {
        "patient_id": "P-1001",
        "intent_type": "FOLLOW_RESULT",
        "goal": "Follow up the result",
        "rationale": "The note contains a follow-up request.",
        "expected_evidence": ["blood_culture_result"],
        "waiting_for": ["LAB_RESULT_CREATED"],
        "priority": "HIGH",
        "confidence": 0.8,
        "evidence_refs": [],
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        AgentProposal.model_validate(payload)


def test_model_dump_has_no_secret_or_raw_prompt_fields() -> None:
    proposal = AgentProposal(
        patient_id="P-1001",
        intent_type=None,
        goal="Review the available result",
        rationale="The current context needs clinician confirmation.",
        expected_evidence=[],
        waiting_for=[],
        priority="NORMAL",
        confidence=0.5,
        evidence_refs=[],
    )

    dumped = proposal.model_dump()
    assert "api_key" not in dumped
    assert "prompt" not in dumped
