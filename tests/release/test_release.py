from __future__ import annotations

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


def test_security_gate_passes() -> None:
    assert main(["--security-only"]) == 0
