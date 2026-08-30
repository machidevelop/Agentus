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
