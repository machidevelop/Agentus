"""GPU-hour ledger used by the coordination layer.

Two agents can describe the same wasted GPU-hours from different angles: the
idle-allocation agent sees a job holding dead GPUs, the queue agent sees a
pending job that those same GPUs could have run. Both findings are true; the
GPU-hours behind them are the same hours and must be counted once.

The ledger is a deterministic interval union per GPU, plus a per-job cap on
queue seconds. Findings are inserted in priority order; each one is credited
only with the hours no higher-priority finding already claimed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from natilah.models.domain import ResourceClaim

Interval = tuple[datetime, datetime]


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    """Union of half-open intervals, sorted by start."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: iv[0])
    merged: list[Interval] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    return merged


def overlap_seconds(a: Interval, b: Interval) -> float:
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    return max(0.0, (end - start).total_seconds())


@dataclass
class ClaimAttribution:
    """What a single finding is actually credited with after deduplication."""

    claimed_gpu_hours: float = 0.0
    attributed_gpu_hours: float = 0.0
    overlap_gpu_hours: float = 0.0
    claimed_queue_seconds: float = 0.0
    attributed_queue_seconds: float = 0.0
    overlap_queue_seconds: float = 0.0
    overlapping_finding_ids: list[str] = field(default_factory=list)

    @property
    def gpu_hour_ratio(self) -> float:
        if self.claimed_gpu_hours <= 0:
            return 1.0
        return max(0.0, min(1.0, self.attributed_gpu_hours / self.claimed_gpu_hours))

    @property
    def queue_ratio(self) -> float:
        if self.claimed_queue_seconds <= 0:
            return 1.0
        return max(0.0, min(1.0, self.attributed_queue_seconds / self.claimed_queue_seconds))

    @property
    def value_ratio(self) -> float:
        """Fraction of the finding's economic value that survives deduplication."""
        return min(self.gpu_hour_ratio, self.queue_ratio)


class GPUHourLedger:
    """Interval union per GPU plus a per-job queue-second cap."""

    def __init__(self) -> None:
        self._by_gpu: dict[str, list[Interval]] = {}
        self._owners: dict[str, list[tuple[datetime, datetime, str]]] = {}
        self._queue_claimed: dict[str, float] = {}
        self._queue_owner: dict[str, str] = {}
        self.total_overlap_gpu_hours = 0.0
        self.total_overlap_queue_seconds = 0.0

    def attribute(self, finding_id: str, claim: ResourceClaim) -> ClaimAttribution:
        """Credit a claim against the ledger and record what it consumed."""
        result = ClaimAttribution(
            claimed_gpu_hours=claim.gpu_hours,
            claimed_queue_seconds=claim.queue_seconds,
        )
        overlapping: set[str] = set()

        for interval in claim.intervals:
            span = (interval.start, interval.end)
            duration = max(0.0, (interval.end - interval.start).total_seconds())
            if duration <= 0:
                continue
            existing = self._by_gpu.get(interval.gpu_id, [])
            taken = 0.0
            for other in existing:
                taken += overlap_seconds(span, other)
            taken = min(taken, duration)
            result.attributed_gpu_hours += (duration - taken) / 3600.0
            result.overlap_gpu_hours += taken / 3600.0
            if taken > 0:
                for start, end, owner in self._owners.get(interval.gpu_id, []):
                    if overlap_seconds(span, (start, end)) > 0:
                        overlapping.add(owner)
            self._by_gpu[interval.gpu_id] = merge_intervals(existing + [span])
            self._owners.setdefault(interval.gpu_id, []).append(
                (interval.start, interval.end, finding_id)
            )

        if claim.queue_seconds > 0 and claim.queue_job_ids:
            per_job = claim.queue_seconds / len(claim.queue_job_ids)
            for job_id in claim.queue_job_ids:
                already = self._queue_claimed.get(job_id, 0.0)
                credited = max(0.0, per_job - already)
                result.attributed_queue_seconds += credited
                result.overlap_queue_seconds += per_job - credited
                if per_job - credited > 0 and job_id in self._queue_owner:
                    overlapping.add(self._queue_owner[job_id])
                if already <= 0:
                    self._queue_owner[job_id] = finding_id
                self._queue_claimed[job_id] = max(already, per_job)
        else:
            result.attributed_queue_seconds = claim.queue_seconds

        overlapping.discard(finding_id)
        result.overlapping_finding_ids = sorted(overlapping)
        self.total_overlap_gpu_hours += result.overlap_gpu_hours
        self.total_overlap_queue_seconds += result.overlap_queue_seconds
        return result
