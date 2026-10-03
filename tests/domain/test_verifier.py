from __future__ import annotations

import pytest

from packages.contracts import FindingType
from packages.domain.verifier import verify_workflow_continuity


@pytest.mark.parametrize(
    ("kwargs", "finding_type"),
    [
        ({"order": "ORDER-1"}, FindingType.INTENT_WITHOUT_PLAN),
        ({"plan": "plan", "execution": "EXEC-1"}, FindingType.PLAN_WITHOUT_ORDER),
        (
            {"plan": "plan", "order": "ORDER-1", "result": "RESULT-1"},
            FindingType.ORDER_WITHOUT_EXECUTION,
        ),
        ({"result": "RESULT-1"}, FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT),
        (
            {
                "plan": "plan",
                "order": "ORDER-1",
                "execution": "EXEC-1",
                "result": "RESULT-1",
                "response": "ACK-1",
            },
            FindingType.LOOP_MISSING_FROM_HANDOFF,
        ),
    ],
)
def test_verifier_reports_the_first_missing_workflow_stage(
    kwargs: dict, finding_type: FindingType
) -> None:
    result = verify_workflow_continuity(**kwargs)

    assert result.status == "GAP"
    assert result.finding_type is finding_type
    assert result.requires_review is True
