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
