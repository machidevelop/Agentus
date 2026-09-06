"""Normalized domain model. Infrastructure-neutral: describes what happened, not what to do."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from natilah.models.enums import (
    ActionStatus,
    AgentObjective,
    CandidateOutcome,
    ConfidenceLevel,
    DecisionType,
    JobState,
    Meter,
    OpportunityType,
    Resolution,
)
from natilah.models.resources import (
    Checkpoint,
    ClockCap,
    Commitment,
    DatasetArtifact,
    FacilityProfile,
    ImagePull,
    InferenceEndpoint,
    InferenceMetricSample,
    NetworkFlow,
    PowerTariff,
    StorageSnapshot,
    StorageVolume,
    TrainingRun,
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


def gpu_type_matches(requested: str | None, actual: str | None) -> bool:
    """Compare a requested GPU type with a physical one, alias-aware.

    Traces record what the user asked for ("A100"), while the catalog records
    what the node has ("A100-80GB"). Comparing those two strings directly makes
    every feasibility check fail, so both sides are resolved first.
    """
    if not requested:
        return True
    if not actual:
        return False
    if requested == actual:
        return True
    return resolve_gpu_type(requested).name == resolve_gpu_type(actual).name


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
    contiguous_blocks: list[Block] = Field(default_factory=list)
    contiguity_index: float = 0.0
    largest_contiguous_block: int = 0

    # Block objects are only needed by callers that inspect free-block shape;
    # the size and contiguity numbers above are computed without them.
    _block_builder: Any = PrivateAttr(default=None)

    def blocks(self) -> list[Block]:
        """Free contiguous blocks, largest first, built on first use."""
        if not self.contiguous_blocks and self._block_builder is not None:
            self.contiguous_blocks = self._block_builder()
        return self.contiguous_blocks


class NodeState(BaseModel):
    node: Node
    gpus: list[GPU]
    allocated_gpu_ids: list[str]
    idle_gpu_ids: list[str]
    running_job_ids: list[str]


class ClusterStateSnapshot(BaseModel):
    timestamp: datetime
    nodes: list[NodeState] = Field(default_factory=list)
    running_jobs: list[Job] = Field(default_factory=list)
    pending_jobs: list[Job] = Field(default_factory=list)
    gpu_allocations: dict[str, str | None] = Field(default_factory=dict)
    idle_gpus: list[str] = Field(default_factory=list)
    available_capacity: CapacityMap

    # Per-node states cost a model per node per snapshot and almost nothing
    # reads them, so the reconstructor attaches a builder instead of paying
    # that cost on every reconstruction. Use node_states(), not .nodes.
    _node_builder: Any = PrivateAttr(default=None)

    def node_states(self) -> list[NodeState]:
        """Per-node view of this instant, built on first use."""
        if not self.nodes and self._node_builder is not None:
            self.nodes = self._node_builder(self.gpu_allocations)
        return self.nodes


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
    # Rate per unit for the non-GPU meters, keyed by Meter value.
    meter_rates: dict[str, float] = Field(default_factory=dict)


class ValueEstimate(BaseModel):
    """What a finding is worth, separated by how the value actually arrives.

    `estimated_monthly_value` is a run rate: waste that recurs every month
    until somebody fixes it. `one_time_value` is money recovered exactly once,
    such as a denied medical claim that gets overturned. Mixing the two is how
    savings reports stop being auditable, so the ledger keeps them apart and
    the API reports both.
    """

    gpu_hours_recovered: float
    compute_cost_avoided: float
    equivalent_gpus_recovered: float
    estimated_monthly_value: float
    estimated_annual_value: float
    assumptions: list[str]
    cost_model_used: EconomicConfig
    gpu_type: str | None = None

    # Non-recurring recovery. Zero for meters that accrue every month.
    one_time_value: float = 0.0
    is_recurring: bool = True


class ConfidenceFactor(BaseModel):
    name: str
    weight: float
    score: float
    reason: str


class ConfidenceAssessment(BaseModel):
    """How much to trust a finding, and how that number was arrived at.

    `score` is what ranking uses. When a calibrator has been fitted against
    recorded outcomes, `score` is the calibrated probability and `raw_score`
    keeps the agent's original heuristic, so a reviewer can always see both.
    """

    score: float
    level: ConfidenceLevel
    factors: list[ConfidenceFactor]
    assumptions: list[str]
    constraints_checked: list[str]
    uncertainty_sources: list[str]
    explanation: str
    raw_score: float | None = None
    calibrated: bool = False


class UtilizationPoint(BaseModel):
    timestamp: datetime
    actual_pct: float
    alternative_pct: float | None = None


class GPUInterval(BaseModel):
    """A GPU held over a time window. Unit of the coordination layer's ledger."""

    gpu_id: str
    start: datetime
    end: datetime

    @property
    def gpu_hours(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


class ResourceInterval(BaseModel):
    """A metered resource held over a window.

    One shape covers every time-accruing meter. `magnitude` is how much of the
    resource is held — 1 GPU, 500 GB, 0.4 kW, 3 replicas — and the meter says
    what a unit of time is worth, so quantity is always magnitude x duration.
    """

    meter: Meter
    resource_id: str
    start: datetime
    end: datetime
    magnitude: float = 1.0

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())

    @property
    def quantity(self) -> float:
        return self.magnitude * self.seconds / self.meter.seconds_per_unit


