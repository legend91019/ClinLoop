"""Application settings, loaded from the environment.

Mirrors ``.env.example``. ``pydantic-settings`` gives us typed access and
a single place to see every knob — no scattered ``os.environ`` reads.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- persistence ---
    database_url: str = "postgresql+psycopg://clinloop:clinloop@localhost:5432/clinloop"
    redis_url: str = "redis://localhost:6379/0"
    event_bus: str = "noop"

    # --- ports ---
    api_port: int = 8000
    web_port: int = 5173

    # --- agent (consumed by the worker in task 5+) ---
    openai_api_key: str = ""
    agent_provider: str = "mock"
    agent_step_budget: int = 8
    agent_timeout_seconds: int = 30
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # --- api ---
    app_name: str = "ClinLoop API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor.

    Tests clear the cache via ``get_settings.cache_clear()`` after
    pointing ``DATABASE_URL`` at a scratch database.
    """
    return Settings()
