from __future__ import annotations

from pathlib import Path

from scripts.check_demo_ready import check_demo_ready


def test_demo_package_is_ready() -> None:
    report = Path("artifacts/eval/report.json")
    assert report.exists(), "generate the fixed evaluation report before running demo checks"
    checks = check_demo_ready(report)
    assert checks["event_count"] == 4
    assert checks["replan_parent"] is True
    assert checks["methods"] == ["ClinLoop", "direct_llm", "rag_template", "rule_engine"]
