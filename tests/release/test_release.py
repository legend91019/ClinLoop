from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.verify_release import main


def test_release_dry_run_lists_all_required_gates(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    for gate in (
        "backend tests",
        "frontend tests",
        "frontend build",
        "evaluation report",
        "online evaluation report",
        "demo readiness",
        "security scan",
    ):
        assert gate in output
    assert "--assert-regression" in output


def test_security_gate_passes() -> None:
    assert main(["--security-only"]) == 0


def test_real_model_evaluation_report_is_ignored() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "artifacts/eval/deepseek-online-local.json"],
        cwd=root,
        check=False,
    )
    assert result.returncode == 0