class ResourceQuantity(BaseModel):
    """A metered amount with no time dimension: bytes moved, dollars committed."""

    meter: Meter
    resource_id: str
    amount: float


class ResourceClaim(BaseModel):
    """Exactly what a finding claims to recover, in the meters it recovers it in.

    The coordination layer needs this to deduplicate: two agents may describe
    the same waste from different angles, and it may only be counted once.
    Meters never mix — a storage claim cannot cancel a GPU claim — but a
    finding may claim in several meters at once, and the ledger credits each
    one separately.

    GPU-hours and queue-seconds keep their own fields because they predate the
    generalized meters and the scheduling agents are built on them.
    """

    intervals: list[GPUInterval] = Field(default_factory=list)
    queue_job_ids: list[str] = Field(default_factory=list)
    queue_seconds: float = 0.0
    basis: str = ""

    # Generalized meters (storage, network, power, commitments, inference)
    resource_intervals: list[ResourceInterval] = Field(default_factory=list)
    quantities: list[ResourceQuantity] = Field(default_factory=list)
    primary_meter: Meter = Meter.GPU_HOURS

    @property
    def gpu_hours(self) -> float:
        return sum(i.gpu_hours for i in self.intervals) + self.metered(Meter.GPU_HOURS)

    @property
    def gpu_ids(self) -> list[str]:
        return sorted({i.gpu_id for i in self.intervals})

    def metered(self, meter: Meter) -> float:
        """Total claimed in one generalized meter, ignoring the legacy fields."""
        total = sum(i.quantity for i in self.resource_intervals if i.meter == meter)
        total += sum(q.amount for q in self.quantities if q.meter == meter)
        return total

    def quantity(self, meter: Meter) -> float:
        """Total claimed in a meter, including the legacy GPU and queue fields."""
        if meter is Meter.GPU_HOURS:
            return self.gpu_hours
        if meter is Meter.QUEUE_SECONDS:
            return self.queue_seconds + self.metered(Meter.QUEUE_SECONDS)
        return self.metered(meter)

    def meters(self) -> list[Meter]:
        """Every meter this claim actually charges, in declaration order."""
        seen: list[Meter] = []
        if self.intervals:
            seen.append(Meter.GPU_HOURS)
        if self.queue_seconds > 0:
            seen.append(Meter.QUEUE_SECONDS)
        for item in [*self.resource_intervals, *self.quantities]:
            if item.meter not in seen:
                seen.append(item.meter)
        return seen

    @property
    def primary_quantity(self) -> float:
        return self.quantity(self.primary_meter)


class CandidateRecord(BaseModel):
    """Audit record for every alternative Y the agent considered."""

    alternative_id: str
    description: str
    generation_method: str
    outcome: CandidateOutcome
    constraints_checked: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None
    gpu_hours_saved: float = 0.0
    queue_time_reduction_seconds: float = 0.0
    monthly_value: float = 0.0
    confidence_score: float = 0.0
    tools_invoked: list[str] = Field(default_factory=list)


