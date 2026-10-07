from __future__ import annotations

from datetime import timedelta

from apps.api.app.db import session_scope
from apps.api.app.repositories import ClinicalEventRepository
from apps.mcp_server.mcp_server.server import build_registry
from packages.contracts import utcnow
from packages.fixtures import main_case_events


def test_worker_tools_hide_records_arriving_after_trigger(api_engine) -> None:
    source = main_case_events()[1]
    as_of = utcnow() - timedelta(minutes=2)
    visible = source.model_copy(
        update={
            "event_id": "EVT-TOOL-VISIBLE",
            "payload_ref": "LAB-TOOL-VISIBLE",
            "event_time": as_of,
            "source_time": as_of,
        }
    )
    future = source.model_copy(
        update={
            "event_id": "EVT-TOOL-FUTURE",
            "payload_ref": "LAB-TOOL-FUTURE",
            "event_time": as_of + timedelta(minutes=1),
            "source_time": as_of + timedelta(minutes=1),
        }
    )
    with session_scope(api_engine) as session:
        ClinicalEventRepository(session).add(visible)
        ClinicalEventRepository(session).add(future)
    with session_scope(api_engine) as session:
        rows = build_registry(session, as_of=as_of).call("get_labs", patient_id="P-1001")

    ids = {row["event_id"] for row in rows}
    assert visible.event_id in ids
    assert future.event_id not in ids
