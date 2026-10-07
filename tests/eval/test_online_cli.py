import json

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


def test_online_report_is_reproducible(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert main(["--output", str(first)]) == 0
    assert main(["--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()