class Attribution(BaseModel):
    """Coordination-layer verdict: value after dedup, conflicts, and ranking."""

    rank: int = 0
    resolution: Resolution = Resolution.UNIQUE
    claimed_gpu_hours: float = 0.0
    attributed_gpu_hours: float = 0.0
    overlap_gpu_hours: float = 0.0
    claimed_queue_seconds: float = 0.0
    attributed_queue_seconds: float = 0.0
    attributed_monthly_value: float = 0.0
    attributed_annual_value: float = 0.0
    expected_monthly_value: float = 0.0
    overlaps_with: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    notes: list[str] = Field(default_factory=list)
    # Claimed vs credited per meter — what a customer's finance team audits.
    claimed_by_meter: dict[str, float] = Field(default_factory=dict)
    attributed_by_meter: dict[str, float] = Field(default_factory=dict)


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

    # Specialized-agent layer
    agent_name: str = ""
    objective: AgentObjective | None = None
    recommended_action: str = ""
    claim: ResourceClaim = Field(default_factory=ResourceClaim)
    candidates_considered: list[CandidateRecord] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    selection_score: float = 0.0

    # Coordination layer (filled by AgentCoordinator, not by the agent)
    attribution: Attribution = Field(default_factory=Attribution)
    status: ActionStatus = ActionStatus.AWAITING_APPROVAL


class AgentRunSummary(BaseModel):
    """Per-agent accounting for one coordinated analysis run."""

    agent_name: str
    objective: AgentObjective
    observations: int = 0
    candidates_generated: int = 0
    candidates_rejected_infeasible: int = 0
    candidates_rejected_no_gain: int = 0
    findings: int = 0
    claimed_gpu_hours: float = 0.0
    claimed_monthly_value: float = 0.0
    llm_used: bool = False
    error: str | None = None


class CoordinationReport(BaseModel):
    """Output of the coordination layer: ranked, deduplicated, conflict-free."""

    generated_at: datetime
    agents: list[AgentRunSummary] = Field(default_factory=list)
    total_findings: int = 0
    ranked_findings: int = 0
    suppressed_findings: int = 0
    conflicts_resolved: int = 0
    # Expected monthly value the global selection kept that the older greedy
    # rule would have discarded. Zero means greedy was already optimal.
    selection_gain_monthly_value: float = 0.0
    duplicate_gpu_hours_removed: float = 0.0
    duplicate_queue_seconds_removed: float = 0.0
    claimed_gpu_hours: float = 0.0
    attributed_gpu_hours: float = 0.0
    claimed_monthly_value: float = 0.0
    attributed_monthly_value: float = 0.0
    attributed_annual_value: float = 0.0
    top_actions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    # Per-meter accounting. A fleet headline is never the sum of its agents,
    # and it is never the sum of unlike units either.
    claimed_by_meter: dict[str, float] = Field(default_factory=dict)
    attributed_by_meter: dict[str, float] = Field(default_factory=dict)
    duplicates_removed_by_meter: dict[str, float] = Field(default_factory=dict)
    findings_by_meter: dict[str, int] = Field(default_factory=dict)


