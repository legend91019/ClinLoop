"""Opt-in model providers for the WorkflowAgent."""

from __future__ import annotations

import json
import math
import re
import time
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx

from apps.api.app.settings import Settings
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from packages.contracts import EventType, IntentType

__all__ = [
    "AgentArtsProvider",
    "DeepSeekProvider",
    "ModelProvider",
    "ModelProviderError",
    "MockProvider",
    "build_model_provider",
]


class ModelProviderError(RuntimeError):
    """An external model failure represented by a safe stable error code."""


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    model: str
    latency_ms: int | None = None
    proposal_ref: str | None = None
    error_code: str | None = None

    def as_dict(self) -> dict[str, str | int]:
        result: dict[str, str | int] = {
            "provider": self.provider,
            "model": self.model,
        }
        if self.latency_ms is not None:
            result["latency_ms"] = self.latency_ms
        if self.proposal_ref is not None:
            result["proposal_ref"] = self.proposal_ref
        if self.error_code is not None:
            result["error_code"] = self.error_code
        return result


class ModelProvider(Protocol):
    kind: Literal["mock", "real"]
    name: str
    metadata: ProviderMetadata

    def analyze(self, context: AgentContext) -> AgentProposal: ...


class MockProvider:
    """Deterministic provider used by tests and offline demos."""

    kind: Literal["mock"] = "mock"
    name = "deterministic-mock"

    def __init__(self) -> None:
        self.metadata = ProviderMetadata(provider=self.name, model="mock")

    def analyze(self, context: AgentContext) -> AgentProposal:
        event = context.event
        if event.event_type is EventType.NOTE_CREATED:
            return AgentProposal(
                patient_id=event.patient_id,
                intent_type=IntentType.FOLLOW_RESULT,
                goal="Follow up the repeat blood culture result",
                rationale="The deterministic offline provider recognizes a result follow-up note.",
                expected_evidence=["blood_culture_result"],
                waiting_for=[EventType.LAB_RESULT_CREATED],
                requested_tools=[],
                priority="HIGH",
                confidence=0.8,
            )
        return AgentProposal(
            patient_id=event.patient_id,
            intent_type=context.current_intent.intent_type if context.current_intent else None,
            goal="Review the current workflow event",
            rationale="The deterministic offline provider requires workflow verification.",
            priority="NORMAL",
            confidence=0.5,
            requested_tools=(
                ["get_labs", "get_progress_notes"]
                if event.event_type is EventType.LAB_RESULT_CREATED
                else []
            ),
        )


