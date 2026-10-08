import json

from apps.worker.worker.providers import MockProvider, ProviderMetadata
from eval.online.scoring import ObservedCase
from eval.run_online_eval import main


def test_default_report_compares_rules_with_explicit_mock(tmp_path) -> None:
    output = tmp_path / "online.json"

    assert main(["--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["synthetic_only"] is True
    assert report["scope"] == "result_followup_only"
    assert set(report["methods"]) == {"rules", "mock"}
    assert report["methods"]["rules"]["provider_kind"] == "rules"
    assert report["methods"]["mock"]["provider_kind"] == "mock"
    assert report["methods"]["rules"]["metrics"]["cases"] == 6
    assert "api_key" not in output.read_text(encoding="utf-8").lower()
    assert "今天复查" not in output.read_text(encoding="utf-8")


def test_real_mode_requires_environment_key_before_writing(tmp_path, monkeypatch) -> None:
    output = tmp_path / "online.json"
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert main(["--provider", "deepseek", "--output", str(output)]) == 2

    assert not output.exists()


def test_agentarts_mode_requires_runtime_configuration(tmp_path, monkeypatch) -> None:
    output = tmp_path / "agentarts.json"
    for key in ("AGENTARTS_ENDPOINT", "AGENTARTS_RUNTIME_NAME", "AGENTARTS_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    assert main(["--provider", "agentarts", "--output", str(output)]) == 2
    assert not output.exists()


def test_agentarts_report_keeps_provenance_and_separate_output(tmp_path, monkeypatch) -> None:
    class TestAgentArtsProvider(MockProvider):
        kind = "real"

        def __init__(self) -> None:
            super().__init__()
            self.metadata = ProviderMetadata(provider="agentarts", model="agent-arts-test")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTARTS_ENDPOINT", "https://agentarts.example.cn")
    monkeypatch.setenv("AGENTARTS_RUNTIME_NAME", "agent-arts-test")
    monkeypatch.setenv("AGENTARTS_API_KEY", "test-only-value")
    monkeypatch.setattr(
        "eval.run_online_eval.build_model_provider", lambda _settings: TestAgentArtsProvider()
    )

    assert main(["--provider", "agentarts"]) == 0

    output = tmp_path / "artifacts/eval/agentarts-online-local.json"
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["methods"]["agentarts"]["provider_kind"] == "real"
    assert report["methods"]["agentarts"]["model"] == "agent-arts-test"
    assert report["methods"]["agentarts"]["metrics"]["cases"] == 6
    assert len(report["corpus_sha256"]) == 64
    assert report["run_at_utc"].endswith("Z")
    assert not (tmp_path / "artifacts/eval/online-report.json").exists()
    assert "test-only-value" not in output.read_text(encoding="utf-8")


def test_contest_corpus_report_has_explicit_denominator(tmp_path) -> None:
    output = tmp_path / "contest.json"

    assert main(["--provider", "rules", "--corpus", "contest-v1", "--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["corpus"] == "contest-v1"
    assert report["case_count"] == 50
    assert report["positive_cases"] == 25
    assert report["negative_cases"] == 25
    assert len(report["corpus_sha256"]) == 64


def test_contest_target_rejects_non_agentarts_and_preserves_prior_report(tmp_path) -> None:
    output = tmp_path / "prior.json"
    output.write_text("prior", encoding="utf-8")

    assert (
        main(
            [
                "--provider",
                "rules",
                "--corpus",
                "contest-v1",
                "--assert-contest-target",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_text(encoding="utf-8") == "prior"


def test_real_mode_default_output_does_not_replace_committed_mock_report(
    tmp_path, monkeypatch
) -> None:
    class TestRealProvider(MockProvider):
        kind = "real"
        metadata = ProviderMetadata(provider="test-real", model="test-real")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-value")
    monkeypatch.setattr(
        "eval.run_online_eval.build_model_provider", lambda _settings: TestRealProvider()
    )

    assert main(["--provider", "deepseek"]) == 0

    assert (tmp_path / "artifacts/eval/deepseek-online-local.json").exists()
    assert not (tmp_path / "artifacts/eval/online-report.json").exists()


def test_online_report_is_reproducible(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert main(["--output", str(first)]) == 0
    assert main(["--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()


def test_release_assertion_rejects_all_miss_regression_without_overwriting(
    tmp_path, monkeypatch
) -> None:
    output = tmp_path / "online.json"
    output.write_text("prior report", encoding="utf-8")

    def all_miss(case, provider):
        return ObservedCase(case.case_id, getattr(provider, "evaluation_kind", "mock"), 0, 0, 0, 0)

    monkeypatch.setattr("eval.run_online_eval.run_case", all_miss)

    assert main(["--assert-regression", "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "prior report"


def test_release_assertion_accepts_current_rule_regression_floor(tmp_path) -> None:
    output = tmp_path / "online.json"

    assert main(["--assert-regression", "--output", str(output)]) == 0

    assert output.exists()
