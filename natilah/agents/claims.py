"""Helpers for building a finding's resource claim.

A claim is the contract between an agent and the coordination layer: exactly
which GPUs, over exactly which window, plus whose queue time. Value is priced
from the claim, and the coordination layer deduplicates the same claim across
agents, so both numbers always agree.
"""

from __future__ import annotations

from datetime import datetime

from natilah.models.domain import GPUInterval, ResourceClaim

Window = tuple[datetime, datetime]


def parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def intervals_for(gpu_ids: list[str], window: Window | None) -> list[GPUInterval]:
    if window is None:
        return []
    start, end = window
    if end <= start:
        return []
    seen: set[str] = set()
    intervals: list[GPUInterval] = []
    for gpu_id in gpu_ids:
        if gpu_id in seen:
            continue
        seen.add(gpu_id)
        intervals.append(GPUInterval(gpu_id=gpu_id, start=start, end=end))
    return intervals


def free_window(
    dataset,
    gpu_ids: list[str],
    window: Window,
    needed: int,
    holder_job_id: str | None = None,
) -> tuple[list[GPUInterval], datetime | None]:
    """How long a set of GPUs actually stayed available inside a window.

    A counterfactual that starts a job earlier only holds while the capacity is
    still there. If another job took one of these GPUs midway, the claim stops
    at that point instead of pricing the whole wait.
    """
    start, end = window
    if end <= start or not gpu_ids:
        return [], None
    free_until: dict[str, datetime] = {gpu_id: end for gpu_id in gpu_ids}
    for alloc in dataset.allocations:
        if alloc.job_id == holder_job_id:
            continue
        if alloc.start_time <= start or alloc.start_time >= end:
            continue
        for gpu_id in alloc.gpu_ids:
            if gpu_id in free_until and alloc.start_time < free_until[gpu_id]:
                free_until[gpu_id] = alloc.start_time
    if holder_job_id is not None:
        holder = dataset.allocation_by_job().get(holder_job_id)
        if holder is not None and holder.end_time is not None:
            for gpu_id in list(free_until):
                free_until[gpu_id] = min(free_until[gpu_id], max(holder.end_time, start))

    ordered = sorted(free_until.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) < needed:
        return [], None
    effective_end = ordered[needed - 1][1]
    if effective_end <= start:
        return [], None
    intervals = [
        GPUInterval(gpu_id=gpu_id, start=start, end=effective_end) for gpu_id, _ in ordered[:needed]
    ]
    return intervals, effective_end


def explicit_claim(action: dict, basis: str = "") -> ResourceClaim | None:
    """Claim fields a deterministic tool candidate attached to its action."""
    gpu_ids = list(action.get("claim_gpu_ids") or [])
    start = parse_dt(action.get("claim_start"))
    end = parse_dt(action.get("claim_end"))
    queue_jobs = list(action.get("claim_queue_job_ids") or [])
    queue_seconds = float(action.get("claim_queue_seconds") or 0.0)
    if not gpu_ids and not queue_jobs:
        return None
    window = (start, end) if start and end else None
    return ResourceClaim(
        intervals=intervals_for(gpu_ids, window),
        queue_job_ids=queue_jobs,
        queue_seconds=queue_seconds,
        basis=str(action.get("claim_basis") or basis),
    )


def attach_claim(
    action: dict,
    gpu_ids: list[str],
    window: Window | None,
    basis: str,
    queue_job_ids: list[str] | None = None,
    queue_seconds: float = 0.0,
) -> dict:
    """Record a claim on a proposed action so pricing and dedup use one source."""
    action["claim_gpu_ids"] = list(gpu_ids)
    if window is not None:
        action["claim_start"] = window[0].isoformat()
        action["claim_end"] = window[1].isoformat()
    action["claim_basis"] = basis
    if queue_job_ids:
        action["claim_queue_job_ids"] = list(queue_job_ids)
        action["claim_queue_seconds"] = queue_seconds
    return action
