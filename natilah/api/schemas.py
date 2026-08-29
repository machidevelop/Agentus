"""API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IngestionGenerateRequest(BaseModel):
    num_nodes: int = 64
    gpus_per_node: int = 8
    num_jobs: int = 500
    time_window_hours: int = 24
    seed: int = 42


class IngestionResponse(BaseModel):
    nodes: int
    gpus: int
    jobs: int
    allocations: int
    samples: int
    decisions: int
    source: str


class AnalysisRunResponse(BaseModel):
    run_id: str
    status: str
    opportunities_found: int = 0
    error: str | None = None


class AnalysisStatusResponse(BaseModel):
    run_id: str | None = None
    status: str = "idle"
    opportunities_found: int = 0
    error: str | None = None


class CostConfigSchema(BaseModel):
    cost_per_gpu_hour: dict[str, float]
    gpu_amortization_years: float = 3.0
    facility_cost_multiplier: float = 1.4
    working_hours_per_month: float = 720.0


class DashboardSummary(BaseModel):
    gpus_analyzed: int
    decisions_analyzed: int
    opportunities_found: int
    gpu_hours_recovered: float
    equivalent_gpus: float
    monthly_value: float
    annual_value: float
    production_changes: int = 0
    analysis_status: str = "idle"
    safety_mode: str = "read_only"


class OpportunityListItem(BaseModel):
    opportunity_id: str
    opportunity_type: str
    title: str
    description: str
    monthly_value: float
    annual_value: float
    confidence_level: str
    confidence_score: float
    severity: float
    affected_job_ids: list[str]


class OpportunityDetail(BaseModel):
    opportunity_id: str
    opportunity_type: str
    title: str
    what_happened: str
    alternative: dict[str, Any]
    impact: dict[str, Any]
    value: dict[str, Any]
    confidence: dict[str, Any]
    utilization_series: list[dict[str, Any]] = Field(default_factory=list)
    detected_at: datetime
    affected_job_ids: list[str]
    affected_gpu_ids: list[str]
    decision: dict[str, Any]
