"""Model prose, source validation, failure visibility and safe re-drafting."""

import json
from uuid import uuid4

import httpx
import pytest

from apps.api.app.settings import Settings
from apps.worker.worker.clinical_writing import (
    SECTIONS,
    DraftingError,
    demo_clinical_note,
    render_clinical_note,
    transcript_speaker,
    validate_draft,
    write_clinical_note,
)
from packages.contracts.interviews import ClinicalNoteDraft, ClinicalSection, ClinicalSentence
from tests.api.test_interviews import interviews, save
from tests.api.test_patient_workspace import HEADERS, patient
from tests.api.test_workspace_agent import drain


@pytest.mark.parametrize(
    "prefix",
    [
        "医生：",
        "主治医生：",
        "住院医师：",
        "主任医师：",
        "副主任医生：",
        "主管医生：",
        "经治医师：",
        "主治医生（对住院医师）：",
        "住院医师(对患者): ",
    ],
)
def test_clinical_titles_and_stage_directions_are_doctor_sources(prefix):
    kind, text = transcript_speaker(prefix + "复查血常规。")
    assert kind == "doctor"
    assert text == "复查血常规。"


def test_doctor_title_is_preserved_through_context_and_plan_validation(workspace):
    from sqlalchemy.orm import Session

    from apps.api.app.db_models import ClinicalDocumentRow
    from apps.api.app.repositories import ClinicalEventRepository
    from apps.worker.worker.clinical_note_workflow import build_context

    client, engine = workspace
    p = patient(client)
    created = save(
        client,
        p,
        transcript="主治医生：今天还发热吗？\n患者：没有发热。\n主治医生（对住院医师）：复查血常规，结果出来后提醒我查看。",
    ).json()
    with Session(engine) as session:
        event = ClinicalEventRepository(session).get(created["generation"]["event_id"])
        source = session.get(ClinicalDocumentRow, created["interview_id"])
        ctx = build_context(session, source, event, [])
        kinds = {item["source_id"]: item["kind"] for item in ctx["sources"]}
        assert kinds["T001"] == "question"
        assert kinds["T002"] == "patient"
        assert kinds["T003"] == "doctor"
        validate_draft(draft(ctx), ctx)


def context(kind="ROUND"):
    return {
        "kind": kind,
        "title": "查房记录",
        "section_order": SECTIONS[kind],
        "patient": {"display_name": "模拟患者", "sex": "女", "age": 42},
        "record_time": "2026-10-27T10:00:00+00:00",
        "admitted_at": None,
        "sources": [
            {"source_id": "T001", "kind": "question", "text": "医生：有发热吗？"},
            {"source_id": "T002", "kind": "patient", "text": "患者：没有发热。"},
            {
                "source_id": "T003",
                "kind": "doctor",
                "text": "医生：复查血常规，结果出来后提醒我查看。",
            },
        ],
    }


def draft(ctx):
    body = {
        "病情变化": [ClinicalSentence(text="患者诉无发热。", source_ids=["T002"])],
        "诊疗计划": [
            ClinicalSentence(text="复查血常规，结果回报后提醒经治医师查看。", source_ids=["T003"])
        ],
    }
    return ClinicalNoteDraft(
        sections=[
            ClinicalSection(heading=heading, sentences=body.get(heading, []))
            for heading in ctx["section_order"]
        ],
        missing_information=["查体及医生评估待补充。"],
    )


def test_real_provider_writes_prose_and_passes_source_bundle_to_model():
    ctx = context()

    def respond(request):
        body = json.loads(request.content)
        supplied = json.loads(body["messages"][1]["content"])
        assert supplied == ctx
        assert "连贯" in body["messages"][0]["content"]
        assert "不得改写" not in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": draft(ctx).model_dump_json()}}
                ]
            },
        )

    result = write_clinical_note(
        ctx, Settings(deepseek_api_key="synthetic-test-key"), transport=httpx.MockTransport(respond)
    )
    content = render_clinical_note(result, ctx)
    assert "【病情变化】\n患者诉无发热。" in content
    assert "医生：" not in content and "患者：" not in content
    assert "现有资料不足，待医生补充。" in content
    assert result.missing_information == ["查体及医生评估待补充。"]


def test_validation_failure_gets_one_grounded_repair_attempt():
    requests = []

    def respond(request):
        supplied = json.loads(json.loads(request.content)["messages"][1]["content"])
        requests.append(supplied)
        result = draft(context())
        if len(requests) == 1:
            result.sections[0].sentences[0].text = "体温38.5℃。"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": result.model_dump_json()}}
                ]
            },
        )

    result = write_clinical_note(
        context(),
        Settings(deepseek_api_key="synthetic-test-key"),
        transport=httpx.MockTransport(respond),
    )
    assert len(requests) == 2
    assert requests[1]["validation_error"] == "NOTE_DRAFT_UNSUPPORTED_NUMBER"
    assert requests[1]["sources"] == requests[0]["sources"]
    assert "38.5" not in render_clinical_note(result, context())


