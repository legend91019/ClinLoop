"""Replay synthetic cases through the production database-backed Worker."""

from __future__ import annotations

from apps.api.app.db import build_engine, create_schema, session_scope
from apps.api.app.repositories import (
    ClinicalEventRepository,
    EvidenceRepository,
    FindingRepository,
    PatientRepository,
)
from apps.worker.worker.agent import WorkflowAgent
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import ModelProvider, ProviderMetadata
from apps.worker.worker.service import process_event
from eval.online.cases import OnlineCase
from eval.online.scoring import ObservedCase
from packages.contracts import EventType, FindingType, StopReason, TrustLevel


class RulesOnlyProvider:
    """Return no model intent so the Worker's existing rule extractor is used."""

    kind = "mock"
    evaluation_kind = "rules"
    name = "rules-only"
    metadata = ProviderMetadata(provider="rules-only", model="none")

    def analyze(self, context: AgentContext) -> AgentProposal:
        return AgentProposal(
            patient_id=context.event.patient_id,
            intent_type=None,
            goal="Review visible workflow records",
            rationale="No model proposal; use existing deterministic intent extraction.",
            confidence=0.0,
        )


def run_case(case: OnlineCase, provider: ModelProvider) -> ObservedCase:
    """Use an isolated in-memory database; only events cross the Worker boundary."""
    engine = build_engine("sqlite+pysqlite:///:memory:")
    try:
        create_schema(engine)
        with session_scope(engine) as session:
            PatientRepository(session).ensure(
                patient_id=case.patient_id,
                encounter_id=case.events[0].encounter_id,
                display_name=f"Synthetic {case.patient_id}",
                ward="SYNTH",
            )
        agent = WorkflowAgent(provider=provider)
        runs = []
        for event in case.events:
            with session_scope(engine) as session:
                ClinicalEventRepository(session).add(event)
                runs.append(process_event(session, agent, event))
        with session_scope(engine) as session:
            findings = [
                finding
                for finding in FindingRepository(session).list_for_patient(case.patient_id)
                if finding.finding_type is FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT
            ]
            evidence = {
                node.evidence_id: node
                for node in EvidenceRepository(session).list_for_patient(case.patient_id)
            }
        labs = {
            event.event_id: event
            for event in case.events
            if event.event_type is EventType.LAB_RESULT_CREATED
        }
        valid_count = 0
        for finding in findings:
            valid = bool(finding.supporting_evidence)
            for evidence_id in finding.supporting_evidence:
                node = evidence.get(evidence_id)
                source_event = labs.get(node.provenance.get("event_id")) if node else None
                valid = valid and bool(
                    node
                    and source_event
                    and node.patient_id == case.patient_id
                    and node.encounter_id == source_event.encounter_id
                    and node.source_type == "LABS"
                    and node.source_id == source_event.payload_ref
                    and node.provenance.get("loop_id") == finding.loop_id
                    and node.trust_level is TrustLevel.SYSTEM_VERIFIED
                    and node.observed_at <= finding.detected_at
                )
            valid_count += int(valid)
        return ObservedCase(
            case_id=case.case_id,
            provider_kind=getattr(provider, "evaluation_kind", provider.kind),
            alert_count=len(findings),
            valid_evidence_count=valid_count,
            model_errors=sum(run.stop_reason is StopReason.MODEL_ERROR for run in runs),
            tool_calls=sum(len(run.tool_calls) for run in runs),
        )
    finally:
        engine.dispose()
