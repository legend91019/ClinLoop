"""Export the frozen synthetic inputs, labels and existing reports for teammates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

from eval.online.cases import OnlineCase, contest_cases, online_cases

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs/handoff/clinloop-synthetic-data-v1.zip"


def _corpus_files(name: str, cases: list[OnlineCase]) -> tuple[dict[str, bytes], dict]:
    inputs = [
        {
            "case_id": case.case_id,
            "patient_id": case.patient_id,
            "events": [event.model_dump(mode="json") for event in case.events],
        }
        for case in cases
    ]
    labels = [
        {
            "case_id": case.case_id,
            "cohort": case.cohort,
            "expected_alert": case.expected_alert,
            "events": [event.model_dump(mode="json") for event in case.events],
        }
        for case in cases
    ]
    corpus_sha256 = hashlib.sha256(
        json.dumps(labels, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    input_bytes = (
        "\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in inputs) + "\n"
    ).encode("utf-8")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=("case_id", "cohort", "expected_alert"),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(
        {
            "case_id": case.case_id,
            "cohort": case.cohort,
            "expected_alert": str(case.expected_alert).lower(),
        }
        for case in cases
    )
    files = {
        f"data/{name}-inputs.jsonl": input_bytes,
        f"labels/{name}-labels.csv": output.getvalue().encode("utf-8"),
    }
    metadata = {
        "cases": len(cases),
        "positive_cases": sum(case.expected_alert for case in cases),
        "negative_cases": sum(not case.expected_alert for case in cases),
        "sha256": corpus_sha256,
    }
    return files, metadata


def build_archive(output: Path = DEFAULT_OUTPUT) -> None:
    """Write the same archive bytes for the same repository files and corpus code."""
    files = {
        "README.md": (ROOT / "docs/handoff/data-package.md").read_bytes(),
        "reports/contest-rules-report.json": (
            ROOT / "artifacts/eval/contest-rules-report.json"
        ).read_bytes(),
        "reports/online-report.json": (ROOT / "artifacts/eval/online-report.json").read_bytes(),
        "reports/offline-report.json": (ROOT / "artifacts/eval/report.json").read_bytes(),
        "reports/comparison.csv": (ROOT / "artifacts/eval/comparison.csv").read_bytes(),
        "knowledge/knowledge-sop-v1.md": (ROOT / "docs/agentarts/knowledge-sop-v1.md").read_bytes(),
    }
    corpora = {}
    for name, cases in (("contest-v1", contest_cases()), ("smoke-v1", online_cases())):
        corpus_files, corpora[name] = _corpus_files(name, cases)
        files.update(corpus_files)
    manifest = {
        "schema_version": "1.0",
        "synthetic_only": True,
        "source_of_truth": "eval/online/cases.py and tracked artifacts/eval reports",
        "corpora": corpora,
        "file_sha256": {
            name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())
        },
    }
    files["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build_archive(parser.parse_args().output)
