"""Run from the repository root: python -m eval.run_eval --count 100 --seed 20260928."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from eval.baselines.providers import load_provider
from eval.generators.cases import generate_cases
from eval.metrics.report import run_all_methods
from eval.replay.replayer import canonicalize


def _atomic_write(path: Path, data: str, suffix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".eval-", suffix=suffix, dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None) -> int:
    # Support the compact --count100/--seed20260928 form in the task request
    # as well as conventional argparse whitespace and = syntax.
    args = []
    for token in sys.argv[1:] if argv is None else argv:
        match = re.fullmatch(r"--(count|seed)(-?\d+)", token)
        args.extend([f"--{match[1]}", match[2]] if match else [token])
    parser = argparse.ArgumentParser(
        description="Synthetic ClinLoop evaluation (default model provider: MOCK)"
    )
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--output", type=Path, default=Path("artifacts/eval/report.json"))
    parser.add_argument("--comparison-output", type=Path)
    parser.add_argument(
        "--provider",
        help="Optional explicitly configured model provider module:factory; declares kind mock/real",
    )
    options = parser.parse_args(args)
    try:
        cases = generate_cases(options.count, options.seed)
        provider = load_provider(options.provider) if options.provider else None
        report = run_all_methods(cases, provider, seed=options.seed)
        data = json.dumps(canonicalize(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        # Atomic replacement and restrictive local file permissions. No EHR
        # ingestion, credentials or external raw provider responses are stored.
        _atomic_write(options.output, data, ".json")
        if options.comparison_output is not None:
            summary = io.StringIO(newline="")
            writer = csv.writer(summary, lineterminator="\n")
            writer.writerow(
                [
                    "method",
                    "provider_kind",
                    "gap_recall",
                    "false_alarm_rate",
                    "evidence_coverage",
                    "handoff_omission_rate",
                    "model_calls",
                ]
            )
            for name in ("ClinLoop", "direct_llm", "rag_template", "rule_engine"):
                method = report.methods[name]
                writer.writerow(
                    [
                        name,
                        method.provider_kind,
                        method.metrics.gap_recall,
                        method.metrics.false_alarm_rate,
                        method.metrics.evidence_coverage,
                        method.metrics.handoff_omission_rate,
                        method.model_calls,
                    ]
                )
            _atomic_write(options.comparison_output, summary.getvalue(), ".csv")
    except Exception as exc:
        # Exceptions from external providers can contain credentials or raw
        # responses: report only exception type, not message/traceback.
        print(
            f"Evaluation failed ({type(exc).__name__}); no provider response or credentials logged.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Evaluated {options.count} synthetic cases; model provider={report.methods['direct_llm'].provider_kind}; report={options.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
