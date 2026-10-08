"""Measure the database-backed result-follow-up Worker on synthetic cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from apps.api.app.settings import Settings
from apps.worker.worker.providers import MockProvider, build_model_provider
from eval.online.cases import contest_cases, online_cases
from eval.online.runtime import RulesOnlyProvider, run_case
from eval.online.scoring import score_case, summarize
from eval.run_eval import _atomic_write


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("compare", "rules", "mock", "deepseek", "agentarts"),
        default="compare",
        help="compare runs rules and deterministic MOCK; DeepSeek requires explicit opt-in",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--corpus",
        choices=("smoke-v1", "contest-v1"),
        default="smoke-v1",
        help="the fixed six-case smoke set or the 50-case contest engineering set",
    )
    parser.add_argument(
        "--assert-regression",
        action="store_true",
        help="fail if the fixed six-case rules baseline loses sourced detections or gains false alerts",
    )
    parser.add_argument(
        "--assert-contest-target",
        action="store_true",
        help="fail unless the published AgentArts runtime meets all preregistered contest gates",
    )
    options = parser.parse_args(argv)
    output = options.output or Path(
        f"artifacts/eval/{options.provider}-online-local.json"
        if options.provider in {"deepseek", "agentarts"}
        else "artifacts/eval/online-report.json"
    )

    if options.assert_regression and (
        options.provider != "compare" or options.corpus != "smoke-v1"
    ):
        print("--assert-regression requires the default compare mode.", file=sys.stderr)
        return 2
    if options.assert_contest_target and (
        options.provider != "agentarts" or options.corpus != "contest-v1"
    ):
        print("--assert-contest-target requires AgentArts on contest-v1.", file=sys.stderr)
        return 2

    if options.provider == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print("DEEPSEEK_API_KEY is required for real inference.", file=sys.stderr)
        return 2
    if options.provider == "agentarts" and not all(
        os.environ.get(key, "").strip()
        for key in ("AGENTARTS_ENDPOINT", "AGENTARTS_RUNTIME_NAME", "AGENTARTS_API_KEY")
    ):
        print(
            "AGENTARTS_ENDPOINT, AGENTARTS_RUNTIME_NAME and AGENTARTS_API_KEY are required.",
            file=sys.stderr,
        )
        return 2
    providers = {"rules": RulesOnlyProvider}
    if options.provider in {"compare", "mock"}:
        providers["mock"] = MockProvider
    if options.provider == "deepseek":
        providers["deepseek"] = lambda: build_model_provider(
            Settings(_env_file=None, agent_provider="deepseek")
        )
    if options.provider == "agentarts":
        providers["agentarts"] = lambda: build_model_provider(
            Settings(_env_file=None, agent_provider="agentarts")
        )
    if options.provider == "mock":
        providers.pop("rules")

    cases = online_cases() if options.corpus == "smoke-v1" else contest_cases()
    corpus_payload = [
        {
            "case_id": case.case_id,
            "cohort": case.cohort,
            "expected_alert": case.expected_alert,
            "events": [event.model_dump(mode="json") for event in case.events],
        }
        for case in cases
    ]
    corpus_sha256 = hashlib.sha256(
        json.dumps(corpus_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    methods = {}
    try:
        for name, factory in providers.items():
            provider = factory()
            scores = [
                score_case(expected_alert=case.expected_alert, observed=run_case(case, provider))
                for case in cases
            ]
            methods[name] = {
                "provider_kind": "real" if name in {"deepseek", "agentarts"} else name,
                "model": provider.metadata.model if name in {"deepseek", "agentarts"} else None,
                "metrics": summarize(scores),
                "cases": [
                    {"cohort": case.cohort, **asdict(score)}
                    for case, score in zip(cases, scores, strict=True)
                ],
            }
        report = {
            "schema_version": "1.0",
            "synthetic_only": True,
            "scope": "result_followup_only",
            "case_count": len(cases),
            "corpus": options.corpus,
            "positive_cases": sum(case.expected_alert for case in cases),
            "negative_cases": sum(not case.expected_alert for case in cases),
            "corpus_sha256": corpus_sha256,
            "methods": methods,
            "limitations": [
                "Small synthetic engineering corpus; no clinical effectiveness claim.",
                "Rules uses the production Worker with no model intent proposal.",
                "Mock is deterministic test code, not LLM inference.",
                "Only RESULT_WITHOUT_ACKNOWLEDGEMENT is assessed online.",
                "Provider failures remain in the recall denominator.",
            ],
        }
        if options.provider in {"deepseek", "agentarts"}:
            report["run_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )
            report["git_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
        if options.provider == "agentarts":
            metrics = methods["agentarts"]["metrics"]
            report["contest_target"] = {
                "recall_at_least": 0.95,
                "precision_at_least": 0.90,
                "false_alert_rate_at_most": 0.10,
                "evidence_validity_rate": 1.0,
                "passed": (
                    metrics["recall"] >= 0.95
                    and metrics["precision"] >= 0.90
                    and metrics["false_alert_rate"] <= 0.10
                    and metrics["evidence_validity_rate"] == 1.0
                    and metrics["model_errors"] == 0
                ),
            }
        if options.assert_regression:
            baseline = methods["rules"]["metrics"]
            if not (
                baseline["cases"] == 6
                and baseline["tp"] >= 2
                and baseline["fp"] == 0
                and baseline["fn"] <= 1
                and baseline["model_errors"] == 0
            ):
                print(
                    "Online rules regression floor failed; prior report preserved.", file=sys.stderr
                )
                return 1
        _atomic_write(output, json.dumps(report, indent=2, sort_keys=True) + "\n", ".json")
    except Exception as exc:
        print(
            f"Online evaluation failed ({type(exc).__name__}); no response body logged.",
            file=sys.stderr,
        )
        return 1
    print(f"Evaluated {len(cases)} synthetic online cases; methods={','.join(methods)}")
    if options.assert_contest_target and not report["contest_target"]["passed"]:
        print(
            "Published AgentArts runtime did not meet contest targets; report saved.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
