"""Exercise grounded analysis, scope, stale reports and durable conditional execution."""

import json
from copy import deepcopy

import pytest
from sqlalchemy.orm import Session

from apps.api.app.db_models import CareAssistanceRow, ClinicalDocumentRow
from apps.api.app.services.care_assistance_service import sync_plans
from apps.worker.worker.care_assistant import process_care_queue
from tests.api.test_patient_workspace import HEADERS, patient
from tests.api.test_workspace_agent import lab, submit


def base(p):
    return f"/api/v1/patients/{p['patient_id']}/care-assistance"


def listing(client, p):
    return client.get(base(p), params={"encounter_id": p["encounter_id"]}).json()


def enqueue(client, p, mode="PREPARE", doc=None):
    reply = client.post(
        base(p),
        headers=HEADERS,
        json={"encounter_id": p["encounter_id"], "mode": mode, "document_id": doc},
    )
    assert reply.status_code == 202, reply.text
    return reply.json()


def model(result):
    remaining = iter(
        [
            {"tool": tool, "reason": "核对来源"}
            for tool in ("read_documents", "read_labs", "read_tasks")
        ]
        + [{"result": result}]
    )
    return lambda messages: next(remaining)


def decide(client, p, run, action, **extra):
    return client.post(
        base(p) + f"/{run['run_id']}/decision",
        headers=HEADERS,
        json={
            "revision": run["revision"],
            "action": action,
            "reason": "医生核对原始资料后确认",
            **extra,
        },
    )


def output(doc=None):
    return {
        "summary": "资料核对完成",
        "findings": [{"category": "QUESTION", "text": "核实过敏史", "source_ids": ["profile"]}],
        "tasks": []
        if not doc
        else [
            {
                "key": "a",
                "goal": "核对培养结果",
                "source_quote": "培养结果出来后查看",
                "source_ids": [doc],
                "condition": "RESULT",
                "panel": "blood_culture_result",
            },
            {
                "key": "b",
                "goal": "整理交接事项",
                "source_quote": "处理后整理交接",
                "source_ids": [doc],
                "depends_on": ["a"],
            },
        ],
    }


def plan(client, engine, p):
    doc = submit(client, p, "【诊疗计划】\n培养结果出来后查看；处理后整理交接。")
    enqueue(client, p, "PLAN", doc["document_id"])
    process_care_queue(engine, turn=model(output(doc["document_id"])))
    run = listing(client, p)[0]
    assert run["status"] == "READY", run
    reply = decide(client, p, run, "ACCEPT")
    assert reply.status_code == 200, reply.text
    return reply.json()


def sync(engine):
    with Session(engine) as session:
        sync_plans(session)
        session.commit()


def test_prepare_reads_tools_and_is_scoped_and_persisted(workspace):
    client, engine = workspace
    p, other = patient(client), patient(client, "另一患者")
    foreign = submit(client, other, "不能出现在当前患者资料")
    first = enqueue(client, p)
    assert enqueue(client, p)["run_id"] == first["run_id"]
    seen = []
    scripted = model(output())

    def turn(messages):
        seen.extend(messages)
        return scripted(messages)

    assert process_care_queue(engine, turn=turn)
    run = listing(client, p)[0]
    assert run["status"] == "READY"
    assert len(run["trace"]) == 3
    assert foreign["document_id"] not in json.dumps(seen)
    assert not run["stale"]
    assert not process_care_queue(engine, turn=turn)
    assert decide(client, other, run, "DISMISS", item_key="0").status_code == 404


def test_quality_requires_saved_document_and_detects_stale_revision(workspace):
    client, engine = workspace
    p = patient(client)
    doc = submit(client, p)
    enqueue(client, p, "QUALITY", doc["document_id"])
    process_care_queue(engine, turn=model(output()))
    run = listing(client, p)[0]
    assert decide(client, p, run, "RESOLVE", item_key="0").status_code == 200
    with Session(engine) as session:
        row = session.get(ClinicalDocumentRow, doc["document_id"])
        row.revision += 1
        session.commit()
    updated = listing(client, p)[0]
    assert updated["stale"]
    assert decide(client, p, updated, "RESOLVE", item_key="0").status_code == 409


@pytest.mark.parametrize("bad", ["foreign_source", "cycle", "invented_quote", "unknown_tool"])
def test_invalid_model_output_never_creates_plan(workspace, bad):
    client, engine = workspace
    p = patient(client)
    doc = submit(client, p, "培养结果出来后查看；处理后整理交接。")
    enqueue(client, p, "PLAN", doc["document_id"])
    result = output(doc["document_id"])
    if bad == "foreign_source":
        result["findings"][0]["source_ids"] = ["ANOTHER_PATIENT"]
    if bad == "cycle":
        result["tasks"][0]["depends_on"] = ["b"]
    if bad == "invented_quote":
        result["tasks"][0]["source_quote"] = "这是医生没有说过的话"
    turn = (lambda messages: {"tool": "write_order"}) if bad == "unknown_tool" else model(result)
    process_care_queue(engine, turn=turn)
    assert listing(client, p)[0]["status"] == "FAILED"
    assert (
        client.get(
            f"/api/v1/patients/{p['patient_id']}/tasks", params={"encounter_id": p["encounter_id"]}
        ).json()
        == []
    )