class DeepSeekProvider:
    """OpenAI-compatible DeepSeek chat-completions provider."""

    kind: Literal["real"] = "real"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        api_key: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if not parsed.hostname or not (parsed.scheme == "https" or local_http):
            raise ValueError("DeepSeek endpoint must use HTTPS (or loopback HTTP)")
        if not api_key.strip() or any(char in api_key for char in "\r\n"):
            raise ValueError("DEEPSEEK_API_KEY must be nonempty")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", model):
            raise ValueError("DEEPSEEK_MODEL is invalid")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("DeepSeek timeout must be numeric")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("DeepSeek timeout must be positive")
        self.name = model
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        self.metadata = ProviderMetadata(provider="deepseek", model=model)

    def __repr__(self) -> str:
        return f"DeepSeekProvider(model={self.name!r}, endpoint={self._endpoint!r})"

    def analyze(self, context: AgentContext) -> AgentProposal:
        body = {
            "model": self.name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a clinical workflow continuity assistant. "
                        "Return only JSON matching the requested fields. "
                        "Propose workflow candidates; never diagnose, prescribe, "
                        "or claim that a missing record proves absence. "
                        "Set requested_tools to only the read-only tool names needed "
                        "to verify this event: get_patient_snapshot, get_recent_events, "
                        "get_orders, get_labs, get_consults, get_progress_notes, "
                        "get_handoff, get_patient_evidence. "
                        "For a note requesting blood culture result follow-up, "
                        "use intent_type FOLLOW_RESULT, expected_evidence "
                        "['blood_culture_result'], and waiting_for "
                        "['LAB_RESULT_CREATED']. Preserve patient_id exactly. "
                        "Return exactly one JSON object with every field in this example "
                        "and no additional fields: "
                        '{"patient_id":"P-1001","intent_type":"FOLLOW_RESULT",'
                        '"goal":"Follow up blood culture result",'
                        '"rationale":"The note requests result follow-up",'
                        '"expected_evidence":["blood_culture_result"],'
                        '"waiting_for":["LAB_RESULT_CREATED"],'
                        '"priority":"HIGH","confidence":0.8,'
                        '"evidence_refs":[],"requested_tools":[]}. '
                        "Replace the example patient_id with the exact event patient_id. "
                        "evidence_refs may contain only IDs or payload_ref values from "
                        "recent_events or IDs from visible_evidence; otherwise use []. "
                        "For a lab result, select get_labs and get_progress_notes. "
                        "If the event does not support an intent, use null intent_type, "
                        "empty expected_evidence and waiting_for arrays, and explain uncertainty "
                        "in rationale. Never invent evidence references."
                    ),
                },
                {
                    "role": "user",
                    "content": context.model_dump_json(),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": 1200,
            "stream": False,
        }
        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(
                    self._endpoint,
                    json=body,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            latency_ms = int((time.monotonic() - started) * 1000)
            if response.status_code < 200 or response.status_code >= 300:
                self._set_metadata(latency_ms, error_code="MODEL_HTTP_ERROR")
                raise ModelProviderError("MODEL_HTTP_ERROR")
            if len(response.content) > 2_000_000:
                self._set_metadata(latency_ms, error_code="MODEL_RESPONSE_TOO_LARGE")
                raise ModelProviderError("MODEL_RESPONSE_TOO_LARGE")
            result = response.json()
            choice = result["choices"][0]
            if choice.get("finish_reason") == "length":
                self._set_metadata(latency_ms, error_code="MODEL_TRUNCATED_RESPONSE")
                raise ModelProviderError("MODEL_TRUNCATED_RESPONSE")
            message = choice["message"]
            if message.get("refusal"):
                self._set_metadata(latency_ms, error_code="MODEL_REFUSAL")
                raise ModelProviderError("MODEL_REFUSAL")
            content = message["content"]
            if not isinstance(content, str):
                raise ValueError("content is not a string")
            proposal = AgentProposal.model_validate_json(content, strict=True)
            self._set_metadata(latency_ms, proposal_ref=proposal.patient_id)
            return proposal
        except ModelProviderError:
            raise
        except httpx.TimeoutException:
            self._set_metadata(0, error_code="MODEL_TIMEOUT")
            raise ModelProviderError("MODEL_TIMEOUT") from None
        except httpx.HTTPError:
            self._set_metadata(0, error_code="MODEL_TRANSPORT_ERROR")
            raise ModelProviderError("MODEL_TRANSPORT_ERROR") from None
        except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
            self._set_metadata(0, error_code="MODEL_INVALID_RESPONSE")
            raise ModelProviderError("MODEL_INVALID_RESPONSE") from None

    def _set_metadata(
        self,
        latency_ms: int,
        *,
        proposal_ref: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.metadata = ProviderMetadata(
            provider="deepseek",
            model=self.name,
            latency_ms=latency_ms,
            proposal_ref=proposal_ref,
            error_code=error_code,
        )


class AgentArtsProvider:
    """Call a published AgentArts workflow; output is still subject to ClinLoop Guard."""

    kind: Literal["real"] = "real"

    def __init__(
        self,
        *,
        endpoint: str,
        runtime_name: str,
        api_key: str,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            not parsed.hostname
            or parsed.query
            or parsed.fragment
            or not (parsed.scheme == "https" or local_http)
        ):
            raise ValueError("AGENTARTS_ENDPOINT must use HTTPS (or loopback HTTP)")
        if not re.fullmatch(r"agent-arts-[A-Za-z0-9_-]{1,53}", runtime_name):
            raise ValueError("AGENTARTS_RUNTIME_NAME must name a published runtime")
        if not api_key.strip() or any(char in api_key for char in "\r\n"):
            raise ValueError("AGENTARTS_API_KEY must be nonempty")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("AgentArts timeout must be positive")
        self.name = runtime_name
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport
        self.metadata = ProviderMetadata(provider="agentarts", model=runtime_name)

    def __repr__(self) -> str:
        return f"AgentArtsProvider(runtime_name={self.name!r})"

    def analyze(self, context: AgentContext) -> AgentProposal:
        started = time.monotonic()
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self._endpoint}/runtimes/{self.name}/invocations",
                    json={
                        "inputs": {
                            "schema_version": "1.0",
                            "context_json": context.model_dump_json(),
                            "request_id": context.event.event_id,
                            "patient_id": context.event.patient_id,
                            "trigger_event_id": context.event.event_id,
                        }
                    },
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "x-hw-agentarts-session-id": uuid.uuid4().hex,
                        "X-Request-Id": uuid.uuid4().hex,
                        "X-Invoke-Mode": "published",
                    },
                )
            latency = int((time.monotonic() - started) * 1000)
            if not 200 <= response.status_code < 300:
                self._set_metadata(latency, error_code="MODEL_HTTP_ERROR")
                raise ModelProviderError("MODEL_HTTP_ERROR")
            if len(response.content) > 2_000_000:
                self._set_metadata(latency, error_code="MODEL_RESPONSE_TOO_LARGE")
                raise ModelProviderError("MODEL_RESPONSE_TOO_LARGE")
            if "text/event-stream" in response.headers.get("content-type", ""):
                messages = [
                    json.loads(line[5:].strip())
                    for line in response.text.splitlines()
                    if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}
                ]
                result = next(
                    message
                    for message in reversed(messages)
                    if message.get("data", {}).get("node_id") == "node_end"
                    or message.get("data", {}).get("node_type") == "End"
                )
            else:
                result = response.json()
            output = result["data"]["text"]
            if isinstance(output, dict):
                output = output.get("proposal_json", output)
            if not isinstance(output, str):
                raise ValueError("AgentArts end node must return proposal JSON text")
            envelope = json.loads(output)
            if isinstance(envelope, dict) and "proposal_json" in envelope:
                envelope = envelope["proposal_json"]
                if isinstance(envelope, str):
                    envelope = json.loads(envelope)
            proposal = AgentProposal.model_validate_json(json.dumps(envelope), strict=True)
            self._set_metadata(latency, proposal_ref=proposal.patient_id)
            return proposal
        except ModelProviderError:
            raise
        except httpx.TimeoutException:
            self._set_metadata(0, error_code="MODEL_TIMEOUT")
            raise ModelProviderError("MODEL_TIMEOUT") from None
        except httpx.HTTPError:
            self._set_metadata(0, error_code="MODEL_TRANSPORT_ERROR")
            raise ModelProviderError("MODEL_TRANSPORT_ERROR") from None
        except (ValueError, TypeError, KeyError, IndexError, StopIteration):
            self._set_metadata(0, error_code="MODEL_INVALID_RESPONSE")
            raise ModelProviderError("MODEL_INVALID_RESPONSE") from None

    def _set_metadata(
        self,
        latency_ms: int,
        *,
        proposal_ref: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.metadata = ProviderMetadata(
            provider="agentarts",
            model=self.name,
            latency_ms=latency_ms,
            proposal_ref=proposal_ref,
            error_code=error_code,
        )


def build_model_provider(settings: Settings) -> ModelProvider:
    provider = settings.agent_provider.strip().lower()
    if provider == "mock":
        return MockProvider()
    if provider == "deepseek":
        if not settings.deepseek_api_key.strip():
            raise ValueError("DEEPSEEK_API_KEY is required when AGENT_PROVIDER=deepseek")
        return DeepSeekProvider(
            endpoint=f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key,
            timeout=settings.agent_timeout_seconds,
        )
    if provider == "agentarts":
        return AgentArtsProvider(
            endpoint=settings.agentarts_endpoint,
            runtime_name=settings.agentarts_runtime_name,
            api_key=settings.agentarts_api_key,
            timeout=settings.agent_timeout_seconds,
        )
    raise ValueError("AGENT_PROVIDER must be mock, deepseek or agentarts")
