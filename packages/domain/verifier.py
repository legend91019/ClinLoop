from __future__ import annotations

from dataclasses import dataclass, field

from packages.contracts import FindingType


@dataclass(frozen=True)
class VerificationResult:
    status: str
    finding_type: FindingType | None = None
    supporting_evidence: list[str] = field(default_factory=list)
    searched_sources: list[str] = field(default_factory=list)
    requires_review: bool = True


def verify_workflow_continuity(
    *, plan=None, order=None, execution=None, result=None, response=None, handoff=None
) -> VerificationResult:
    stages = (
        ("PLAN", plan),
        ("ORDER", order),
        ("EXECUTION", execution),
        ("RESULT", result),
        ("RESPONSE", response),
        ("HANDOFF", handoff),
    )
    searched = [name for name, value in stages if value is not None]

    def gap(finding_type: FindingType, value: object) -> VerificationResult:
        return VerificationResult("GAP", finding_type, [str(value)], searched)

    if order is not None and plan is None:
        return gap(FindingType.INTENT_WITHOUT_PLAN, order)
    if execution is not None and order is None and plan is not None:
        return gap(FindingType.PLAN_WITHOUT_ORDER, execution)
    if result is not None and execution is None and order is not None:
        return gap(FindingType.ORDER_WITHOUT_EXECUTION, result)
    if result is not None and response is None:
        return gap(FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT, result)
    if response is not None and handoff is None:
        return gap(FindingType.LOOP_MISSING_FROM_HANDOFF, response)

    return VerificationResult(
        "CONTINUOUS",
        None,
        [str(value) for _, value in stages if value is not None],
        searched,
        False,
    )
