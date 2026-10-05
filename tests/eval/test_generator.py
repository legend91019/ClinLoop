from collections import Counter

import pytest

from packages.contracts import FindingType


def test_exact_distribution_and_reproducible_synthetic_contracts(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases

    cases = generate_cases(100, 20260928)
    assert Counter(c.annotation.defect_type for c in cases) == {
        None: 25,
        FindingType.PLAN_WITHOUT_ORDER: 20,
        FindingType.ORDER_WITHOUT_EXECUTION: 20,
        FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT: 20,
        FindingType.LOOP_MISSING_FROM_HANDOFF: 15,
    }
    assert cases == generate_cases(100, 20260928)
    assert cases != generate_cases(100, 20260929)
    assert len({c.patient_id for c in cases}) == 100
    assert all(c.synthetic and c.events and c.evidence for c in cases)
    assert len({e.event_type for c in cases for e in c.events}) >= 6
    assert all(e.patient_id == c.patient_id for c in cases for e in c.events)


@pytest.mark.parametrize("count", [0, 1, 3, 7, 99, 101, 203])
def test_general_counts_are_exact(api, count):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases

    assert len(generate_cases(count, 4)) == count


@pytest.mark.parametrize(
    "count,seed", [(-1, 1), (True, 1), (1.5, 1), ("100", 1), (1, True), (1, 1.2)]
)
def test_generator_rejects_invalid_parameters(api, count, seed):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases

    with pytest.raises(ValueError):
        generate_cases(count, seed)


@pytest.mark.parametrize(
    "kind",
    [
        FindingType.PLAN_WITHOUT_ORDER,
        FindingType.ORDER_WITHOUT_EXECUTION,
        FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT,
        FindingType.LOOP_MISSING_FROM_HANDOFF,
    ],
)
def test_injection_changes_observations_without_mutating_input(api, kind):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.generators.defects import inject_defect

    case = next(c for c in generate_cases(100, 8) if c.annotation.defect_type is None)
    before = case.model_dump_json()
    broken = inject_defect(case, kind, 5)
    assert case.model_dump_json() == before
    assert broken == inject_defect(case, kind, 5)
    assert broken.events != case.events
    assert broken.annotation.defect_type == kind
    assert {e.source_id for e in broken.evidence} <= {e.payload_ref for e in broken.events}
    assert len(broken.annotation.gaps) == 1
    with pytest.raises(ValueError):
        inject_defect(broken, kind, 5)


def test_injection_rejects_unsupported_taxonomy(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.generators.defects import inject_defect

    with pytest.raises(ValueError):
        inject_defect(generate_cases(1, 4)[0], FindingType.STALE_LOOP, 4)
