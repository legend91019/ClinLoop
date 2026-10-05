"""Small API safety helpers shared by request handling and audit logging."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = frozenset(
    {"api_key", "authorization", "password", "secret", "token", "access_token"}
)


def redact_sensitive(value: Any) -> Any:
    """Return a JSON-like value with credential-shaped fields removed."""
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive(item) for item in value)
    return value
