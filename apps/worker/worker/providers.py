"""Opt-in model providers for the WorkflowAgent."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

import httpx

from apps.api.app.settings import Settings
from apps.worker.worker.model_contracts import AgentContext, AgentProposal
from packages.contracts import EventType, IntentType

__all__ = [
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
                        "or claim that a missing record proves absence."
                    ),
                },
                {
                    "role": "user",
                    "content": context.model_dump_json(),
                },
            ],
            "response_format": {"type": "json_object"},
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
            message = result["choices"][0]["message"]
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
    raise ValueError("AGENT_PROVIDER must be mock or deepseek")
