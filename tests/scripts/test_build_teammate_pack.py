"""The shared handoff archive must be reproducible and keep gold labels separate."""

import csv
import hashlib
import io
import json
import zipfile

from scripts.build_teammate_pack import build_archive


def test_handoff_archive_has_separate_inputs_labels_and_provenance(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build_archive(first)
    build_archive(second)
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert {
            "README.md",
            "manifest.json",
            "data/contest-v1-inputs.jsonl",
            "labels/contest-v1-labels.csv",
            "data/smoke-v1-inputs.jsonl",
            "labels/smoke-v1-labels.csv",
            "reports/contest-rules-report.json",
            "reports/online-report.json",
            "reports/offline-report.json",
            "reports/comparison.csv",
            "knowledge/knowledge-sop-v1.md",
        } == names
        inputs = [
            json.loads(line)
            for line in archive.read("data/contest-v1-inputs.jsonl").decode().splitlines()
        ]
        labels = list(
            csv.DictReader(io.StringIO(archive.read("labels/contest-v1-labels.csv").decode()))
        )
        manifest = json.loads(archive.read("manifest.json"))
        assert set(manifest["file_sha256"]) == names - {"manifest.json"}
        assert all(
            hashlib.sha256(archive.read(name)).hexdigest() == digest
            for name, digest in manifest["file_sha256"].items()
        )

    assert len(inputs) == len(labels) == 50
    assert len({row["case_id"] for row in inputs}) == 50
    assert [row["case_id"] for row in inputs] == [row["case_id"] for row in labels]
    assert sum(row["expected_alert"] == "true" for row in labels) == 25
    assert all("expected_alert" not in row and "cohort" not in row for row in inputs)
    assert all("expected_alert" not in json.dumps(row["events"]) for row in inputs)
    assert manifest["corpora"]["contest-v1"]["sha256"] == (
        "b8780d14be703102e22c196706308a279e030ca2a4eb24d73d21b507f21dcd90"
    )
    assert manifest["corpora"]["contest-v1"]["positive_cases"] == 25
    assert manifest["corpora"]["contest-v1"]["negative_cases"] == 25