def test_invalid_model_result_is_not_accepted_after_repair_budget():
    calls = []

    def respond(request):
        calls.append(request)
        result = draft(context())
        result.sections[-1].sentences[0].source_ids = ["T002"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": result.model_dump_json()}}
                ]
            },
        )

    with pytest.raises(DraftingError, match="UNSUPPORTED_CLINICAL_PLAN"):
        write_clinical_note(
            context(),
            Settings(deepseek_api_key="synthetic-test-key"),
            transport=httpx.MockTransport(respond),
        )
    assert len(calls) == 2


@pytest.mark.parametrize(
    "status,error", [(401, "AUTH_ERROR"), (404, "MODEL_UNAVAILABLE"), (429, "RATE_LIMITED")]
)
def test_model_connection_failures_have_actionable_codes_without_response_leaks(status, error):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, text="private upstream detail")
    )
    with pytest.raises(DraftingError, match=error) as exc:
        write_clinical_note(
            context(), Settings(deepseek_api_key="synthetic-test-key"), transport=transport
        )
    assert "private upstream detail" not in str(exc.value)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("unknown", "INVALID_SOURCE"),
        ("question", "QUESTION_AS_FACT"),
        ("number", "UNSUPPORTED_NUMBER"),
        ("dialogue", "DIALOGUE_OUTPUT"),
        ("patient_plan", "UNSUPPORTED_CLINICAL_PLAN"),
        ("sections", "INVALID_SECTIONS"),
    ],
)
def test_rejects_untraceable_or_dialogue_output(mutation, error):
    ctx, result = context(), draft(context())
    sentence = result.sections[0].sentences[0]
    if mutation == "unknown":
        sentence.source_ids = ["WRONG"]
    elif mutation == "question":
        sentence.source_ids = ["T001"]
    elif mutation == "number":
        sentence.text = "体温37.8℃。"
    elif mutation == "dialogue":
        sentence.text = "患者：没有发热。"
    elif mutation == "patient_plan":
        result.sections[-1].sentences[0].source_ids = ["T002"]
    else:
        result.sections.reverse()
    with pytest.raises(DraftingError, match=error):
        validate_draft(result, ctx)


def test_no_key_saves_original_and_exposes_failure_instead_of_mock_success(workspace, monkeypatch):
    client, engine = workspace
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    from apps.api.app.settings import get_settings

    get_settings.cache_clear()
    p = patient(client)
    # Real writing is the API default, independent from AGENT_PROVIDER=mock.
    response = save(client, p, draft_mode="CLINICAL")
    assert response.status_code == 202
    drain(engine)
    source = interviews(client, p)[0]
    assert source["generation"]["status"] == "FAILED"
    assert source["generation"]["error"] == "NOTE_DRAFT_NOT_CONFIGURED"
    assert source["document"] is None
    assert source["transcript"] == response.json()["transcript"]
    config = client.get("/api/v1/clinical-writing/config").json()
    assert config["configured"] is False
    assert "key" not in str(config)


def test_redraft_keeps_signed_note_and_creates_new_model_draft(workspace, monkeypatch):
    client, engine = workspace
    p = patient(client)
    original = save(client, p).json()
    drain(engine)
    old = interviews(client, p)[0]["document"]
    path = f"/api/v1/patients/{p['patient_id']}/documents/{old['document_id']}"
    signed = client.post(
        path + "/submit",
        headers=HEADERS,
        json={"revision": 1, "signature_name": "模拟医生", "confirmed": True},
    )
    assert signed.status_code == 200, signed.text
    from apps.worker.worker import clinical_note_workflow

    captured = []

    def writer(ctx, settings):
        captured.append(ctx)
        # This integration stub replaces only the external model call.
        return demo_clinical_note(ctx)

    monkeypatch.setattr(clinical_note_workflow, "write_clinical_note", writer)
    route = f"/api/v1/patients/{p['patient_id']}/interviews/{original['interview_id']}/draft"
    body = {"request_id": uuid4().hex, "draft_mode": "CLINICAL"}
    assert client.post(route, headers=HEADERS, json=body).status_code == 202
    assert client.post(route, headers=HEADERS, json=body).status_code == 202
    assert (
        client.post(route, headers=HEADERS, json={**body, "request_id": uuid4().hex}).status_code
        == 409
    )
    drain(engine)
    fresh = interviews(client, p)[0]
    assert fresh["transcript"] == original["transcript"]
    assert fresh["document"]["document_id"] != old["document_id"]
    assert fresh["document"]["status"] == "DRAFT"
    assert fresh["document"]["generation"]["draft_mode"] == "CLINICAL"
    assert any(
        item["ref"] == old["document_id"]
        for item in captured[0]["sources"]
        if item["kind"] == "signed_note"
    )
    docs = client.get(
        f"/api/v1/patients/{p['patient_id']}/documents", params={"encounter_id": p["encounter_id"]}
    ).json()
    preserved = next(item for item in docs if item["document_id"] == old["document_id"])
    assert preserved["status"] == "SUBMITTED"
    assert preserved["signature"]["name"] == "模拟医生"
    # A network retry with the same request id never generates another version.
    assert (
        client.post(route, headers=HEADERS, json=body).json()["document"]["document_id"]
        == fresh["document"]["document_id"]
    )
    assert drain(engine) == []