def test_conditions_wait_resume_require_review_and_release_dependencies(workspace):
    client, engine = workspace
    p = patient(client)
    run = plan(client, engine, p)
    assert run["task_states"]["a"]["state"] == "WAITING"
    assert decide(client, p, run, "RESOLVE", item_key="a").status_code == 409
    # Existing manual endpoint must also enforce the plan, not offer a bypass.
    direct = client.patch(
        f"/api/v1/patients/{p['patient_id']}/tasks/{run['bindings']['a']}",
        headers=HEADERS,
        json={"expected_state": "PLANNED", "state": "RESOLVED", "reason": "核对"},
    )
    assert direct.status_code == 409
    other = patient(client, "另一患者")
    lab(client, other)
    sync(engine)
    assert listing(client, p)[0]["task_states"]["a"]["state"] == "WAITING"
    lab(client, p)
    sync(engine)
    run = listing(client, p)[0]
    assert run["task_states"]["a"]["state"] == "READY"
    assert run["task_states"]["b"]["state"] == "WAITING"
    finished = decide(client, p, run, "RESOLVE", item_key="a")
    assert finished.status_code == 200, finished.text
    run = finished.json()
    assert run["task_states"]["a"]["state"] == "RESOLVED"
    assert run["task_states"]["b"]["state"] == "READY"
    assert decide(client, p, run, "RESOLVE", item_key="b").status_code == 200


def test_cancel_does_not_unlock_and_plan_adjustment_is_audited(workspace):
    client, engine = workspace
    p = patient(client)
    run = plan(client, engine, p)
    run = decide(client, p, run, "DISMISS", item_key="a").json()
    assert run["task_states"]["b"]["state"] == "WAITING"
    tasks = deepcopy(run["result"]["tasks"])
    tasks[1]["depends_on"] = []
    reply = decide(client, p, run, "UPDATE", tasks=tasks)
    assert reply.status_code == 200, reply.text
    assert reply.json()["task_states"]["b"]["state"] == "READY"
    assert any(h.get("action") == "UPDATE" for h in reply.json()["history"])
    assert decide(client, p, run, "UPDATE", tasks=tasks).status_code == 409


def test_multiple_results_require_clarification(workspace):
    client, engine = workspace
    p = patient(client)
    plan(client, engine, p)
    lab(client, p)
    lab(client, p)
    sync(engine)
    run = listing(client, p)[0]
    assert run["task_states"]["a"]["state"] == "CLARIFY"
    assert decide(client, p, run, "RESOLVE", item_key="a").status_code == 409


def test_unconfigured_model_reports_failure_without_template(workspace, monkeypatch):
    from apps.api.app.settings import get_settings

    client, engine = workspace
    p = patient(client)
    enqueue(client, p)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    get_settings.cache_clear()
    process_care_queue(engine)
    run = listing(client, p)[0]
    assert run["status"] == "FAILED"
    assert "未配置" in run["error"]
    assert "result" not in run


def test_claimed_run_survives_worker_restart_as_explicit_failure(workspace):
    from datetime import timedelta

    from packages.contracts import utcnow

    client, engine = workspace
    p = patient(client)
    run = enqueue(client, p)
    with Session(engine) as session:
        row = session.get(CareAssistanceRow, run["run_id"])
        row.status = "RUNNING"
        row.updated_at = utcnow() - timedelta(hours=1)
        session.commit()
    process_care_queue(engine)
    assert listing(client, p)[0]["status"] == "FAILED"


def test_model_batch_format_is_fully_consumed_and_only_reads_are_allowed():
    import httpx

    from apps.api.app.settings import Settings
    from apps.worker.worker.care_assistant import CareFormatError, model_turn

    settings = Settings(deepseek_api_key="fake-test-only-key")

    def response(content):
        return httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
            )
        )

    batch = model_turn(
        [], settings, transport=response('{"tool":"read_documents"}\n{"tool":"read_labs"}')
    )
    assert [call["tool"] for call in batch["batch"]] == ["read_documents", "read_labs"]
    for bad in (
        '{"tool":"read_documents"} trailing text',
        '{"tool":"read_documents"}\n{"result":{}}',
    ):
        with pytest.raises(CareFormatError):
            model_turn([], settings, transport=response(bad))


def test_prepare_can_repair_format_once_without_losing_scope(workspace):
    from apps.worker.worker.care_assistant import CareFormatError

    client, engine = workspace
    p = patient(client)
    enqueue(client, p)
    replies = iter(
        [
            CareFormatError("invalid JSON"),
            {"batch": [{"tool": name} for name in ("read_tasks", "read_labs", "read_documents")]},
            {"result": output()},
        ]
    )

    def turn(messages):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    process_care_queue(engine, turn=turn)
    run = listing(client, p)[0]
    assert run["status"] == "READY", run
    assert len(run["trace"]) == 3


def test_old_plan_cannot_be_accepted_after_patient_data_changes(workspace):
    client, engine = workspace
    p = patient(client)
    doc = submit(client, p, "培养结果出来后查看；处理后整理交接。")
    enqueue(client, p, "PLAN", doc["document_id"])
    process_care_queue(engine, turn=model(output(doc["document_id"])))
    lab(client, p)
    run = listing(client, p)[0]
    assert run["stale"]
    assert decide(client, p, run, "ACCEPT").status_code == 409
