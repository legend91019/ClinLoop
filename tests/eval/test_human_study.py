from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta

from eval.run_human_study import analyze, main


def row(participant: str, task: str, mode: str, seconds: str, correct: str) -> dict:
    start = datetime(2026, 10, 8, tzinfo=UTC)
    return {
        "participant_id": participant,
        "task_id": task,
        "synthetic_case_id": f"CASE-{task}-{mode}",
        "mode": mode,
        "sequence_order": "1" if mode == "manual" else "2",
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "end_utc": (start + timedelta(seconds=float(seconds))).isoformat().replace("+00:00", "Z"),
        "duration_seconds": seconds,
        "correct_gap_identified": correct,
        "evidence_source_correct": "1",
        "false_accept": "0",
        "notes": "do not copy notes to report",
    }


def test_analysis_uses_paired_durations_and_reports_errors() -> None:
    rows = [
        row("P1", "T1", "manual", "100", "1"),
        row("P1", "T1", "clinloop", "60", "1"),
        row("P2", "T1", "manual", "80", "0"),
        row("P2", "T1", "clinloop", "50", "1"),
    ]

    report = analyze(rows)

    assert report["participants"] == 2
    assert report["paired_tasks"] == 2
    assert report["median_manual_seconds"] == 90.0
    assert report["median_clinloop_seconds"] == 55.0
    assert report["median_paired_seconds_saved"] == 35.0
    assert report["correct_gap_rate"]["manual"] == 0.5
    assert report["correct_gap_rate"]["clinloop"] == 1.0
    assert "notes" not in json.dumps(report)


def test_analysis_rejects_unpaired_or_invalid_timing() -> None:
    only_manual = [row("P1", "T1", "manual", "100", "1")]
    try:
        analyze(only_manual)
    except ValueError as exc:
        assert "pair" in str(exc).lower()
    else:
        raise AssertionError("unpaired data accepted")

    invalid = [row("P1", "T1", "manual", "0", "1"), row("P1", "T1", "clinloop", "60", "1")]
    try:
        analyze(invalid)
    except ValueError as exc:
        assert "duration" in str(exc).lower()
    else:
        raise AssertionError("invalid duration accepted")


def test_cli_preserves_output_when_dataset_is_empty(tmp_path) -> None:
    source = tmp_path / "study.csv"
    output = tmp_path / "report.json"
    output.write_text("prior", encoding="utf-8")
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row("P1", "T1", "manual", "10", "1")))
        writer.writeheader()

    assert main(["--input", str(source), "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "prior"


def test_cli_writes_aggregate_only_and_input_digest(tmp_path) -> None:
    source = tmp_path / "study.csv"
    output = tmp_path / "report.json"
    records = [
        row("PRIVATE-P1", "T1", "manual", "100", "1"),
        row("PRIVATE-P1", "T1", "clinloop", "60", "1"),
    ]
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    assert main(["--input", str(source), "--output", str(output)]) == 0

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["median_paired_seconds_saved"] == 40.0
    assert len(report["input_sha256"]) == 64
    assert "PRIVATE-P1" not in output.read_text(encoding="utf-8")
    assert "do not copy notes" not in output.read_text(encoding="utf-8")