class ClusterDataset(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    gpus: list[GPU] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    allocations: list[Allocation] = Field(default_factory=list)
    samples: list[GPUUtilizationSample] = Field(default_factory=list)
    decisions: list[SchedulerDecision] = Field(default_factory=list)
    queue_snapshots: list[QueueSnapshot] = Field(default_factory=list)

    # Phase 3 domains. Each is optional: a cluster with no storage connector
    # simply produces no storage findings rather than failing the run.
    volumes: list[StorageVolume] = Field(default_factory=list)
    snapshots: list[StorageSnapshot] = Field(default_factory=list)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    artifacts: list[DatasetArtifact] = Field(default_factory=list)
    flows: list[NetworkFlow] = Field(default_factory=list)
    image_pulls: list[ImagePull] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    tariffs: list[PowerTariff] = Field(default_factory=list)
    facilities: list[FacilityProfile] = Field(default_factory=list)
    clock_caps: list[ClockCap] = Field(default_factory=list)
    training_runs: list[TrainingRun] = Field(default_factory=list)
    endpoints: list[InferenceEndpoint] = Field(default_factory=list)
    endpoint_samples: list[InferenceMetricSample] = Field(default_factory=list)

    # Lookups are rebuilt on first use and cached: analysis walks these
    # indexes thousands of times per run, once per candidate alternative.
    _job_index: dict[str, Job] | None = PrivateAttr(default=None)
    _gpu_index: dict[str, GPU] | None = PrivateAttr(default=None)
    _node_index: dict[str, Node] | None = PrivateAttr(default=None)
    _allocation_index: dict[str, Allocation] | None = PrivateAttr(default=None)
    _samples_index: dict[str, list[GPUUtilizationSample]] | None = PrivateAttr(default=None)
    _endpoint_samples_index: dict[str, list[InferenceMetricSample]] | None = PrivateAttr(default=None)
    _snapshots_index: dict[str, list[StorageSnapshot]] | None = PrivateAttr(default=None)

    def invalidate_indexes(self) -> None:
        """Call after mutating any of the lists above."""
        self._job_index = None
        self._gpu_index = None
        self._node_index = None
        self._allocation_index = None
        self._samples_index = None
        self._endpoint_samples_index = None
        self._snapshots_index = None

    def has_domain_data(self) -> bool:
        """True when any Phase 3 connector contributed records."""
        return any(
            [
                self.volumes,
                self.snapshots,
                self.checkpoints,
                self.artifacts,
                self.flows,
                self.image_pulls,
                self.commitments,
                self.clock_caps,
                self.training_runs,
                self.endpoints,
            ]
        )

    def samples_for_endpoint(self, endpoint_id: str) -> list[InferenceMetricSample]:
        if self._endpoint_samples_index is None:
            index: dict[str, list[InferenceMetricSample]] = {}
            for sample in self.endpoint_samples:
                index.setdefault(sample.endpoint_id, []).append(sample)
            for values in index.values():
                values.sort(key=lambda s: s.timestamp)
            self._endpoint_samples_index = index
        return self._endpoint_samples_index.get(endpoint_id, [])

    def snapshots_for_volume(self, volume_id: str) -> list[StorageSnapshot]:
        if self._snapshots_index is None:
            index: dict[str, list[StorageSnapshot]] = {}
            for snap in self.snapshots:
                index.setdefault(snap.volume_id, []).append(snap)
            for values in index.values():
                values.sort(key=lambda s: s.created_at)
            self._snapshots_index = index
        return self._snapshots_index.get(volume_id, [])

    def window(self) -> tuple[datetime, datetime] | None:
        """Observation window spanning jobs and every domain record present."""
        starts: list[datetime] = []
        ends: list[datetime] = []
        for job in self.jobs:
            starts.append(job.submit_time)
            ends.append(job.end_time or job.start_time or job.submit_time)
        for flow in self.flows:
            starts.append(flow.start)
            ends.append(flow.end)
        for run in self.training_runs:
            starts.append(run.start)
            ends.append(run.end or run.start)
        for sample in self.endpoint_samples:
            starts.append(sample.timestamp)
            ends.append(sample.timestamp)
        for pull in self.image_pulls:
            starts.append(pull.timestamp)
            ends.append(pull.timestamp)
        if not starts or not ends:
            return None
        return min(starts), max(ends)

    def job_by_id(self) -> dict[str, Job]:
        if self._job_index is None:
            self._job_index = {j.job_id: j for j in self.jobs}
        return self._job_index

    def gpu_by_id(self) -> dict[str, GPU]:
        if self._gpu_index is None:
            self._gpu_index = {g.gpu_id: g for g in self.gpus}
        return self._gpu_index

    def node_by_id(self) -> dict[str, Node]:
        if self._node_index is None:
            self._node_index = {n.node_id: n for n in self.nodes}
        return self._node_index

    def allocation_by_job(self) -> dict[str, Allocation]:
        if self._allocation_index is None:
            self._allocation_index = {a.job_id: a for a in self.allocations}
        return self._allocation_index

    def samples_by_job(self) -> dict[str, list[GPUUtilizationSample]]:
        """Telemetry grouped by job. Scanning `samples` per job is O(jobs x samples)."""
        if self._samples_index is None:
            index: dict[str, list[GPUUtilizationSample]] = {}
            for sample in self.samples:
                if sample.job_id:
                    index.setdefault(sample.job_id, []).append(sample)
            self._samples_index = index
        return self._samples_index

    def samples_for_job(self, job_id: str) -> list[GPUUtilizationSample]:
        return self.samples_by_job().get(job_id, [])


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
