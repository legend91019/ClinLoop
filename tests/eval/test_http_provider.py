import importlib
import json

import httpx
import pytest


def provider_module():
    module = importlib.import_module("eval.baselines.providers")
    assert hasattr(module, "HTTPModelProvider"), "opt-in HTTP model provider is missing"
    return module


def request_data():
    return {
        "patient_id": "SYN-P-1",
        "as_of": "2026-09-28T20:00:00+00:00",
        "records": [],
        "instruction": "SOURCE-PROMPT-DO-NOT-LOG",
    }


def completion(content=None, **overrides):
    if content is None:
        content = json.dumps({"patient_id": "SYN-P-1", "findings": [], "handoff": None})
    return {"choices": [{"finish_reason": "stop", "message": {"content": content, **overrides}}]}


def test_http_provider_sends_auth_strict_schema_and_parses_real_output():
    module = provider_module()
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json=completion())

    provider = module.HTTPModelProvider(
        endpoint="https://models.example/v1/chat/completions",
        model="configured-model",
        api_key="SECRET-KEY",
        transport=httpx.MockTransport(respond),
        timeout=3,
    )
    actual = provider.generate(request_data())
    assert actual == {"patient_id": "SYN-P-1", "findings": [], "handoff": None}
    request = captured[0]
    assert request.headers["authorization"] == "Bearer SECRET-KEY"
    assert str(request.url) == "https://models.example/v1/chat/completions"
    body = json.loads(request.content)
    assert body["model"] == "configured-model"
    schema = body["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["required"]) == {"patient_id", "findings", "handoff"}
    assert "SOURCE-PROMPT-DO-NOT-LOG" in body["messages"][0]["content"]
    assert request.extensions["timeout"]["read"] == 3
    assert provider.kind == "real"
    assert "SECRET-KEY" not in repr(provider)


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "http",
        "invalid_json",
        "invalid_prediction",
        "refusal",
        "truncated",
        "wrong_patient",
        "future",
        "coerced",
        "extra",
        "missing_root",
        "missing_nested",
        "bad_envelope",
    ],
)
def test_http_failures_are_safe_and_do_not_silently_become_empty_predictions(failure):
    module = provider_module()

    def respond(request):
        if failure == "missing_root":
            return httpx.Response(200, json=completion('{"patient_id":"SYN-P-1"}'))
        if failure == "missing_nested":
            return httpx.Response(
                200,
                json=completion(
                    '{"patient_id":"SYN-P-1","findings":[],"handoff":{"patient_id":"SYN-P-1","generated_at":"2026-09-28T20:00:00Z"}}'
                ),
            )
        if failure == "bad_envelope":
            return httpx.Response(200, json={"choices": [None]})
        if failure == "timeout":
            raise httpx.ReadTimeout("SECRET-KEY SOURCE-PROMPT-DO-NOT-LOG", request=request)
        if failure == "http":
            return httpx.Response(401, text="SECRET-KEY SOURCE-PROMPT-DO-NOT-LOG")
        if failure == "invalid_json":
            return httpx.Response(200, json=completion("NOT JSON SECRET-KEY"))
        if failure == "invalid_prediction":
            return httpx.Response(
                200,
                json=completion('{"patient_id": "SYN-P-1", "findings": [{"bad":"SECRET-KEY"}]}'),
            )
        if failure == "refusal":
            return httpx.Response(200, json=completion(refusal="SECRET-KEY"))
        if failure == "truncated":
            body = completion()
            body["choices"][0]["finish_reason"] = "length"
            return httpx.Response(200, json=body)
        if failure == "wrong_patient":
            return httpx.Response(
                200, json=completion('{"patient_id": "OTHER", "findings": [], "handoff": null}')
            )
        if failure == "future":
            return httpx.Response(
                200,
                json=completion(
                    '{"patient_id": "SYN-P-1", "findings": [], "handoff": {"patient_id":"SYN-P-1","item_ids":[],"generated_at":"2026-09-29T20:00:00Z"}}'
                ),
            )
        if failure == "coerced":
            return httpx.Response(
                200,
                json=completion(
                    '{"patient_id": "SYN-P-1", "findings": [], "handoff": {"patient_id":"SYN-P-1","item_ids":[12],"generated_at":"2026-09-28T20:00:00Z"}}'
                ),
            )
        return httpx.Response(
            200,
            json=completion(
                '{"patient_id": "SYN-P-1", "findings": [], "handoff": null, "secret":"SECRET-KEY"}'
            ),
        )

    provider = module.HTTPModelProvider(
        endpoint="https://models.example/v1/chat/completions",
        model="m",
        api_key="SECRET-KEY",
        transport=httpx.MockTransport(respond),
    )
    with pytest.raises(module.ModelProviderError) as raised:
        provider.generate(request_data())
    assert "SECRET-KEY" not in str(raised.value)
    assert "SOURCE-PROMPT-DO-NOT-LOG" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_configured_credentials_do_not_enable_http_unless_explicit_provider_selected(monkeypatch):
    from eval.baselines import make_handler
    from eval.generators.cases import generate_cases
    from eval.replay.replayer import replay

    monkeypatch.setenv("CLINLOOP_EVAL_ENDPOINT", "https://models.example/v1/chat/completions")
    monkeypatch.setenv("CLINLOOP_EVAL_MODEL", "m")
    monkeypatch.setenv("CLINLOOP_EVAL_API_KEY", "SECRET-KEY")

    def forbidden(*args, **kwargs):
        pytest.fail("default baseline must not call HTTP")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    result = replay(generate_cases(1, 42)[0], make_handler("direct_llm"))
    assert result.model_calls[0]["kind"] == "mock"


