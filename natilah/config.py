"""Configuration management for Natilah."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_GPU_COSTS: dict[str, float] = {
    "A100-80GB": 2.21,
    "H100-80GB": 3.49,
    "H200-141GB": 4.50,
    "B200-192GB": 5.80,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str = "sqlite+aiosqlite:///./data/natilah.db"
    safety_mode: str = "read_only"
    log_level: str = "INFO"
    default_cost_per_gpu_hour: float = 2.21
    xai_api_key: str | None = None
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4.6"
    agent_mode: str = "hybrid"


settings = Settings()
