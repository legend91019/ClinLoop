from __future__ import annotations

from sqlalchemy.orm import Session

from apps.api.app.db_models import AgentRunRow


def test_patient_trace_includes_model_error_without_a_loop(client, api_engine) -> None:
    with Session(api_engine) as session:
        session.add(
            AgentRunRow(
                run_id="RUN-UNBOUND-MODEL-ERROR",
                loop_id=None,
                intent_id=None,
                trigger_event_id="EVT-1001",
                plan=[],
                steps=[],
                tool_calls=[],
                finding_ids=[],
                candidate_state_changes={},
                stop_reason="MODEL_ERROR",
                payload={"trace_metadata": {"provider": "deepseek", "error_code": "MODEL_TIMEOUT"}},
            )
        )
        session.commit()

    response = client.get("/api/v1/patients/P-1001/runs")

    assert response.status_code == 200
    assert any(
        run["run_id"] == "RUN-UNBOUND-MODEL-ERROR"
        and run["loop_id"] is None
        and run["trace_metadata"]["error_code"] == "MODEL_TIMEOUT"
        for run in response.json()
    )
    assert client.get("/api/v1/patients/P-NOBODY/runs").json() == []
