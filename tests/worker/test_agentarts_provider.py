from __future__ import annotations

import json

import httpx
import pytest

from apps.api.app.settings import Settings
from apps.worker.worker.providers import (
    AgentArtsProvider,
    ModelProviderError,
    build_model_provider,
)
from tests.worker.test_deepseek_provider import context, valid_proposal


def provider(transport: httpx.BaseTransport) -> AgentArtsProvider:
    return AgentArtsProvider(
        endpoint="https://agentarts.example.cn",
        runtime_name="agent-arts-test-runtime",
        api_key="test-key",
        timeout=3,
        transport=transport,
    )


def test_published_runtime_request_and_strict_proposal() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={"event": "message", "data": {"text": json.dumps(valid_proposal())}},
        )

    selected = provider(httpx.MockTransport(handler))
    proposal = selected.analyze(context())

    assert proposal.patient_id == "P-1001"
    request = seen["request"]
    assert request.url.path == "/runtimes/agent-arts-test-runtime/invocations"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["x-invoke-mode"] == "published"
    assert request.headers["x-hw-agentarts-session-id"]
    body = json.loads(request.content)
    assert body["inputs"]["schema_version"] == "1.0"
    assert body["inputs"]["patient_id"] == "P-1001"
    assert body["inputs"]["trigger_event_id"] == "EVT-PROVIDER-1"
    assert json.loads(body["inputs"]["context_json"])["event"]["patient_id"] == "P-1001"
    assert body["inputs"]["query"] == body["inputs"]["context_json"]
    assert "test-key" not in repr(selected)
    assert selected.metadata.provider == "agentarts"


def test_invalid_runtime_output_fails_closed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"event": "message", "data": {"text": "hello"}})

    with pytest.raises(ModelProviderError, match="MODEL_INVALID_RESPONSE"):
        provider(httpx.MockTransport(handler)).analyze(context())


def test_streamed_runtime_uses_final_end_node_message() -> None:
    body = (
        'data: {"event":"message","data":{"node_id":"progress","text":"working"}}\n\n'
        + "data: "
        + json.dumps(
            {
                "event": "message",
                "data": {"node_id": "node_end", "text": json.dumps(valid_proposal())},
            }
        )
        + "\n\n"
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    assert provider(httpx.MockTransport(handler)).analyze(context()).patient_id == "P-1001"


def test_runtime_http_error_is_safe() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="private error with key")

    with pytest.raises(ModelProviderError, match="MODEL_HTTP_ERROR") as error:
        provider(httpx.MockTransport(handler)).analyze(context())
    assert "private" not in str(error.value)


def test_factory_requires_published_runtime_configuration() -> None:
    with pytest.raises(ValueError, match="AGENTARTS"):
        build_model_provider(Settings(_env_file=None, agent_provider="agentarts"))


def test_factory_selects_agentarts() -> None:
    selected = build_model_provider(
        Settings(
            _env_file=None,
            agent_provider="agentarts",
            agentarts_endpoint="https://agentarts.example.cn",
            agentarts_runtime_name="agent-arts-test-runtime",
            agentarts_api_key="test-key",
        )
    )
    assert selected.kind == "real"
    assert selected.metadata.provider == "agentarts"