def test_http_prediction_report_omits_credentials_endpoint_and_prompts():
    module = provider_module()
    from eval.generators.cases import generate_cases
    from eval.metrics.report import run_all_methods

    def respond(request):
        body = json.loads(request.content)
        observed = json.loads(body["messages"][1]["content"])
        return httpx.Response(
            200,
            json=completion(
                json.dumps({"patient_id": observed["patient_id"], "findings": [], "handoff": None})
            ),
        )

    provider = module.HTTPModelProvider(
        endpoint="https://PRIVATE-ENDPOINT.example/v1/chat/completions",
        model="test-real-model",
        api_key="SECRET-KEY",
        transport=httpx.MockTransport(respond),
    )
    report = run_all_methods(generate_cases(1, 42)[0:1], provider).model_dump_json()
    assert "SECRET-KEY" not in report
    assert "PRIVATE-ENDPOINT" not in report
    assert "response_schema" not in report
    assert '"provider_kind":"real"' in report


def test_real_factory_requires_explicit_configuration_and_never_calls_network(monkeypatch):
    module = provider_module()
    for name in ("CLINLOOP_EVAL_ENDPOINT", "CLINLOOP_EVAL_MODEL", "CLINLOOP_EVAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError):
        module.real_http_provider()
    monkeypatch.setenv("CLINLOOP_EVAL_ENDPOINT", "https://models.example/v1/chat/completions")
    monkeypatch.setenv("CLINLOOP_EVAL_MODEL", "m")
    monkeypatch.setenv("CLINLOOP_EVAL_API_KEY", "SECRET-KEY")
    provider = module.real_http_provider()
    assert provider.kind == "real"
    assert provider.name == "m"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:SECRET-KEY@models.example/v1/chat/completions",
        "https://models.example/v1/chat/completions?api_key=SECRET-KEY",
        "http://models.example/v1/chat/completions",
    ],
)
def test_provider_rejects_credential_urls_and_remote_cleartext(url):
    module = provider_module()
    with pytest.raises(ValueError) as raised:
        module.HTTPModelProvider(endpoint=url, model="m", api_key="SECRET-KEY")
    assert "SECRET-KEY" not in str(raised.value)
