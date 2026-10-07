from datetime import timedelta

import pytest


def test_replay_exposes_only_chronological_prefix_and_detached_objects(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import replay

    case = generate_cases(1, 10)[0]
    before = case.model_dump_json()
    seen = []

    class Observer:
        def handle_event(self, event, context):
            assert not hasattr(context, "annotation")
            assert not hasattr(context, "expected")
            assert all(e.event_time <= context.as_of for e in context.events)
            assert all(e.source_time <= context.available_at for e in context.events)
            assert all(n.observed_at <= context.as_of for n in context.evidence)
            assert context.events[-1].event_id == event.event_id
            seen.append(event.event_id)
            event.payload["tampered"] = True
            context.events.clear()
            return api.HandlerResult()

        def final_states(self):
            return {"observed": len(seen)}

    shuffled = case.model_copy(update={"events": list(reversed(case.events))}, deep=True)
    result = replay(shuffled, Observer())
    assert seen == [
        e.event_id
        for e in sorted(case.events, key=lambda e: (e.event_time, e.source_time, e.event_id))
    ]
    assert result.final_states == {"observed": len(case.events)}
    assert len(result.event_ids) == len(case.events)
    assert case.model_dump_json() == before


def test_delayed_source_record_is_not_visible_to_earlier_events(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import replay

    case = generate_cases(1, 10)[0].model_copy(deep=True)
    early = case.events[0]
    early.source_time = case.events[2].event_time + timedelta(minutes=1)
    observations = []

    class Observer:
        def handle_event(self, event, context):
            observations.append((event.event_id, {e.event_id for e in context.events}))
            return api.HandlerResult()

        def final_states(self):
            return {}

    replay(case, Observer())
    second_id = case.events[1].event_id
    assert early.event_id not in next(ids for eid, ids in observations if eid == second_id)


def test_late_record_is_dispatched_only_when_available_not_into_worker_memory_early(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import replay

    case = generate_cases(1, 10)[0].model_copy(deep=True)
    case.events[0].source_time = case.events[2].event_time + timedelta(minutes=1)
    dispatched = []

    class Observer:
        def handle_event(self, event, context):
            assert max(event.source_time, event.event_time) == context.as_of
            dispatched.append(event.event_id)
            return api.HandlerResult()

        def final_states(self):
            return {}

    replay(case, Observer())
    assert dispatched[:3] == [
        case.events[1].event_id,
        case.events[2].event_id,
        case.events[0].event_id,
    ]


def test_real_clinloop_replay_records_worker_runs_no_fabricated_tools(api):
    assert api, "task11 evaluation API not implemented"
    from apps.worker.worker.agent import WorkflowAgent
    from eval.baselines.clinloop import ClinLoopAdapter
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import canonicalize, replay

    case = generate_cases(1, 42)[0]
    adapter = ClinLoopAdapter()
    assert isinstance(adapter.agent, WorkflowAgent)
    first = replay(case, adapter)
    second = replay(case, ClinLoopAdapter())
    assert len(first.runs) == len(case.events)
    assert first.runs[0].steps
    assert first.tool_calls == []
    assert first.final_states["loops"] == {}
    assert first.prediction.findings == []
    assert first.prediction.handoff.item_ids == []
    assert canonicalize(first) == canonicalize(second)
    assert first.runs[0].run_id != second.runs[0].run_id


def test_canonical_comparison_preserves_clinical_time_and_semantic_ids(api):
    assert api, "task11 evaluation API not implemented"
    from eval.replay.replayer import canonicalize

    a = {
        "run_id": "RUN-a123456789ab",
        "source_run_id": "RUN-a123456789ab",
        "started_at": "today",
        "duration_ms": 2,
        "event_id": "EV-1",
        "event_time": "2026-09-28T09:00:00+00:00",
        "observed_at": "2026-09-28T09:00:00+00:00",
    }
    b = {
        **a,
        "run_id": "RUN-b123456789ab",
        "source_run_id": "RUN-b123456789ab",
        "started_at": "tomorrow",
        "duration_ms": 900,
    }
    assert canonicalize(a) == canonicalize(b)
    assert canonicalize(a)["run_id"] == canonicalize(a)["source_run_id"]
    assert canonicalize(a) != canonicalize({**b, "event_id": "EV-2"})
    assert canonicalize(a) != canonicalize({**b, "event_time": "2026-09-29T09:00:00+00:00"})


def test_canonical_runtime_ids_as_dictionary_keys_preserve_references(api):
    from eval.replay.replayer import canonicalize

    a = {
        "loops": {"LOOP-a123456789ab": {"state": "PENDING_REVIEW"}},
        "loop_id": "LOOP-a123456789ab",
    }
    b = {
        "loops": {"LOOP-b123456789ab": {"state": "PENDING_REVIEW"}},
        "loop_id": "LOOP-b123456789ab",
    }
    assert canonicalize(a) == canonicalize(b)
    canonical = canonicalize(a)
    assert canonical["loop_id"] in canonical["loops"]


@pytest.mark.parametrize(
    "field", ["event_id", "event_ids", "trigger_event_id", "source_id", "evidence_ids", "claim"]
)
def test_canonical_clinical_uuid_changes_remain_significant(api, field):
    from eval.replay.replayer import canonicalize

    first = "11111111-1111-4111-8111-111111111111"
    second = "22222222-2222-4222-8222-222222222222"
    a = {field: [first] if field.endswith("ids") else first}
    b = {field: [second] if field.endswith("ids") else second}
    assert canonicalize(a) != canonicalize(b)


def test_canonical_bare_runtime_uuids_keep_relationships_and_clinical_references(api):
    from eval.replay.replayer import canonicalize

    clinical = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

    def trace(run, step, finding):
        return {
            "runs": [
                {
                    "run_id": run,
                    "trigger_event_id": clinical,
                    "steps": [{"step_id": step}],
                    "finding_ids": [finding],
                }
            ],
            "findings": {
                finding: {
                    "finding_id": finding,
                    "source_run_id": run,
                    "supporting_evidence": [clinical],
                }
            },
            "source_id": clinical,
            "evidence_ids": [clinical],
        }

    a = trace(
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    )
    b = trace(
        "44444444-4444-4444-8444-444444444444",
        "55555555-5555-4555-8555-555555555555",
        "66666666-6666-4666-8666-666666666666",
    )
    normalized = canonicalize(a)
    assert normalized == canonicalize(b)
    finding = normalized["runs"][0]["finding_ids"][0]
    assert finding in normalized["findings"]
    assert normalized["findings"][finding]["source_run_id"] == normalized["runs"][0]["run_id"]
    assert normalized["runs"][0]["trigger_event_id"] == clinical
    assert normalized["findings"][finding]["supporting_evidence"] == [clinical]
    assert normalized["evidence_ids"] == [clinical]
