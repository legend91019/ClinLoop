from eval.online.scoring import ObservedCase, score_case, summarize


def test_scoring_rejects_unsourced_positive_alert() -> None:
    observed = ObservedCase(
        case_id="CASE-001",
        provider_kind="mock",
        alert_count=1,
        valid_evidence_count=0,
        model_errors=0,
        tool_calls=2,
    )

    result = score_case(expected_alert=True, observed=observed)

    assert result.tp == 0
    assert result.fp == 1
    assert result.fn == 1
    assert result.evidence_valid is False


def test_scoring_counts_both_positive_and_negative_opportunities() -> None:
    positive = score_case(
        expected_alert=True,
        observed=ObservedCase("CASE-001", "rules", 1, 1, 0, 2),
    )
    negative = score_case(
        expected_alert=False,
        observed=ObservedCase("CASE-002", "rules", 0, 0, 0, 0),
    )

    report = summarize([positive, negative])

    assert report["tp"] == 1
    assert report["tn"] == 1
    assert report["fp"] == 0
    assert report["fn"] == 0
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["tool_calls"] == 2


def test_scoring_keeps_model_failure_in_denominator() -> None:
    failed = score_case(
        expected_alert=True,
        observed=ObservedCase("CASE-001", "real", 0, 0, 1, 0),
    )

    report = summarize([failed])

    assert report["fn"] == 1
    assert report["model_errors"] == 1
    assert report["recall"] == 0.0


def test_scoring_reports_runtime_latency_and_false_alert_rate() -> None:
    positive = score_case(
        expected_alert=True,
        observed=ObservedCase("CASE-001", "real", 1, 1, 0, 2, 1200),
    )
    negative = score_case(
        expected_alert=False,
        observed=ObservedCase("CASE-002", "real", 1, 1, 0, 2, 800),
    )

    report = summarize([positive, negative])

    assert report["false_alert_rate"] == 1.0
    assert report["latency_ms_total"] == 2000
    assert report["latency_ms_mean"] == 1000.0


def test_invalid_positive_evidence_does_not_inflate_negative_false_alert_rate() -> None:
    invalid_positive = score_case(
        expected_alert=True,
        observed=ObservedCase("CASE-001", "real", 1, 0, 0, 0),
    )
    normal = score_case(
        expected_alert=False,
        observed=ObservedCase("CASE-002", "real", 0, 0, 0, 0),
    )
    assert summarize([invalid_positive, normal])["false_alert_rate"] == 0.0
    assert summarize([invalid_positive, normal])["evidence_validity_rate"] == 0.0
