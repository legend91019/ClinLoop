from __future__ import annotations

from collections.abc import Sequence

from eval.baselines import make_handler
from eval.metrics.definitions import MetricsReport, compute_metrics
from eval.models import SyntheticCase
from eval.replay.replayer import canonicalize, replay
from packages.contracts.models import StrictModel


class MethodReport(StrictModel):
    provider_kind: str
    limitations: list[str]
    metrics: MetricsReport
    model_calls: int
    replays: list[dict]


class ComparisonReport(StrictModel):
    schema_version: str = "1.0"
    seed: int | None = None
    case_count: int
    synthetic_only: bool = True
    distribution: dict[str, int]
    methods: dict[str, MethodReport]
    notes: list[str]


def run_all_methods(
    cases: Sequence[SyntheticCase], provider=None, *, seed: int | None = None
) -> ComparisonReport:
    if any(not case.synthetic for case in cases):
        raise ValueError("evaluation accepts synthetic cases only")
    methods = {}
    for method in ("direct_llm", "rag_template", "rule_engine", "ClinLoop"):
        results = []
        description = make_handler(method, provider)
        for case in cases:
            results.append(replay(case, make_handler(method, provider)))
        methods[method] = MethodReport(
            provider_kind=description.provider_kind,
            limitations=description.limitations,
            metrics=compute_metrics(cases, results),
            model_calls=sum(len(r.model_calls) for r in results),
            replays=[canonicalize(r) for r in results],
        )
    distribution = {
        "normal": 0,
        "PLAN_WITHOUT_ORDER": 0,
        "ORDER_WITHOUT_EXECUTION": 0,
        "RESULT_WITHOUT_ACKNOWLEDGEMENT": 0,
        "LOOP_MISSING_FROM_HANDOFF": 0,
    }
    for case in cases:
        distribution[
            case.annotation.defect_type.value if case.annotation.defect_type else "normal"
        ] += 1
    return ComparisonReport(
        seed=seed,
        case_count=len(cases),
        distribution=distribution,
        methods=methods,
        notes=[
            "Synthetic engineering verification; not evidence of clinical effectiveness.",
            "Dispatch clock = max(event_time, source_time); model/worker see only now-available records, never annotations or gold evidence.",
            "Canonical reports alpha-rename runtime UUIDs and omit wall-clock timestamps/durations; clinical times and reference relationships remain.",
            "Runtime IDs are identified by runtime field roles; clinical event/source UUIDs and evidence citations remain significant.",
            "Metrics assess retained findings at the final case checkpoint, not alert latency or clinical timeliness.",
            "A credited gap requires its specific prerequisite stages available at detected_at using max(event_time, source_time), never an unrelated earlier item record.",
            "False alarm denominator = normal patient/item/type opportunities, including unaffected edges of defect cases.",
            "Evidence coverage = (backed findings + backed handoff items)/(predicted findings + predicted handoff items); separate rates and counts also reported.",
            "Each handoff item needs attributable trusted source records available at generated_at; a global nonempty evidence list does not back unrelated items. Unknown references invalidate handoff coverage conservatively.",
            "Finding citations must all be valid, trusted, attributable and visible at detection; deduplicate patient/item/type findings and handoff item IDs.",
            "Handoff omission denominator = eligible items, missing predictions count as omissions; unknown predictions reported separately.",
            "Built-in MOCK abstains; model_calls counts provider invocations and does not imply actual model inference.",
        ],
    )
