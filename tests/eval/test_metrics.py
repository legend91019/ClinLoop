from datetime import timedelta

import pytest

from packages.contracts import FindingType, TrustLevel


def test_zero_denominators_have_counts_and_zero_rates(api):
    assert api, "task11 evaluation API not implemented"
    from eval.metrics.definitions import compute_metrics

    metrics = compute_metrics([], [])
    for name in ("gap_recall", "false_alarm_rate", "evidence_coverage", "handoff_omission_rate"):
        assert getattr(metrics, name) == 0.0
    assert (
        metrics.gaps
        == metrics.normal_opportunities
        == metrics.predicted_findings
        == metrics.eligible_handoff_items
        == 0
    )


def test_metrics_use_opportunities_and_eligible_items_not_case_denominators(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    cases = generate_cases(100, 20260928)
    predictions = []
    for case in cases:
        findings = [
            api.FindingPrediction(
                patient_id=case.patient_id,
                item_id=g.item_id,
                finding_type=g.finding_type,
                evidence_ids=g.evidence_ids,
                detected_at=case.events[-1].event_time,
            )
            for g in case.annotation.gaps
        ]
        predictions.append(
            api.CasePrediction(
                patient_id=case.patient_id,
                findings=findings,
                handoff=api.HandoffPrediction(
                    patient_id=case.patient_id,
                    item_ids=case.annotation.eligible_handoff_items,
                    generated_at=case.events[-1].event_time,
                ),
            )
        )
    normal = next(c for c in cases if c.annotation.defect_type is None)
    pred = next(p for p in predictions if p.patient_id == normal.patient_id)
    alarm = api.FindingPrediction(
        patient_id=normal.patient_id,
        item_id=normal.annotation.eligible_handoff_items[0],
        finding_type=FindingType.PLAN_WITHOUT_ORDER,
        evidence_ids=[normal.evidence[0].evidence_id],
        detected_at=normal.events[-1].event_time,
    )
    pred.findings.extend([alarm, alarm.model_copy(deep=True)])
    pred.handoff.item_ids = []
    metrics = compute_metrics(cases, predictions)
    assert metrics.gaps == metrics.true_positives == 75
    assert metrics.gap_recall == 1.0
    assert metrics.normal_opportunities == 325
    assert metrics.false_alarms == 1
    assert metrics.false_alarm_rate == pytest.approx(1 / 325)
    assert metrics.eligible_handoff_items == 100
    assert metrics.omitted_handoff_items == 1
    assert metrics.handoff_omission_rate == 0.01


@pytest.mark.parametrize(
    "bad",
    ["unknown", "wrong_item", "other_patient", "future", "patient_reported", "unattributable"],
)
def test_evidence_coverage_requires_valid_attributable_visible_evidence(api, bad):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    case = generate_cases(1, 42)[0].model_copy(deep=True)
    node = case.evidence[0]
    when = case.events[-1].event_time
    refs = [node.evidence_id]
    if bad == "unknown":
        refs = ["NONEXISTENT"]
    elif bad == "wrong_item":
        node.provenance["item_id"] = "UNRELATED"
    elif bad == "other_patient":
        node.patient_id = "OTHER"
    elif bad == "future":
        node.observed_at = when + timedelta(days=1)
    elif bad == "patient_reported":
        node.trust_level = TrustLevel.PATIENT_REPORTED
    else:
        node.source_id = "NO-RECORD"
    finding = api.FindingPrediction(
        patient_id=case.patient_id,
        item_id=case.annotation.eligible_handoff_items[0],
        finding_type=FindingType.PLAN_WITHOUT_ORDER,
        evidence_ids=refs,
        detected_at=when,
    )
    metric = compute_metrics(
        [case], [api.CasePrediction(patient_id=case.patient_id, findings=[finding])]
    )
    assert metric.evidence_coverage == 0.0
    assert metric.evidence_backed_findings == 0


def test_missing_predictions_count_omissions_and_wrong_items_do_not_match(api):
    assert api, "task11 evaluation API not implemented"
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    case = next(c for c in generate_cases(100, 4) if c.annotation.gaps)
    gap = case.annotation.gaps[0]
    wrong = api.FindingPrediction(
        patient_id=case.patient_id,
        item_id="OTHER",
        finding_type=gap.finding_type,
        detected_at=case.events[-1].event_time,
    )
    metric = compute_metrics(
        [case], [api.CasePrediction(patient_id=case.patient_id, findings=[wrong])]
    )
    assert metric.true_positives == 0
    assert metric.unmatched_predictions == 1
    assert metric.handoff_omission_rate == 1.0


def test_source_less_handoff_lowers_total_coverage_despite_valid_finding(api):
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    case = generate_cases(1, 42)[0]
    item = case.annotation.eligible_handoff_items[0]
    when = case.events[-1].event_time
    finding = api.FindingPrediction(
        patient_id=case.patient_id,
        item_id=item,
        finding_type=FindingType.PLAN_WITHOUT_ORDER,
        evidence_ids=[case.evidence[0].evidence_id],
        detected_at=when,
    )
    handoff = api.HandoffPrediction(
        patient_id=case.patient_id, item_ids=[item, item], generated_at=when
    )
    metric = compute_metrics(
        [case],
        [api.CasePrediction(patient_id=case.patient_id, findings=[finding], handoff=handoff)],
    )
    assert metric.evidence_coverage == 0.5
    assert metric.predicted_findings == metric.evidence_backed_findings == 1
    assert metric.predicted_handoff_items == 1
    assert metric.evidence_backed_handoff_items == 0
    assert metric.finding_evidence_coverage == 1.0
    assert metric.handoff_evidence_coverage == 0.0


def test_handoff_coverage_attributes_sources_to_each_item_not_global_nonempty_list(api):
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    case = generate_cases(1, 42)[0]
    item = case.annotation.eligible_handoff_items[0]
    other = next(n for n in case.evidence if n.provenance["stage"] == "CONSULT")
    handoff = api.HandoffPrediction(
        patient_id=case.patient_id,
        item_ids=[item, other.provenance["item_id"]],
        evidence_ids=[case.evidence[0].evidence_id],
        generated_at=case.events[-1].event_time,
    )
    prediction = api.CasePrediction(patient_id=case.patient_id, handoff=handoff)
    metric = compute_metrics([case], [prediction])
    assert metric.predicted_handoff_items == 2
    assert metric.evidence_backed_handoff_items == 1
    assert metric.evidence_coverage == 0.5
    handoff.evidence_ids.append(other.evidence_id)
    metric = compute_metrics([case], [prediction])
    assert metric.evidence_backed_handoff_items == 2
    assert metric.evidence_coverage == 1.0


@pytest.mark.parametrize(
    "bad",
    [
        "unknown",
        "other_patient",
        "wrong_item",
        "future",
        "late_source",
        "patient_reported",
        "unattributable",
    ],
)
def test_handoff_sources_must_be_valid_trusted_attributable_and_available(api, bad):
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    case = generate_cases(1, 42)[0].model_copy(deep=True)
    item = case.annotation.eligible_handoff_items[0]
    node = case.evidence[0]
    when = case.events[-1].event_time
    refs = [node.evidence_id]
    if bad == "unknown":
        refs = ["UNKNOWN"]
    elif bad == "other_patient":
        node.patient_id = "OTHER"
    elif bad == "wrong_item":
        node.provenance["item_id"] = "OTHER-ITEM"
    elif bad == "future":
        node.observed_at = when + timedelta(days=1)
    elif bad == "late_source":
        case.events[0].source_time = when + timedelta(days=1)
    elif bad == "patient_reported":
        node.trust_level = TrustLevel.PATIENT_REPORTED
    else:
        node.source_id = "UNATTRIBUTABLE"
    handoff = api.HandoffPrediction(
        patient_id=case.patient_id, item_ids=[item], evidence_ids=refs, generated_at=when
    )
    metric = compute_metrics(
        [case], [api.CasePrediction(patient_id=case.patient_id, handoff=handoff)]
    )
    assert metric.predicted_handoff_items == 1
    assert metric.evidence_backed_handoff_items == 0
    assert metric.evidence_coverage == 0.0


def test_combined_evidence_counts_have_zero_denominators(api):
    from eval.metrics.definitions import compute_metrics

    metric = compute_metrics([], [])
    assert metric.predicted_handoff_items == metric.evidence_backed_handoff_items == 0
    assert metric.finding_evidence_coverage == metric.handoff_evidence_coverage == 0.0


@pytest.mark.parametrize(
    "kind,stage",
    [
        (FindingType.ORDER_WITHOUT_EXECUTION, "ORDER"),
        (FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT, "RESULT"),
        (FindingType.LOOP_MISSING_FROM_HANDOFF, "HANDOFF"),
    ],
)
def test_gap_recall_requires_the_correct_prerequisite_stage(api, kind, stage):
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    case = next(c for c in generate_cases(100, 42) if c.annotation.defect_type == kind)
    item = case.annotation.eligible_handoff_items[0]
    prerequisite = next(e for e in case.events if e.payload["stage"] == stage)
    finding = api.FindingPrediction(
        patient_id=case.patient_id,
        item_id=item,
        finding_type=kind,
        detected_at=case.events[0].event_time,
    )
    prediction = api.CasePrediction(patient_id=case.patient_id, findings=[finding])
    metric = compute_metrics([case], [prediction])
    assert metric.true_positives == 0
    assert metric.gap_recall == 0.0
    assert metric.temporally_invalid_predictions == 1
    finding.detected_at = max(prerequisite.event_time, prerequisite.source_time)
    metric = compute_metrics([case], [prediction])
    assert metric.true_positives == 1
    assert metric.temporally_invalid_predictions == 0


def test_result_response_gap_cannot_be_credited_before_late_source_is_available(api):
    from eval.generators.cases import generate_cases
    from eval.metrics.definitions import compute_metrics

    kind = FindingType.RESULT_WITHOUT_ACKNOWLEDGEMENT
    case = next(c for c in generate_cases(100, 42) if c.annotation.defect_type == kind).model_copy(
        deep=True
    )
    result = next(e for e in case.events if e.payload["stage"] == "RESULT")
    result.source_time = result.event_time + timedelta(hours=2)
    finding = api.FindingPrediction(
        patient_id=case.patient_id,
        item_id=case.annotation.eligible_handoff_items[0],
        finding_type=kind,
        evidence_ids=[result.payload_ref],
        detected_at=result.event_time,
    )
    prediction = api.CasePrediction(patient_id=case.patient_id, findings=[finding])
    before = compute_metrics([case], [prediction])
    assert before.true_positives == before.evidence_backed_findings == 0
    assert before.temporally_invalid_predictions == 1
    finding.detected_at = result.source_time
    after = compute_metrics([case], [prediction])
    assert after.true_positives == after.evidence_backed_findings == 1
    assert after.temporally_invalid_predictions == 0
