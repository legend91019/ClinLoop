"""Measure the database-backed result-follow-up Worker on synthetic cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from apps.api.app.settings import Settings
from apps.worker.worker.providers import MockProvider, build_model_provider
from eval.online.cases import online_cases
from eval.online.runtime import RulesOnlyProvider, run_case
from eval.online.scoring import score_case, summarize
from eval.run_eval import _atomic_write


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("compare", "rules", "mock", "deepseek"),
        default="compare",
        help="compare runs rules and deterministic MOCK; DeepSeek requires explicit opt-in",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/eval/online-report.json"))
    options = parser.parse_args(argv)

    if options.provider == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print("DEEPSEEK_API_KEY is required for real inference.", file=sys.stderr)
        return 2
    providers = {"rules": RulesOnlyProvider}
    if options.provider in {"compare", "mock"}:
        providers["mock"] = MockProvider
    if options.provider == "deepseek":
        providers["deepseek"] = lambda: build_model_provider(
            Settings(_env_file=None, agent_provider="deepseek")
        )
    if options.provider == "mock":
        providers.pop("rules")

    cases = online_cases()
    methods = {}
    try:
        for name, factory in providers.items():
            provider = factory()
            scores = [
                score_case(expected_alert=case.expected_alert, observed=run_case(case, provider))
                for case in cases
            ]
            methods[name] = {
                "provider_kind": "real" if name == "deepseek" else name,
                "model": provider.metadata.model if name == "deepseek" else None,
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
            "methods": methods,
            "limitations": [
                "Small synthetic engineering corpus; no clinical effectiveness claim.",
                "Rules uses the production Worker with no model intent proposal.",
                "Mock is deterministic test code, not LLM inference.",
                "Only RESULT_WITHOUT_ACKNOWLEDGEMENT is assessed online.",
                "Provider failures remain in the recall denominator.",
            ],
        }
        _atomic_write(options.output, json.dumps(report, indent=2, sort_keys=True) + "\n", ".json")
    except Exception as exc:
        print(
            f"Online evaluation failed ({type(exc).__name__}); no response body logged.",
            file=sys.stderr,
        )
        return 1
    print(f"Evaluated {len(cases)} synthetic online cases; methods={','.join(methods)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
