"""Records for the non-scheduling waste domains.

Every Phase 3 domain needs its own data, and none of it fits the job/allocation
model: an orphaned volume has no scheduler decision behind it, a commitment is
an accounting object, a power tariff is a property of the building. These are
the normalized shapes each domain connector produces, kept deliberately small
and infrastructure-neutral.

One rule holds across all of them: a record describes what was observed, never
what to do about it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# --------------------------------------------------------------------- storage


class StorageVolume(BaseModel):
    """A persistent volume, whether or not anything is still using it."""

    volume_id: str
    name: str = ""
    size_gb: float
    tier: str = "ssd"
    created_at: datetime
    last_accessed_at: datetime | None = None
    attached_to_job_id: str | None = None
    attached: bool = False
    node_id: str | None = None
    owner: str = ""
    labels: dict[str, str] = Field(default_factory=dict)


class StorageSnapshot(BaseModel):
    """A point-in-time copy. Sprawl is many of these against one volume."""

    snapshot_id: str
    volume_id: str
    size_gb: float
    created_at: datetime
    tier: str = "object"
    owner: str = ""


class Checkpoint(BaseModel):
    """A training checkpoint. Cold ones are the ones nothing ever reads back."""

    checkpoint_id: str
    job_id: str | None = None
    run_id: str | None = None
    path: str = ""
    size_gb: float
    created_at: datetime
    last_read_at: datetime | None = None
    tier: str = "object"
    is_final: bool = False


class DatasetArtifact(BaseModel):
    """A materialized dataset. Two with one checksum are one dataset paid twice."""

    artifact_id: str
    path: str = ""
    size_gb: float
    checksum: str = ""
    created_at: datetime
    last_read_at: datetime | None = None
    tier: str = "object"
    owner: str = ""


# --------------------------------------------------------------------- network


class NetworkFlow(BaseModel):
    """Bytes moved between two places, with the zones that make it billable."""

    flow_id: str
    src_zone: str = ""
    dst_zone: str = ""
    src_node_id: str | None = None
    dst_node_id: str | None = None
    job_id: str | None = None
    gb_transferred: float
    start: datetime
    end: datetime
    kind: str = "cross_az"  # cross_az | egress | intra_az | storage_read

    @property
    def is_billable(self) -> bool:
        return self.kind in {"cross_az", "egress"} or self.src_zone != self.dst_zone


class ImagePull(BaseModel):
    """A container image pulled onto a node. Cache misses are the waste."""

    pull_id: str
    node_id: str
    image: str
    gb: float
    timestamp: datetime
    job_id: str | None = None
    cache_hit: bool = False
    registry_zone: str = ""
    duration_seconds: float = 0.0


# ----------------------------------------------------------------- commitments


class Commitment(BaseModel):
    """Capacity bought ahead of time: reserved instances, plans, or spot policy."""

    commitment_id: str
    kind: str = "reserved"  # reserved | savings_plan | spot
    gpu_type: str = ""
    quantity: int = 0
    hourly_rate: float = 0.0
    on_demand_rate: float = 0.0
    start: datetime
    end: datetime
    auto_renew: bool = False
    scope: str = ""
    labels: dict[str, str] = Field(default_factory=dict)

    @property
    def committed_hours(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0) * max(self.quantity, 0)

    @property
    def total_commitment_dollars(self) -> float:
        return self.committed_hours * self.hourly_rate


# ----------------------------------------------------------------------- power


class PowerTariff(BaseModel):
    """What a kWh costs in a zone during a window of the day."""

    zone: str = ""
    start_hour: int = 0
    end_hour: int = 24
    price_per_kwh: float = 0.12
    is_peak: bool = False


class FacilityProfile(BaseModel):
    """Power overhead of the building holding a set of nodes."""

    zone: str = ""
    pue: float = 1.4
    node_ids: list[str] = Field(default_factory=list)
    carbon_kg_per_kwh: float = 0.0


class ClockCap(BaseModel):
    """A GPU running below its rated clock: paid-for silicon that cannot work."""

    gpu_id: str
    capped_mhz: float
    max_mhz: float
    start: datetime
    end: datetime
    reason: str = ""

    @property
    def throttle_fraction(self) -> float:
        if self.max_mhz <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - (self.capped_mhz / self.max_mhz)))


# ------------------------------------------------------------------- training


class TrainingRun(BaseModel):
    """One training run's lifecycle, including how much of it was thrown away."""

    run_id: str
    job_id: str | None = None
    sweep_id: str | None = None
    start: datetime
    end: datetime | None = None
    steps_completed: int = 0
    restart_count: int = 0
    checkpoint_seconds: float = 0.0
    dataloader_stall_seconds: float = 0.0
    gpu_count: int = 1
    gpu_type: str = ""
    best_metric: float | None = None
    final_metric: float | None = None
    metric_name: str = ""
    higher_is_better: bool = True
    exit_reason: str = ""  # completed | failed | preempted | diverged | killed
    resumed_from_checkpoint: bool = False

    @property
    def wall_hours(self) -> float:
        if self.end is None:
            return 0.0
        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


# ------------------------------------------------------------------- inference


class InferenceEndpoint(BaseModel):
    """A served model holding GPUs whether or not requests arrive."""

    endpoint_id: str
    name: str = ""
    model: str = ""
    gpu_type: str = ""
    replicas: int = 1
    gpus_per_replica: int = 1
    gpu_ids: list[str] = Field(default_factory=list)
    node_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    max_batch_size: int = 1
    autoscaling_enabled: bool = False
    min_replicas: int = 1
    labels: dict[str, str] = Field(default_factory=dict)


class InferenceMetricSample(BaseModel):
    """Serving telemetry: what the endpoint was actually asked to do."""

    endpoint_id: str
    timestamp: datetime
    requests_per_second: float = 0.0
    batch_size: float = 0.0
    p95_latency_ms: float = 0.0
    gpu_utilization_pct: float = 0.0
    replica_count: int = 1
