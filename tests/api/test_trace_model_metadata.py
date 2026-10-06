from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from apps.api.app.db_models import AgentRunRow


def test_trace_returns_safe_model_metadata(client: TestClient, api_engine) -> None:
    with Session(api_engine) as session:
        session.add(
            AgentRunRow(
                run_id="RUN-MODEL-1",
                loop_id="LOOP-1001",
                intent_id="INT-1001",
                trigger_event_id="EVT-1001",
                plan=["model proposal"],
                steps=[],
                tool_calls=[],
                finding_ids=[],
                candidate_state_changes={},
                stop_reason="WAITING_EXTERNAL_EVENT",
                payload={
                    "trace_metadata": {
                        "provider": "deepseek",
                        "model": "deepseek-chat",
                        "proposal_ref": "PROP-1",
                        "latency_ms": 120,
                    }
                },
            )
        )
        session.commit()

    response = client.get("/api/v1/loops/LOOP-1001/trace")

    assert response.status_code == 200
    assert response.json()[0]["trace_metadata"] == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "proposal_ref": "PROP-1",
        "latency_ms": 120,
    }
