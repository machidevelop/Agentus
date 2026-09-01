"""Configuration management for Natilah."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_GPU_COSTS: dict[str, float] = {
    "P100-16GB": 0.60,
    "V100-16GB": 0.80,
    "V100-32GB": 1.10,
    "T4-16GB": 0.35,
    "A10-24GB": 1.10,
    "A100-40GB": 1.80,
    "A100-80GB": 2.21,
    "H100-80GB": 3.49,
    "H200-141GB": 4.50,
    "B200-192GB": 5.80,
    "A30-24GB": 1.05,
    "A800-80GB": 2.10,
    "H800-80GB": 3.20,
    "H20-96GB": 2.50,
    "H20-141GB": 3.00,
    "L20-48GB": 1.60,
}


# One rate per meter, in dollars per unit of that meter. Cloud list-price
# references; every one is user-configurable, and the assumption is printed on
# each finding that uses it.
DEFAULT_METER_RATES: dict[str, float] = {
    "gb_months": 0.08,          # block SSD, $/GB-month
    "gb_transferred": 0.02,     # cross-AZ, $/GB
    "kwh": 0.12,                # industrial electricity, $/kWh
    "committed_dollars": 1.0,   # already dollars
    "replica_hours": 2.21,      # one A100-class replica-hour
    "cpu_hours": 0.04,          # $/vCPU-hour
    "queue_seconds": 0.0,       # priced through the GPU-hours it implies
}

# Storage tiers differ by an order of magnitude, so a claim that names its
# tier is priced against that tier instead of the generic block rate.
DEFAULT_STORAGE_TIER_RATES: dict[str, float] = {
    "ssd": 0.08,
    "nvme": 0.12,
    "block": 0.08,
    "standard": 0.045,
    "object": 0.023,
    "archive": 0.004,
    "glacier": 0.004,
}

# Network egress is priced by where the bytes went, not just how many.
DEFAULT_NETWORK_KIND_RATES: dict[str, float] = {
    "cross_az": 0.02,
    "cross_region": 0.02,
    "egress": 0.09,
    "internet": 0.09,
    "intra_az": 0.0,
    "storage_read": 0.01,
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
