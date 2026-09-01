"""Shared enumerations for the Natilah domain model."""

from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DecisionType(str, Enum):
    ALLOCATE = "allocate"
    PLACE = "place"
    QUEUE = "queue"
    CONSOLIDATE = "consolidate"


class OpportunityType(str, Enum):
    OVER_ALLOCATION = "over_allocation"
    POOR_PLACEMENT = "poor_placement"
    FRAGMENTATION = "fragmentation"
    IDLE_ALLOCATION = "idle_allocation"
    QUEUE_INEFFICIENCY = "queue_inefficiency"

    # Storage
    ORPHANED_VOLUME = "orphaned_volume"
    COLD_CHECKPOINT = "cold_checkpoint"
    SNAPSHOT_SPRAWL = "snapshot_sprawl"
    DUPLICATE_DATASET = "duplicate_dataset"

    # Network
    CROSS_AZ_TRAFFIC = "cross_az_traffic"
    DATA_LOCALITY = "data_locality"
    IMAGE_PULL_CHURN = "image_pull_churn"

    # Commitments
    RESERVATION_UNDERUSE = "reservation_underuse"
    SPOT_ELIGIBLE = "spot_eligible"
    COMMITMENT_EXPIRY = "commitment_expiry"

    # Power / thermal
    CAPPED_CLOCKS = "capped_clocks"
    PUE_PLACEMENT = "pue_placement"
    OFF_PEAK_SHIFT = "off_peak_shift"

    # Training efficiency
    DATALOADER_STALL = "dataloader_stall"
    RESTART_WASTE = "restart_waste"
    NONCONVERGING_SWEEP = "nonconverging_sweep"
    CHECKPOINT_OVERHEAD = "checkpoint_overhead"

    # Inference
    IDLE_ENDPOINT = "idle_endpoint"
    OVER_PROVISIONED_REPLICAS = "over_provisioned_replicas"
    BATCH_HEADROOM = "batch_headroom"


class Meter(str, Enum):
    """A unit of waste the ledger can deduplicate and price.

    Each new waste domain ships its own meter. Two meters never share a
    resource namespace, so a storage finding can never cancel a GPU finding.
    """

    GPU_HOURS = "gpu_hours"
    QUEUE_SECONDS = "queue_seconds"
    GB_MONTHS = "gb_months"
    GB_TRANSFERRED = "gb_transferred"
    KWH = "kwh"
    COMMITTED_DOLLARS = "committed_dollars"
    REPLICA_HOURS = "replica_hours"
    CPU_HOURS = "cpu_hours"

    @property
    def is_interval(self) -> bool:
        """True when the meter accrues over time and dedups by interval union."""
        return self in _INTERVAL_METERS

    @property
    def seconds_per_unit(self) -> float:
        """Seconds that make up one unit of the meter (hour, month, ...)."""
        return _METER_SECONDS.get(self, 3600.0)

    @property
    def unit_label(self) -> str:
        return _METER_LABELS.get(self, self.value)


_INTERVAL_METERS = {
    Meter.GPU_HOURS,
    Meter.GB_MONTHS,
    Meter.KWH,
    Meter.REPLICA_HOURS,
    Meter.CPU_HOURS,
}

_METER_SECONDS = {
    Meter.GPU_HOURS: 3600.0,
    Meter.GB_MONTHS: 2_592_000.0,  # 30-day month
    Meter.KWH: 3600.0,
    Meter.REPLICA_HOURS: 3600.0,
    Meter.CPU_HOURS: 3600.0,
}

_METER_LABELS = {
    Meter.GPU_HOURS: "GPU-h",
    Meter.QUEUE_SECONDS: "queue-s",
    Meter.GB_MONTHS: "GB-month",
    Meter.GB_TRANSFERRED: "GB",
    Meter.KWH: "kWh",
    Meter.COMMITTED_DOLLARS: "$ committed",
    Meter.REPLICA_HOURS: "replica-h",
    Meter.CPU_HOURS: "CPU-h",
}


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SafetyMode(str, Enum):
    READ_ONLY = "read_only"
    PROPOSE = "propose"
    EXECUTE_WITH_APPROVAL = "execute"


class AgentObjective(str, Enum):
    """One clear optimization objective per specialized agent."""

    IDLE_ALLOCATION = "idle_allocation"
    OVER_ALLOCATION = "over_allocation"
    QUEUE_EFFICIENCY = "queue_efficiency"
    FRAGMENTATION_PLACEMENT = "fragmentation_placement"

    # Phase 3: one objective per meter, not per view of GPU-hours.
    STORAGE_EFFICIENCY = "storage_efficiency"
    NETWORK_EFFICIENCY = "network_efficiency"
    COMMITMENT_COVERAGE = "commitment_coverage"
    POWER_EFFICIENCY = "power_efficiency"
    TRAINING_EFFICIENCY = "training_efficiency"
    INFERENCE_EFFICIENCY = "inference_efficiency"


class CandidateOutcome(str, Enum):
    """Result of deterministic validation + simulation for a candidate Y."""

    SELECTED = "selected"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    NO_IMPROVEMENT = "no_improvement"


class Resolution(str, Enum):
    """What the coordination layer did with a finding."""

    UNIQUE = "unique"
    DEDUPLICATED = "deduplicated"
    FULLY_DEDUPLICATED = "fully_deduplicated"
    SUPERSEDED = "superseded"


class ActionStatus(str, Enum):
    """Human approval state. Natilah never executes; engineers do."""

    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    DISMISSED = "dismissed"
