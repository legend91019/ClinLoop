from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from apps.worker.worker.providers import MockProvider, ModelProviderError, ProviderMetadata
from eval.online.cases import online_cases
from eval.online.runtime import RulesOnlyProvider, run_case


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
