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
