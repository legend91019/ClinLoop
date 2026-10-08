from eval.online.cases import contest_cases, online_cases


def test_online_cases_keep_labels_outside_visible_events() -> None:
    cases = online_cases()

    assert len(cases) >= 6
    assert len({case.case_id for case in cases}) == len(cases)
    assert any(case.expected_alert for case in cases)
    assert any(not case.expected_alert for case in cases)
    assert len({case.cohort for case in cases}) >= 4
    for case in cases:
        assert case.events
        assert len({event.event_id for event in case.events}) == len(case.events)
        assert all(event.patient_id == case.patient_id for event in case.events)
        assert all("expected_alert" not in event.payload for event in case.events)
        assert all("cohort" not in event.payload for event in case.events)
        assert all("intent_hint" not in event.payload for event in case.events)
        assert all("expected_evidence" not in event.payload for event in case.events)


def test_online_cases_are_deterministic() -> None:
    first = online_cases()
    second = online_cases()

    assert first == second


def test_contest_corpus_is_frozen_balanced_and_label_blind() -> None:
    cases = contest_cases()

    assert len(cases) == 50
    assert sum(case.expected_alert for case in cases) == 25
    assert len({case.case_id for case in cases}) == 50
    assert cases == contest_cases()
    for case in cases:
        assert all("expected_alert" not in event.payload for event in case.events)
        assert all("cohort" not in event.payload for event in case.events)
