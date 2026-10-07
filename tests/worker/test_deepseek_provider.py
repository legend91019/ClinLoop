from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from apps.api.app.settings import Settings
from apps.worker.worker.model_contracts import AgentContext
from apps.worker.worker.providers import (
    DeepSeekProvider,
    ModelProviderError,
    build_model_provider,
)
from packages.contracts import ActorRef, ClinicalEvent, EventType


def context() -> AgentContext:
    now = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
    return AgentContext(
        event=ClinicalEvent(
            event_id="EVT-PROVIDER-1",
            patient_id="P-1001",
            encounter_id="ENC-2001",
            event_type=EventType.NOTE_CREATED,
            event_time=now,
            source_time=now,
            payload_ref="NOTE-PROVIDER-1",
            actor=ActorRef(actor_id="DR-TEST", role="PHYSICIAN"),
            payload={"text": "复查血培养"},
        )
    )


def provider(transport: httpx.BaseTransport) -> DeepSeekProvider:
    return DeepSeekProvider(
        endpoint="https://api.deepseek.com/v1/chat/completions",
        model="deepseek-chat",
        api_key="test-secret-key",
        timeout=3,
        transport=transport,
    )


def response_body(content: str):
    return {
        "id": "chatcmpl-test",
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
    }


def valid_proposal() -> dict:
    return {
        "patient_id": "P-1001",
        "intent_type": "FOLLOW_RESULT",
        "goal": "Follow up the blood culture result",
        "rationale": "The note asks for a result follow-up.",
        "expected_evidence": ["blood_culture_result"],
        "waiting_for": ["LAB_RESULT_CREATED"],
        "priority": "HIGH",
        "confidence": 0.9,
        "evidence_refs": [],
    }


def test_provider_sends_auth_and_parses_strict_json() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json=response_body(json.dumps(valid_proposal())))

    provider_instance = provider(httpx.MockTransport(handler))
    result = provider_instance.analyze(context())

    assert result.patient_id == "P-1001"
    assert seen["request"].headers["authorization"] == "Bearer test-secret-key"
    body = json.loads(seen["request"].content)
    assert body["model"] == "deepseek-chat"
    assert body["stream"] is False
    assert "blood_culture_result" in body["messages"][0]["content"]
    assert "test-secret-key" not in repr(provider_instance)


def test_provider_rejects_non_https_public_endpoint() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        DeepSeekProvider(
            endpoint="http://api.deepseek.com/v1/chat/completions",
            model="deepseek-chat",
            api_key="secret",
            timeout=3,
        )


def test_provider_maps_timeout_to_safe_error_code() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    with pytest.raises(ModelProviderError, match="MODEL_TIMEOUT"):
        provider(httpx.MockTransport(handler)).analyze(context())


def test_provider_maps_invalid_response_without_remote_text() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ModelProviderError, match="MODEL_INVALID_RESPONSE") as raised:
        provider(httpx.MockTransport(handler)).analyze(context())
    assert "simulated" not in str(raised.value)


def test_provider_factory_requires_explicit_deepseek_credentials() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        build_model_provider(Settings(agent_provider="deepseek", deepseek_api_key=""))


def test_mock_provider_is_selected_without_network_configuration() -> None:
    selected = build_model_provider(Settings(agent_provider="mock"))
    assert selected.kind == "mock"
    assert selected.analyze(context()).patient_id == "P-1001"
