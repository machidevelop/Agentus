"""Multi-meter claim ledger used by the coordination layer.

Two agents can describe the same waste from different angles: the
idle-allocation agent sees a job holding dead GPUs, the queue agent sees a
pending job that those same GPUs could have run. Both findings are true; the
GPU-hours behind them are the same hours and must be counted once.

The same problem appears in every domain the fleet grows into — two storage
agents pointing at one volume, a power agent and a scheduling agent pricing
one idle GPU — so the ledger is generic over *meters*:

* **Interval meters** (GPU-hours, GB-months, kWh, replica-hours, CPU-hours)
  accrue over time against a named resource. Dedup is an interval union per
  resource, weighted by how much of the resource is held.
* **Quantity meters** (queue-seconds, GB transferred, dollars committed) have
  no time dimension. Dedup is a high-water mark per resource.

Meters never mix: a storage claim cannot cancel a GPU claim, because they are
keyed separately. Findings are inserted in priority order; each is credited
only with what no higher-priority finding already claimed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from natilah.models.domain import ResourceClaim
from natilah.models.enums import Meter

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
class MeterAttribution:
    """What one finding is credited with in one meter."""

    meter: Meter
    claimed: float = 0.0
    attributed: float = 0.0
    overlap: float = 0.0

    @property
    def ratio(self) -> float:
        if self.claimed <= 0:
            return 1.0
        return max(0.0, min(1.0, self.attributed / self.claimed))


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
    per_meter: dict[Meter, MeterAttribution] = field(default_factory=dict)

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
        """Fraction of the finding's economic value that survives deduplication.

        A finding is worth what its most-contested meter allows: if any meter
        it charges was already claimed elsewhere, the value shrinks with it.
        """
        ratios = [m.ratio for m in self.per_meter.values() if m.claimed > 0]
        ratios.extend([self.gpu_hour_ratio, self.queue_ratio])
        return min(ratios) if ratios else 1.0

    @property
    def attributed_total(self) -> float:
        """Everything credited, across meters. Only meaningful per meter."""
        return sum(m.attributed for m in self.per_meter.values())

    def meter(self, meter: Meter) -> MeterAttribution:
        return self.per_meter.setdefault(meter, MeterAttribution(meter=meter))


class ClaimLedger:
    """Interval union and quantity caps, kept separately per meter."""

    def __init__(self) -> None:
        self._intervals: dict[tuple[Meter, str], list[Interval]] = {}
        self._owners: dict[tuple[Meter, str], list[tuple[datetime, datetime, str]]] = {}
        self._quantities: dict[tuple[Meter, str], float] = {}
        self._quantity_owner: dict[tuple[Meter, str], str] = {}
        self.total_overlap_gpu_hours = 0.0
        self.total_overlap_queue_seconds = 0.0
        self.overlap_by_meter: dict[Meter, float] = {}

    # ------------------------------------------------------------------ entry

    def attribute(self, finding_id: str, claim: ResourceClaim) -> ClaimAttribution:
        """Credit a claim against the ledger and record what it consumed."""
        result = ClaimAttribution(
            claimed_gpu_hours=claim.gpu_hours,
            claimed_queue_seconds=claim.queue_seconds,
        )
        overlapping: set[str] = set()

        # Legacy GPU intervals: magnitude 1, priced per hour.
        for interval in claim.intervals:
            self._credit_interval(
                finding_id=finding_id,
                meter=Meter.GPU_HOURS,
                resource_id=interval.gpu_id,
                span=(interval.start, interval.end),
                magnitude=1.0,
                result=result,
                overlapping=overlapping,
            )

        for interval in claim.resource_intervals:
            self._credit_interval(
                finding_id=finding_id,
                meter=interval.meter,
                resource_id=interval.resource_id,
                span=(interval.start, interval.end),
                magnitude=interval.magnitude,
                result=result,
                overlapping=overlapping,
            )

        # Legacy queue seconds: split evenly across the jobs they belong to.
        if claim.queue_seconds > 0 and claim.queue_job_ids:
            per_job = claim.queue_seconds / len(claim.queue_job_ids)
            for job_id in claim.queue_job_ids:
                self._credit_quantity(
                    finding_id=finding_id,
                    meter=Meter.QUEUE_SECONDS,
                    resource_id=job_id,
                    amount=per_job,
                    result=result,
                    overlapping=overlapping,
                )
        elif claim.queue_seconds > 0:
            result.attributed_queue_seconds = claim.queue_seconds
            bucket = result.meter(Meter.QUEUE_SECONDS)
            bucket.claimed += claim.queue_seconds
            bucket.attributed += claim.queue_seconds

        for quantity in claim.quantities:
            self._credit_quantity(
                finding_id=finding_id,
                meter=quantity.meter,
                resource_id=quantity.resource_id,
                amount=quantity.amount,
                result=result,
                overlapping=overlapping,
            )

        overlapping.discard(finding_id)
        result.overlapping_finding_ids = sorted(overlapping)
        self.total_overlap_gpu_hours += result.overlap_gpu_hours
        self.total_overlap_queue_seconds += result.overlap_queue_seconds
        return result

    # ---------------------------------------------------------------- credits

    def _credit_interval(
        self,
        finding_id: str,
        meter: Meter,
        resource_id: str,
        span: Interval,
        magnitude: float,
        result: ClaimAttribution,
        overlapping: set[str],
    ) -> None:
        duration = max(0.0, (span[1] - span[0]).total_seconds())
        if duration <= 0 or magnitude <= 0:
            return
        key = (meter, resource_id)
        existing = self._intervals.get(key, [])
        taken = 0.0
        for other in existing:
            taken += overlap_seconds(span, other)
        taken = min(taken, duration)

        per_unit = meter.seconds_per_unit
        credited = magnitude * (duration - taken) / per_unit
        overlapped = magnitude * taken / per_unit

        bucket = result.meter(meter)
        bucket.claimed += magnitude * duration / per_unit
        bucket.attributed += credited
        bucket.overlap += overlapped
        if meter is Meter.GPU_HOURS:
            result.attributed_gpu_hours += credited
            result.overlap_gpu_hours += overlapped

        if taken > 0:
            for start, end, owner in self._owners.get(key, []):
                if overlap_seconds(span, (start, end)) > 0:
                    overlapping.add(owner)
            self.overlap_by_meter[meter] = self.overlap_by_meter.get(meter, 0.0) + overlapped

        self._intervals[key] = merge_intervals(existing + [span])
        self._owners.setdefault(key, []).append((span[0], span[1], finding_id))

    def _credit_quantity(
        self,
        finding_id: str,
        meter: Meter,
        resource_id: str,
        amount: float,
        result: ClaimAttribution,
        overlapping: set[str],
    ) -> None:
        if amount <= 0:
            return
        key = (meter, resource_id)
        already = self._quantities.get(key, 0.0)
        credited = max(0.0, amount - already)
        overlapped = amount - credited

        bucket = result.meter(meter)
        bucket.claimed += amount
        bucket.attributed += credited
        bucket.overlap += overlapped
        if meter is Meter.QUEUE_SECONDS:
            result.attributed_queue_seconds += credited
            result.overlap_queue_seconds += overlapped

        if overlapped > 0:
            owner = self._quantity_owner.get(key)
            if owner:
                overlapping.add(owner)
            self.overlap_by_meter[meter] = self.overlap_by_meter.get(meter, 0.0) + overlapped
        if already <= 0:
            self._quantity_owner[key] = finding_id
        self._quantities[key] = max(already, amount)


# The ledger was GPU-only when the four scheduling agents were written.
GPUHourLedger = ClaimLedger
