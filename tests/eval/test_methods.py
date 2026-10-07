import json
import subprocess
import sys

import pytest


def test_four_methods_replay_deterministically_and_report_mock_honestly(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.metrics.report import run_all_methods
    from eval.replay.replayer import canonicalize

    cases = generate_cases(7, 15)
    first = run_all_methods(cases)
    assert canonicalize(first) == canonicalize(run_all_methods(cases))
    assert set(first.methods) == {"direct_llm", "rag_template", "rule_engine", "ClinLoop"}
    for name in ("direct_llm", "rag_template"):
        assert first.methods[name].provider_kind == "mock"
        assert first.methods[name].model_calls > 0
        assert first.methods[name].limitations
    assert first.methods["ClinLoop"].provider_kind == "worker_runtime"
    assert first.methods["ClinLoop"].limitations
    assert first.methods["rule_engine"].provider_kind == "rules"
    assert first.methods["rule_engine"].metrics.gap_recall == 1.0
    assert first.methods["rule_engine"].metrics.false_alarm_rate == 0.0


@pytest.mark.parametrize("method", ["direct_llm", "rag_template", "rule_engine", "ClinLoop"])
def test_methods_are_blind_to_changed_annotations(api, method):
    assert api, "task11 evaluation API not implemented"
    from eval.baselines import make_handler
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import canonicalize, replay

    case = generate_cases(1, 42)[0]
    changed = case.model_copy(deep=True)
    changed.annotation.gaps = []
    changed.annotation.eligible_handoff_items = ["LEAK-MARKER"]
    changed.annotation.defect_type = "LOOP_MISSING_FROM_HANDOFF"
    assert canonicalize(replay(case, make_handler(method))) == canonicalize(
        replay(changed, make_handler(method))
    )


def test_model_provider_receives_visible_records_and_validates_returned_predictions(api):
    assert api, "task11 evaluation API not implemented"
    from eval.baselines.direct_llm import DirectLLM
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import replay

    class Provider:
        kind = "mock"
        name = "test-provider"

        def generate(self, request):
            assert "annotation" not in json.dumps(request)
            assert "defect_type" not in json.dumps(request)
            patient = request["patient_id"]
            item = request["records"][0]["payload"]["item_id"]
            return {
                "patient_id": patient,
                "findings": [],
                "handoff": {
                    "patient_id": patient,
                    "item_ids": [item],
                    "generated_at": request["as_of"],
                },
            }

    case = generate_cases(1, 42)[0]
    result = replay(case, DirectLLM(Provider()))
    assert result.prediction.handoff.item_ids == case.annotation.eligible_handoff_items
    assert result.model_calls[0]["provider"] == "test-provider"


def test_model_does_not_receive_unobservable_gold_evidence(api):
    assert api, "task11 evaluation API not implemented"
    from eval.baselines.direct_llm import DirectLLM
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import canonicalize, replay

    case = generate_cases(1, 42)[0]
    poisoned = case.model_copy(deep=True)
    poisoned.evidence[0].claim = "GOLD-SECRET-DO-NOT-OBSERVE"
    poisoned.evidence[0].evidence_id = "GOLD-SECRET-ID"
    assert canonicalize(replay(case, DirectLLM())) == canonicalize(replay(poisoned, DirectLLM()))


def test_cli_accepts_compact_flags_emits_reproducible_secure_report(api, tmp_path):
    assert api, "task11 evaluation API not implemented"
    outputs = [tmp_path / "a.json", tmp_path / "b.json"]
    summaries = [tmp_path / "a.csv", tmp_path / "b.csv"]
    for path, summary in zip(outputs, summaries, strict=True):
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "eval.run_eval",
                "--count100",
                "--seed20260928",
                "--output",
                str(path),
                "--comparison-output",
                str(summary),
            ],
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stderr
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    assert summaries[0].read_bytes() == summaries[1].read_bytes()
    report = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert "ClinLoop,worker_runtime,0.0,0.0" in summaries[0].read_text(encoding="utf-8")
    assert report["case_count"] == 100
    assert report["synthetic_only"] is True
    assert report["seed"] == 20260928
    assert report["methods"]["direct_llm"]["provider_kind"] == "mock"
