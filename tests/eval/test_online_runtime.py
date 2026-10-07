from datetime import timedelta

from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import MockProvider, ModelProviderError, ProviderMetadata
from eval.online.cases import online_cases
from eval.online.runtime import RulesOnlyProvider, evidence_is_source_backed, run_case
from packages.contracts import EvidenceNode, Finding, FindingType


def test_rules_runtime_persists_sourced_alert_for_direct_note() -> None:
    observed = run_case(online_cases()[0], RulesOnlyProvider())

    assert observed.provider_kind == "rules"
    assert observed.alert_count == 1
    assert observed.valid_evidence_count == 1
    assert observed.tool_calls >= 2
    assert observed.model_errors == 0


def test_rules_runtime_misses_paraphrase_without_model_help() -> None:
    observed = run_case(online_cases()[1], RulesOnlyProvider())

    assert observed.alert_count == 0


def test_unrelated_result_does_not_create_alert() -> None:
    observed = run_case(online_cases()[4], RulesOnlyProvider())

    assert observed.alert_count == 0


def test_mock_runtime_is_explicitly_labeled() -> None:
    observed = run_case(online_cases()[3], MockProvider())

    assert observed.provider_kind == "mock"
    assert observed.alert_count == 1  # The deterministic mock over-interprets the note.


def test_provider_context_cannot_see_case_label() -> None:
    class CapturingProvider(RulesOnlyProvider):
        def __init__(self) -> None:
            self.contexts: list[AgentContext] = []

        def analyze(self, context: AgentContext) -> AgentProposal:
            self.contexts.append(context)
            return super().analyze(context)

    provider = CapturingProvider()
    run_case(online_cases()[0], provider)

    assert provider.contexts
    assert all("expected_alert" not in context.model_dump_json() for context in provider.contexts)
    assert all("cohort" not in context.model_dump_json() for context in provider.contexts)


def test_model_error_remains_visible_in_result() -> None:
    class FailingProvider:
        kind = "real"
        name = "failing-test-provider"
        metadata = ProviderMetadata(provider="failing-test-provider", model="test")

        def analyze(self, _context: AgentContext) -> AgentProposal:
            raise ModelProviderError("MODEL_TIMEOUT")

    observed = run_case(online_cases()[0], FailingProvider())

    assert observed.alert_count == 0
    assert observed.model_errors == 2


def test_evidence_check_rejects_cross_patient_and_future_source() -> None:
    case = online_cases()[0]
    lab = case.events[-1]
    finding = Finding(
        finding_id="FND-TEST",
        patient_id=case.patient_id,
        loop_id="LOOP-TEST",
        finding_type=FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
        claim="Result requires review",
        supporting_evidence=["EVD-TEST"],
        searched_sources=["LABS"],
        detected_at=lab.source_time + timedelta(minutes=1),
    )
    node = EvidenceNode(
        evidence_id="EVD-TEST",
        patient_id=case.patient_id,
        encounter_id=lab.encounter_id,
        source_type="LABS",
        source_id=lab.payload_ref,
        observed_at=lab.source_time,
        claim="Synthetic lab result",
        provenance={"event_id": lab.event_id, "loop_id": finding.loop_id},
    )
    assert evidence_is_source_backed(
        finding, {node.evidence_id: node}, {lab.event_id: lab}, case.patient_id
    )

    other_patient_lab = lab.model_copy(update={"patient_id": "P-OTHER"})
    assert not evidence_is_source_backed(
        finding, {node.evidence_id: node}, {lab.event_id: other_patient_lab}, case.patient_id
    )
    early_finding = finding.model_copy(
        update={"detected_at": lab.source_time - timedelta(minutes=1)}
    )
    assert not evidence_is_source_backed(
        early_finding, {node.evidence_id: node}, {lab.event_id: lab}, case.patient_id
    )
    backdated_node = node.model_copy(update={"observed_at": lab.source_time - timedelta(hours=1)})
    assert not evidence_is_source_backed(
        finding, {node.evidence_id: backdated_node}, {lab.event_id: lab}, case.patient_id
    )
