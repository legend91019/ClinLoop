from __future__ import annotations

import pytest

from apps.api.app.settings import Settings
from apps.worker.worker.providers import build_model_provider


def test_mock_provider_does_not_enable_network_from_a_key() -> None:
    provider = build_model_provider(
        Settings(agent_provider="mock", deepseek_api_key="local-only-test-key")
    )
    assert provider.kind == "mock"


def test_deepseek_provider_requires_a_key() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        build_model_provider(Settings(agent_provider="deepseek"))
