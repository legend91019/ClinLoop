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


def verify_workflow_continuity(*, plan=None, order=None, execution=None, result=None, response=None, handoff=None) -> VerificationResult:
    searched = [name for name, value in (("PLAN", plan), ("ORDER", order), ("EXECUTION", execution), ("RESULT", result), ("RESPONSE", response), ("HANDOFF", handoff)) if value is not None]
    if result and not response:
        return VerificationResult("GAP", FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT, [str(result)], searched)
    return VerificationResult("CONTINUOUS", None, [str(x) for x in (plan, order, execution, result, response, handoff) if x], searched, False)
