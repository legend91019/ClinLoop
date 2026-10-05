"""Injectable provider contract. Default MOCK is intentionally an abstaining stub.

No engineered gap rules are represented as LLM behavior. A real implementation
can be injected in Python or loaded with --provider module:factory. Its factory
owns SDK/configuration/secrets; report traces contain metadata, never prompts,
keys, HTTP headers, or response bodies.
"""

from __future__ import annotations

import importlib
import json
import math
import os
import re
from datetime import datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError

from eval.models import CasePrediction


class ModelProvider(Protocol):
    kind: Literal["mock", "real"]
    name: str

    def generate(self, request: dict[str, Any]) -> dict[str, Any]: ...


class MockModelProvider:
    kind = "mock"
    name = "deterministic-abstaining-MOCK"

    def generate(self, request):
        # No model inference and no rules-based detection. This exercises the
        # plumbing and makes the unmeasured LLM quality impossible to misread.
        return {
            "patient_id": request["patient_id"],
            "findings": [],
            "handoff": {
                "patient_id": request["patient_id"],
                "item_ids": [],
                "evidence_ids": [],
                "generated_at": request["as_of"],
            },
        }


def load_provider(reference: str) -> ModelProvider:
    module_name, separator, factory_name = reference.partition(":")
    if not separator or not module_name or not factory_name.isidentifier():
        raise ValueError("provider must be module:factory")
    provider = getattr(importlib.import_module(module_name), factory_name)()
    validate_provider(provider)
    return provider


def validate_provider(provider: ModelProvider) -> None:
    if getattr(provider, "kind", None) not in {"mock", "real"}:
        raise ValueError("provider must explicitly declare kind mock or real")
    if not isinstance(getattr(provider, "name", None), str) or not provider.name.strip():
        raise ValueError("provider must declare a public model name")
    if not callable(getattr(provider, "generate", None)):
        raise ValueError("provider must implement generate(request)")


class ModelProviderError(RuntimeError):
    """Safe error code only. Never retain remote text in the public message."""


def _strict_schema():
    # Chat structured outputs requires every object property in `required`;
    # optional properties remain required-but-nullable. Strip local defaults.
    # https://developers.openai.com/api/docs/guides/structured-outputs
    schema = CasePrediction.model_json_schema()

    def visit(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def _require_declared_fields(value, schema, root=None):
    """Do not fill omitted model output fields with local Pydantic defaults.

    This enforces recursive required keys even if a compatible HTTP server
    ignores strict=true. Type/enum/time/extra validation remains in Pydantic.
    """
    root = schema if root is None else root
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].rsplit("/", 1)[1]]
    if "anyOf" in schema:
        if value is None and any(branch.get("type") == "null" for branch in schema["anyOf"]):
            return
        schema = next(branch for branch in schema["anyOf"] if branch.get("type") != "null")
        return _require_declared_fields(value, schema, root)
    if schema.get("type") == "object" and isinstance(value, dict):
        if not set(schema["required"]) <= value.keys():
            raise ModelProviderError("MODEL_MISSING_FIELDS")
        for name, child in schema["properties"].items():
            _require_declared_fields(value[name], child, root)
    elif schema.get("type") == "array" and isinstance(value, list):
        for child in value:
            _require_declared_fields(child, schema["items"], root)


class HTTPModelProvider:
    """Opt-in OpenAI-compatible chat completions with strict JSON predictions.

    Only generate() performs HTTP. Errors fail the evaluation rather than
    fabricating an abstention. No automatic retry or paid fallback inference.
    Compatible endpoints must support response_format=json_schema (strict).
    """

    kind = "real"

    def __init__(
        self, *, endpoint: str, model: str, api_key: str, timeout: float = 30.0, transport=None
    ):
        parsed = urlsplit(endpoint)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not (parsed.scheme == "https" or local_http)
        ):
            raise ValueError(
                "endpoint must use HTTPS (or loopback HTTP), without URL credentials/query/fragment"
            )
        if not isinstance(api_key, str) or not api_key.strip() or any(c in api_key for c in "\r\n"):
            raise ValueError("a nonempty API key is required")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}", model) or api_key in model:
            raise ValueError("a public model identifier is required")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number")
        self.name = model
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    def generate(self, request):
        import httpx

        body = {
            "model": self.name,
            "messages": [
                {"role": "system", "content": request["instruction"]},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            k: v
                            for k, v in request.items()
                            if k not in {"instruction", "response_schema"}
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "CasePrediction",
                    "strict": True,
                    "schema": _strict_schema(),
                },
            },
            "stream": False,
        }
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.post(
                    self._endpoint, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
                )
            if response.status_code < 200 or response.status_code >= 300:
                raise ModelProviderError("MODEL_HTTP_ERROR")
            if len(response.content) > 2_000_000:
                raise ModelProviderError("MODEL_RESPONSE_TOO_LARGE")
            result = response.json()
            choices = result["choices"]
            if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
                raise ModelProviderError("MODEL_INCOMPLETE_RESPONSE")
            message = choices[0]["message"]
            if message.get("refusal"):
                raise ModelProviderError("MODEL_REFUSAL")
            content = message["content"]
            if not isinstance(content, str):
                raise ModelProviderError("MODEL_INVALID_RESPONSE")
            _require_declared_fields(
                json.loads(content), body["response_format"]["json_schema"]["schema"]
            )
            prediction = CasePrediction.model_validate_json(content, strict=True)
            when = datetime.fromisoformat(request["as_of"])
            if (
                prediction.patient_id != request["patient_id"]
                or any(f.detected_at > when for f in prediction.findings)
                or prediction.handoff
                and prediction.handoff.generated_at > when
            ):
                raise ModelProviderError("MODEL_INVALID_PREDICTION")
            return prediction.model_dump(mode="json")
        except httpx.TimeoutException:
            raise ModelProviderError("MODEL_TIMEOUT") from None
        except httpx.HTTPError:
            raise ModelProviderError("MODEL_TRANSPORT_ERROR") from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, ValidationError):
            raise ModelProviderError("MODEL_INVALID_RESPONSE") from None


def real_http_provider() -> HTTPModelProvider:
    """Factory loaded only by explicit --provider eval.baselines.providers:real_http_provider.

    CLINLOOP_EVAL_ENDPOINT is the full /v1/chat/completions URL;
    CLINLOOP_EVAL_MODEL and CLINLOOP_EVAL_API_KEY have no implicit defaults.
    CLINLOOP_EVAL_TIMEOUT_SECONDS optionally sets the timeout (default 30).
    Merely having environment configuration does not enable external inference.
    """
    names = ("CLINLOOP_EVAL_ENDPOINT", "CLINLOOP_EVAL_MODEL", "CLINLOOP_EVAL_API_KEY")
    if any(not os.environ.get(name, "").strip() for name in names):
        raise ValueError(
            "real HTTP provider requires explicit endpoint/model/API key configuration"
        )
    try:
        timeout = float(os.environ.get("CLINLOOP_EVAL_TIMEOUT_SECONDS", "30"))
    except ValueError:
        raise ValueError("invalid HTTP provider timeout configuration") from None
    return HTTPModelProvider(
        endpoint=os.environ[names[0]],
        model=os.environ[names[1]],
        api_key=os.environ[names[2]],
        timeout=timeout,
    )
