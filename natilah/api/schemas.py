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


class AgentSummarySchema(BaseModel):
    agent_name: str
    objective: str
    observations: int = 0
    candidates_generated: int = 0
    candidates_rejected_infeasible: int = 0
    candidates_rejected_no_gain: int = 0
    findings: int = 0
    claimed_gpu_hours: float = 0.0
    claimed_monthly_value: float = 0.0
    llm_used: bool = False
    error: str | None = None


class CoordinationSummary(BaseModel):
    total_findings: int = 0
    ranked_findings: int = 0
    suppressed_findings: int = 0
    conflicts_resolved: int = 0
    duplicate_gpu_hours_removed: float = 0.0
    claimed_gpu_hours: float = 0.0
    attributed_gpu_hours: float = 0.0
    claimed_monthly_value: float = 0.0
    attributed_monthly_value: float = 0.0
    attributed_annual_value: float = 0.0
    agents: list[AgentSummarySchema] = Field(default_factory=list)
    top_actions: list[str] = Field(default_factory=list)


class AnalysisRunResponse(BaseModel):
    run_id: str
    status: str
    opportunities_found: int = 0
    error: str | None = None
    coordination: CoordinationSummary | None = None


class AgentInfo(BaseModel):
    name: str
    objective: str
    signals: list[str]
    finding_title: str
    llm_enabled: bool


class ActionListItem(BaseModel):
    rank: int
    opportunity_id: str
    agent_name: str
    objective: str | None = None
    opportunity_type: str
    title: str
    recommended_action: str
    what_happened: str
    alternative: str
    gpu_hours_recovered: float
    queue_hours_recovered: float
    monthly_value: float
    annual_value: float
    claimed_monthly_value: float
    confidence_level: str
    confidence_score: float
    resolution: str
    status: str
    affected_job_ids: list[str]
    affected_gpu_ids: list[str]


class ActionDetail(ActionListItem):
    claim: dict[str, Any]
    attribution: dict[str, Any]
    candidates_considered: list[dict[str, Any]]
    constraints_checked: list[str]
    impact: dict[str, Any]
    value: dict[str, Any]
    confidence: dict[str, Any]
    evidence: dict[str, Any]
    utilization_series: list[dict[str, Any]] = Field(default_factory=list)


class ActionStatusUpdate(BaseModel):
    status: str


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
    agent_name: str = ""
    objective: str | None = None
    rank: int = 0
    attributed_monthly_value: float = 0.0
    resolution: str = "unique"
    status: str = "awaiting_approval"


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
    agent_name: str = ""
    objective: str | None = None
    recommended_action: str = ""
    claim: dict[str, Any] = Field(default_factory=dict)
    attribution: dict[str, Any] = Field(default_factory=dict)
    candidates_considered: list[dict[str, Any]] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = "awaiting_approval"
