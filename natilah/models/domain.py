"""Normalized domain model. Infrastructure-neutral: describes what happened, not what to do."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from natilah.models.enums import (
    ConfidenceLevel,
    DecisionType,
    JobState,
    OpportunityType,
)


class GPUType(BaseModel):
    name: str
    memory_gb: float
    tdp_watts: float
    compute_capability: str
    fp16_tflops: float


GPU_TYPE_CATALOG: dict[str, GPUType] = {
    "P100-16GB": GPUType(
        name="P100-16GB",
        memory_gb=16.0,
        tdp_watts=250.0,
        compute_capability="6.0",
        fp16_tflops=18.7,
    ),
    "V100-16GB": GPUType(
        name="V100-16GB",
        memory_gb=16.0,
        tdp_watts=300.0,
        compute_capability="7.0",
        fp16_tflops=125.0,
    ),
    "V100-32GB": GPUType(
        name="V100-32GB",
        memory_gb=32.0,
        tdp_watts=300.0,
        compute_capability="7.0",
        fp16_tflops=125.0,
    ),
    "T4-16GB": GPUType(
        name="T4-16GB",
        memory_gb=16.0,
        tdp_watts=70.0,
        compute_capability="7.5",
        fp16_tflops=65.0,
    ),
    "A10-24GB": GPUType(
        name="A10-24GB",
        memory_gb=24.0,
        tdp_watts=150.0,
        compute_capability="8.6",
        fp16_tflops=125.0,
    ),
    "A100-40GB": GPUType(
        name="A100-40GB",
        memory_gb=40.0,
        tdp_watts=400.0,
        compute_capability="8.0",
        fp16_tflops=312.0,
    ),
    "A100-80GB": GPUType(
        name="A100-80GB",
        memory_gb=80.0,
        tdp_watts=400.0,
        compute_capability="8.0",
        fp16_tflops=312.0,
    ),
    "H100-80GB": GPUType(
        name="H100-80GB",
        memory_gb=80.0,
        tdp_watts=700.0,
        compute_capability="9.0",
        fp16_tflops=989.0,
    ),
    "H200-141GB": GPUType(
        name="H200-141GB",
        memory_gb=141.0,
        tdp_watts=700.0,
        compute_capability="9.0",
        fp16_tflops=989.0,
    ),
    "B200-192GB": GPUType(
        name="B200-192GB",
        memory_gb=192.0,
        tdp_watts=1000.0,
        compute_capability="10.0",
        fp16_tflops=2250.0,
    ),
    "A30-24GB": GPUType(
        name="A30-24GB",
        memory_gb=24.0,
        tdp_watts=165.0,
        compute_capability="8.0",
        fp16_tflops=165.0,
    ),
    "A800-80GB": GPUType(
        name="A800-80GB",
        memory_gb=80.0,
        tdp_watts=400.0,
        compute_capability="8.0",
        fp16_tflops=312.0,
    ),
    "H800-80GB": GPUType(
        name="H800-80GB",
        memory_gb=80.0,
        tdp_watts=700.0,
        compute_capability="9.0",
        fp16_tflops=989.0,
    ),
    "H20-96GB": GPUType(
        name="H20-96GB",
        memory_gb=96.0,
        tdp_watts=500.0,
        compute_capability="9.0",
        fp16_tflops=296.0,
    ),
    "H20-141GB": GPUType(
        name="H20-141GB",
        memory_gb=141.0,
        tdp_watts=500.0,
        compute_capability="9.0",
        fp16_tflops=296.0,
    ),
    "L20-48GB": GPUType(
        name="L20-48GB",
        memory_gb=48.0,
        tdp_watts=275.0,
        compute_capability="8.9",
        fp16_tflops=239.0,
    ),
}

ALIBABA_GPU_ALIASES: dict[str, str] = {
    "T4": "T4-16GB",
    "V100": "V100-32GB",
    "V100S": "V100-32GB",
    "P100": "P100-16GB",
    "A10": "A10-24GB",
    "A100": "A100-80GB",
    "A100-40G": "A100-40GB",
    "A100-80G": "A100-80GB",
    "H100": "H100-80GB",
    "H200": "H200-141GB",
    "MISC": "T4-16GB",
    "A30": "A30-24GB",
    "A800": "A800-80GB",
    "H800": "H800-80GB",
    "H20": "H20-96GB",
    "H20-141GB": "H20-141GB",
    "L20": "L20-48GB",
    "XPU-A": "T4-16GB",
    "XPU-B": "A10-24GB",
    "XPU-C": "A100-40GB",
    "XPU-D": "A100-80GB",
    "XPU-E": "H100-80GB",
}


def resolve_gpu_type(name: str) -> GPUType:
    if name in GPU_TYPE_CATALOG:
        return GPU_TYPE_CATALOG[name]
    canonical = ALIBABA_GPU_ALIASES.get(name.upper(), ALIBABA_GPU_ALIASES.get(name))
    if canonical and canonical in GPU_TYPE_CATALOG:
        return GPU_TYPE_CATALOG[canonical]
    return GPUType(
        name=name,
        memory_gb=16.0,
        tdp_watts=250.0,
        compute_capability="7.0",
        fp16_tflops=65.0,
    )


class GPU(BaseModel):
    gpu_id: str
    gpu_type: GPUType
    node_id: str
    gpu_index: int


class Node(BaseModel):
    node_id: str
    hostname: str
    gpu_count: int
    gpu_type: GPUType
    total_memory_gb: float
    cpu_cores: int
    labels: dict[str, str] = Field(default_factory=dict)


class Job(BaseModel):
    job_id: str
    name: str
    user: str
    submit_time: datetime
    start_time: datetime | None = None
    end_time: datetime | None = None
    state: JobState
    requested_gpus: int
    requested_gpu_type: str | None = None
    priority: int = 0
    constraints: dict[str, str] = Field(default_factory=dict)


class Allocation(BaseModel):
    allocation_id: str
    job_id: str
    gpu_ids: list[str]
    node_ids: list[str]
    start_time: datetime
    end_time: datetime | None = None
    decision_reason: str | None = None


class GPUUtilizationSample(BaseModel):
    gpu_id: str
    timestamp: datetime
    gpu_utilization_pct: float
    memory_utilization_pct: float
    memory_used_gb: float
    power_watts: float | None = None
    job_id: str | None = None


class QueueSnapshot(BaseModel):
    timestamp: datetime
    pending_jobs: list[str]
    running_jobs: list[str]
    total_gpus: int
    allocated_gpus: int
    idle_gpus: int


class SchedulerDecision(BaseModel):
    decision_id: str
    timestamp: datetime
    decision_type: DecisionType
    job_id: str
    chosen_action: dict[str, Any] = Field(default_factory=dict)
    cluster_state_id: str | None = None


class Block(BaseModel):
    node_id: str
    gpu_ids: list[str]
    size: int
    clique_type: str


class NodeCapacity(BaseModel):
    node_id: str
    total_gpus: int
    allocated_gpus: int
    idle_gpus: int
    gpu_type: str
    idle_gpu_ids: list[str]


class CapacityMap(BaseModel):
    total_gpus: int
    allocated_gpus: int
    idle_gpus: int
    by_node: dict[str, NodeCapacity]
    by_gpu_type: dict[str, int]
    contiguous_blocks: list[Block]
    contiguity_index: float = 0.0
    largest_contiguous_block: int = 0


class NodeState(BaseModel):
    node: Node
    gpus: list[GPU]
    allocated_gpu_ids: list[str]
    idle_gpu_ids: list[str]
    running_job_ids: list[str]


class ClusterStateSnapshot(BaseModel):
    timestamp: datetime
    nodes: list[NodeState]
    running_jobs: list[Job]
    pending_jobs: list[Job]
    gpu_allocations: dict[str, str | None]
    idle_gpus: list[str]
    available_capacity: CapacityMap


class Observation(BaseModel):
    """A signal about an observed decision. Not a recommended action."""

    observation_id: str
    signal_type: OpportunityType
    decision: SchedulerDecision
    timestamp: datetime
    severity: float
    description: str
    affected_job_ids: list[str]
    affected_gpu_ids: list[str]
    evidence: dict[str, Any] = Field(default_factory=dict)


class Alternative(BaseModel):
    """A candidate decision Y proposed by an agent. Not executed."""

    alternative_id: str
    description: str
    proposed_action: dict[str, Any]
    constraints_satisfied: list[str] = Field(default_factory=list)
    generation_method: str
    agent_name: str
    agent_rationale: str
    tools_invoked: list[str] = Field(default_factory=list)


class DecisionMetrics(BaseModel):
    gpu_hours: float
    avg_gpu_utilization: float
    avg_memory_utilization: float
    idle_gpu_hours: float
    fragmentation_score: float
    queue_time_seconds: float
    jobs_completable: int
    throughput_jobs_per_hour: float


class MetricsDelta(BaseModel):
    gpu_hours_saved: float
    utilization_improvement: float
    idle_hours_recovered: float
    fragmentation_reduction: float
    queue_time_reduction: float
    additional_jobs_serviceable: int


class ComparisonResult(BaseModel):
    actual: DecisionMetrics
    alternative: DecisionMetrics
    delta: MetricsDelta


class EconomicConfig(BaseModel):
    cost_per_gpu_hour: dict[str, float]
    gpu_acquisition_cost: dict[str, float] = Field(default_factory=dict)
    gpu_amortization_years: float = 3.0
    facility_cost_multiplier: float = 1.4
    working_hours_per_month: float = 720.0


class ValueEstimate(BaseModel):
    gpu_hours_recovered: float
    compute_cost_avoided: float
    equivalent_gpus_recovered: float
    estimated_monthly_value: float
    estimated_annual_value: float
    assumptions: list[str]
    cost_model_used: EconomicConfig
    gpu_type: str | None = None


class ConfidenceFactor(BaseModel):
    name: str
    weight: float
    score: float
    reason: str


class ConfidenceAssessment(BaseModel):
    score: float
    level: ConfidenceLevel
    factors: list[ConfidenceFactor]
    assumptions: list[str]
    constraints_checked: list[str]
    uncertainty_sources: list[str]
    explanation: str


class UtilizationPoint(BaseModel):
    timestamp: datetime
    actual_pct: float
    alternative_pct: float | None = None


class Finding(BaseModel):
    """Persisted counterfactual: observed X, feasible Y, technical delta, economic value."""

    opportunity_id: str
    opportunity_type: OpportunityType
    decision: SchedulerDecision
    severity: float
    title: str
    description: str
    detected_at: datetime
    affected_job_ids: list[str]
    affected_gpu_ids: list[str]
    alternative: Alternative
    comparison: ComparisonResult
    value: ValueEstimate
    confidence: ConfidenceAssessment
    utilization_series: list[UtilizationPoint] = Field(default_factory=list)


class ClusterDataset(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    gpus: list[GPU] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    allocations: list[Allocation] = Field(default_factory=list)
    samples: list[GPUUtilizationSample] = Field(default_factory=list)
    decisions: list[SchedulerDecision] = Field(default_factory=list)
    queue_snapshots: list[QueueSnapshot] = Field(default_factory=list)

    def job_by_id(self) -> dict[str, Job]:
        return {j.job_id: j for j in self.jobs}

    def gpu_by_id(self) -> dict[str, GPU]:
        return {g.gpu_id: g for g in self.gpus}

    def node_by_id(self) -> dict[str, Node]:
        return {n.node_id: n for n in self.nodes}

    def allocation_by_job(self) -> dict[str, Allocation]:
        return {a.job_id: a for a in self.allocations}


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class IngestionResult(BaseModel):
    nodes: int
    gpus: int
    jobs: int
    allocations: int
    samples: int
    decisions: int
    source: str


class ValidationIssue(BaseModel):
    field: str
    message: str
