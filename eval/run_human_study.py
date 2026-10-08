"""Analyze actual paired synthetic-workflow timing observations, never generate them."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from eval.run_eval import _atomic_write

REQUIRED_FIELDS = {
    "participant_id",
    "task_id",
    "synthetic_case_id",
    "mode",
    "sequence_order",
    "start_utc",
    "end_utc",
    "duration_seconds",
    "correct_gap_identified",
    "evidence_source_correct",
    "false_accept",
}


def _binary(value: str, field: str) -> int:
    if value not in {"0", "1"}:
        raise ValueError(f"{field} must be 0 or 1")
    return int(value)


def _validated_row(row: dict[str, str]) -> dict:
    if not REQUIRED_FIELDS.issubset(row):
        raise ValueError("missing required study columns")
    if not row["participant_id"].strip() or not row["task_id"].strip():
        raise ValueError("participant_id and task_id are required")
    if not row["synthetic_case_id"].strip():
        raise ValueError("synthetic_case_id is required")
    if row["mode"] not in {"manual", "clinloop"}:
        raise ValueError("mode must be manual or clinloop")
    duration = float(row["duration_seconds"])
    if not 0 < duration < 3600:
        raise ValueError("duration_seconds must be between 0 and 3600")
    start = datetime.fromisoformat(row["start_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(row["end_utc"].replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timestamps must include a UTC offset")
    if abs((end - start).total_seconds() - duration) > 1:
        raise ValueError("duration_seconds disagrees with timestamps")
    sequence_order = int(row["sequence_order"])
    if sequence_order not in {1, 2}:
        raise ValueError("sequence_order must be 1 or 2")
    return {
        "participant_id": row["participant_id"].strip(),
        "task_id": row["task_id"].strip(),
        "mode": row["mode"],
        "duration_seconds": duration,
        "sequence_order": sequence_order,
        "correct_gap_identified": _binary(row["correct_gap_identified"], "correct_gap_identified"),
        "evidence_source_correct": _binary(
            row["evidence_source_correct"], "evidence_source_correct"
        ),
        "false_accept": _binary(row["false_accept"], "false_accept"),
    }


def analyze(rows: list[dict[str, str]]) -> dict:
    """Aggregate complete within-participant task pairs; return no participant-level data."""
    if not rows:
        raise ValueError("no study observations")
    pairs: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for raw in rows:
        row = _validated_row(raw)
        key = (row["participant_id"], row["task_id"])
        if row["mode"] in pairs[key]:
            raise ValueError("duplicate participant/task/mode observation")
        pairs[key][row["mode"]] = row
    if any(set(pair) != {"manual", "clinloop"} for pair in pairs.values()):
        raise ValueError("each participant/task must have a manual and clinloop pair")
    if any(
        pair["manual"]["sequence_order"] == pair["clinloop"]["sequence_order"]
        for pair in pairs.values()
    ):
        raise ValueError("paired modes need different sequence_order values")

    manual = [pair["manual"] for pair in pairs.values()]
    assisted = [pair["clinloop"] for pair in pairs.values()]
    differences = [
        left["duration_seconds"] - right["duration_seconds"]
        for left, right in zip(manual, assisted, strict=True)
    ]
    relative = [
        (left["duration_seconds"] - right["duration_seconds"]) / left["duration_seconds"]
        for left, right in zip(manual, assisted, strict=True)
    ]
    return {
        "schema_version": "1.0",
        "synthetic_only": True,
        "exploratory_human_study": True,
        "participants": len({participant for participant, _ in pairs}),
        "paired_tasks": len(pairs),
        "manual_first_pairs": sum(pair["manual"]["sequence_order"] == 1 for pair in pairs.values()),
        "clinloop_first_pairs": sum(
            pair["clinloop"]["sequence_order"] == 1 for pair in pairs.values()
        ),
        "median_manual_seconds": median(row["duration_seconds"] for row in manual),
        "median_clinloop_seconds": median(row["duration_seconds"] for row in assisted),
        "median_paired_seconds_saved": median(differences),
        "median_paired_fraction_saved": median(relative),
        "correct_gap_rate": {
            "manual": sum(row["correct_gap_identified"] for row in manual) / len(manual),
            "clinloop": sum(row["correct_gap_identified"] for row in assisted) / len(assisted),
        },
        "evidence_source_correct_rate": {
            "manual": sum(row["evidence_source_correct"] for row in manual) / len(manual),
            "clinloop": sum(row["evidence_source_correct"] for row in assisted) / len(assisted),
        },
        "false_accept_rate": {
            "manual": sum(row["false_accept"] for row in manual) / len(manual),
            "clinloop": sum(row["false_accept"] for row in assisted) / len(assisted),
        },
        "limitations": [
            "Synthetic tasks and volunteers do not establish clinical effectiveness.",
            "Pairing by participant and task_id assumes matched task difficulty.",
            "Input observations require independent collection and verification.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args(argv)
    try:
        raw = options.input.read_bytes()
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        report = analyze(rows)
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
        report["run_at_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        _atomic_write(options.output, json.dumps(report, indent=2, sort_keys=True) + "\n", ".json")
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Human study analysis failed: {exc}; prior report preserved.", file=sys.stderr)
        return 1
    print(f"Analyzed {report['paired_tasks']} paired synthetic workflow tasks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
