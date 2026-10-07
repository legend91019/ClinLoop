# ruff: noqa: E402
"""Check the synthetic demo package before a release."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

# Running ``python scripts/check_demo_ready.py`` puts only ``scripts/`` on
# sys.path; add the repository root so the monorepo packages resolve too.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.app.db import build_engine, create_schema, session_scope
from apps.api.app.repositories import EvidenceRepository
from apps.worker.worker.agent import WorkflowAgent
from packages.contracts import EventType
from packages.fixtures import main_case_events
from scripts.run_demo import run_demo


def check_demo_ready(report_path: Path) -> dict[str, object]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    required_methods = {"direct_llm", "rag_template", "rule_engine", "ClinLoop"}
    if set(report.get("methods", {})) != required_methods:
        raise ValueError("evaluation report must contain all four methods")

    with tempfile.TemporaryDirectory(prefix="clinloop-demo-") as directory:
        engine = build_engine(f"sqlite+pysqlite:///{Path(directory) / 'demo.sqlite3'}")
        create_schema(engine)
        result = run_demo("P-1001", engine=engine, auto_review=False)
        finding_evidence = {
            evidence
            for finding in result["findings"]
            for evidence in finding["supporting_evidence"]
        }
        with session_scope(engine) as session:
            evidence_source_ids = {
                node.source_id
                for evidence_id in finding_evidence
                if (node := EvidenceRepository(session).get(evidence_id)) is not None
            }
        engine.dispose()

    events = main_case_events()
    agent = WorkflowAgent()
    first = agent.handle_event(events[0])
    resumed = agent.resume_loop("LOOP-1001", events[1])
    replanned = agent.replan(resumed.run_id, ["EVD-1002"])
    checks = {
        "case": "P-1001",
        "event_count": len(result["events"]),
        "agent_runs": len(agent.runs.all()),
        "replan_parent": replanned.resumed_from_run_id == resumed.run_id,
        "finding_present": bool(result["findings"]),
        "lab_evidence_present": "LAB-8821" in evidence_source_ids,
        "handoff_loops": result["loop_ids"],
        "methods": sorted(report["methods"]),
    }
    if checks["event_count"] != 4 or first.run_id == resumed.run_id:
        raise ValueError("canonical demo did not produce the expected event/run sequence")
    if not checks["replan_parent"] or not checks["finding_present"]:
        raise ValueError("resume/re-plan evidence is incomplete")
    if EventType.LAB_RESULT_CREATED.value not in {item["event_type"] for item in result["events"]}:
        raise ValueError("canonical LAB_RESULT_CREATED event is missing")
    if not checks["lab_evidence_present"] or "LOOP-1002" not in result["loop_ids"]:
        raise ValueError("handoff/finding evidence is incomplete")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("artifacts/eval/report.json"))
    args = parser.parse_args()
    checks = check_demo_ready(args.report)
    print(json.dumps(checks, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
