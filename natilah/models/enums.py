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

    # Consumer: health claim recovery
    CLAIM_DENIED = "claim_denied"
    CLAIM_UNDERPAID = "claim_underpaid"
    DUPLICATE_CHARGE = "duplicate_charge"
    IMPROPER_BUNDLING = "improper_bundling"
    BALANCE_BILL = "balance_bill"
    DEDUCTIBLE_MISAPPLIED = "deductible_misapplied"

    # Consumer: recurring household spend
    UNUSED_SUBSCRIPTION = "unused_subscription"
    DUPLICATE_SERVICE = "duplicate_service"
    SILENT_PRICE_HIKE = "silent_price_hike"
    TRIAL_CONVERSION = "trial_conversion"
    BILLING_TERM_ARBITRAGE = "billing_term_arbitrage"


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

    # Consumer domains. A dollar is the unit, so the rate is 1.0 and the
    # claim quantity is the money itself. These do not accrue over time the
    # way a GPU-hour does: a denied claim is recovered once, not per hour.
    CLAIM_DOLLARS = "claim_dollars"
    REFUND_DOLLARS = "refund_dollars"
    RECURRING_DOLLARS = "recurring_dollars"

    @property
    def is_interval(self) -> bool:
        """True when the meter accrues over time and dedups by interval union."""
        return self in _INTERVAL_METERS

    @property
    def seconds_per_unit(self) -> float:
        """Seconds that make up one unit of the meter (hour, month, ...)."""
        return _METER_SECONDS.get(self, 3600.0)

    @property
    def is_recurring(self) -> bool:
        """True when the recovered quantity keeps accruing every month.

        A GPU left idle wastes GPU-hours again next month, so its claim is a
        run rate. A denied medical claim is recovered exactly once. Both are
        real value and the ledger keeps them apart rather than annualizing a
        one-off into a number a finance team would reject.
        """
        return self not in _ONE_TIME_METERS

    @property
    def is_monthly_rate(self) -> bool:
        """True when the claim is already a per-month figure.

        A $12/month subscription is $12/month whether it was observed over 30
        days or 90. Normalizing it against the window the way an accruing
        meter is normalized would understate it by the length of the window.
        """
        return self in _MONTHLY_RATE_METERS

    @property
    def is_money(self) -> bool:
        """True when the meter is already denominated in dollars."""
        return self in _MONEY_METERS

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

_ONE_TIME_METERS = {
    Meter.CLAIM_DOLLARS,
    Meter.REFUND_DOLLARS,
}

_MONTHLY_RATE_METERS = {
    Meter.RECURRING_DOLLARS,
}

_MONEY_METERS = {
    Meter.COMMITTED_DOLLARS,
    Meter.CLAIM_DOLLARS,
    Meter.REFUND_DOLLARS,
    Meter.RECURRING_DOLLARS,
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
    Meter.CLAIM_DOLLARS: "$ claimed",
    Meter.REFUND_DOLLARS: "$ refundable",
    Meter.RECURRING_DOLLARS: "$/month recurring",
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

    # Consumer domains. Same engine, same output contract, dollar meters.
    CLAIM_RECOVERY = "claim_recovery"
    RECURRING_SPEND = "recurring_spend"


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
