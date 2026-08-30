"""Read-only tools an agent may call. None of these is the product architecture.

Bin packing, headroom sizing, and similar routines live here so an agent can
ask a question ("was a single node free?") without the pipeline assuming the
answer is always "run BFD" or "always downsize".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from natilah.models.domain import (
    ClusterDataset,
    ClusterStateSnapshot,
    Job,
    NodeCapacity,
    gpu_type_matches,
)


@dataclass
class UtilizationReport:
    job_id: str
    allocated: int
    mean_pct: float
    peak_pct: float
    per_gpu_mean: dict[str, float]
    active_gpus: int
    idle_gpus: int


@dataclass
class ToolCandidate:
    kind: str
    description: str
    proposed_action: dict
    rationale: str
    tool_name: str
    extra: dict = field(default_factory=dict)


def inspect_utilization(dataset: ClusterDataset, job_id: str) -> UtilizationReport | None:
    samples = dataset.samples_for_job(job_id)
    alloc = dataset.allocation_by_job().get(job_id)
    if not alloc:
        return None
    per_gpu: dict[str, list[float]] = {gid: [] for gid in alloc.gpu_ids}
    peaks: list[float] = []
    by_ts: dict = {}
    for sample in samples:
        per_gpu.setdefault(sample.gpu_id, []).append(sample.gpu_utilization_pct)
        by_ts.setdefault(sample.timestamp, []).append(sample.gpu_utilization_pct)
    for vals in by_ts.values():
        peaks.append(mean(vals))
    means = {gid: (mean(vals) if vals else 0.0) for gid, vals in per_gpu.items()}
    overall = mean(means.values()) if means else 0.0
    peak = max(peaks) if peaks else overall
    active = sum(1 for v in means.values() if v > 40.0)
    idle = sum(1 for v in means.values() if v < 5.0)
    return UtilizationReport(
        job_id=job_id,
        allocated=len(alloc.gpu_ids),
        mean_pct=overall,
        peak_pct=peak,
        per_gpu_mean=means,
        active_gpus=active,
        idle_gpus=idle,
    )


def list_idle_capacity(
    state: ClusterStateSnapshot,
    gpu_type: str | None = None,
    min_gpus: int = 1,
) -> list[NodeCapacity]:
    out = []
    for cap in state.available_capacity.by_node.values():
        if cap.idle_gpus < min_gpus:
            continue
        if not gpu_type_matches(gpu_type, cap.gpu_type):
            continue
        out.append(cap)
    out.sort(key=lambda c: c.idle_gpus, reverse=True)
    return out


def probe_headroom_size(report: UtilizationReport, headroom: float = 0.20) -> ToolCandidate | None:
    """Ask: could fewer GPUs have covered the observed peak plus headroom?

    Returns None when the observed peak needs the full allocation.
    """
    if report.allocated < 2:
        return None
    # Peak is cluster-mean across GPUs; also consider count of GPUs that were actually active.
    needed_from_active = int(round(report.active_gpus * (1.0 + headroom)))
    needed_from_peak = max(1, int((report.peak_pct / 100.0) * report.allocated * (1.0 + headroom) + 0.999))
    needed = max(needed_from_active, 1)
    # If peak is high on all GPUs, do not suggest shrinking.
    if report.mean_pct >= 40.0 and report.active_gpus > report.allocated * 0.5:
        return None
    if needed >= report.allocated:
        return None
    # Keep at least the number of GPUs that were truly active.
    needed = min(max(needed, report.active_gpus, needed_from_peak if report.peak_pct > 40 else needed), report.allocated - 1)
    if needed >= report.allocated:
        return None
    return ToolCandidate(
        kind="resize",
        description=f"Allocate {needed} GPUs instead of {report.allocated} (observed peak plus {int(headroom * 100)}% headroom).",
        proposed_action={
            "kind": "resize",
            "gpu_count": needed,
            "requested_gpus": needed,
            "original_gpu_count": report.allocated,
        },
        rationale=(
            f"Observed mean utilization {report.mean_pct:.1f}% with {report.active_gpus} of "
            f"{report.allocated} GPUs above 40%. A {needed}-GPU allocation covers that peak with headroom."
        ),
        tool_name="probe_headroom_size",
    )


def first_fit_node(job: Job, state: ClusterStateSnapshot, needed: int) -> NodeCapacity | None:
    for cap in state.available_capacity.by_node.values():
        if not gpu_type_matches(job.requested_gpu_type, cap.gpu_type):
            continue
        if cap.idle_gpus >= needed:
            return cap
    return None


def best_fit_decreasing_node(job: Job, state: ClusterStateSnapshot, needed: int) -> NodeCapacity | None:
    """BFD as a search tool: smallest idle block that still fits. Not a policy."""
    fits = [
        cap
        for cap in state.available_capacity.by_node.values()
        if cap.idle_gpus >= needed and gpu_type_matches(job.requested_gpu_type, cap.gpu_type)
    ]
    if not fits:
        return None
    fits.sort(key=lambda c: c.idle_gpus)
    return fits[0]


def probe_alternate_placement(
    job: Job,
    state: ClusterStateSnapshot,
    current_node_ids: list[str],
    needed: int,
) -> list[ToolCandidate]:
    """Ask whether a different feasible placement existed. May consult packing tools."""
    candidates: list[ToolCandidate] = []
    ff = first_fit_node(job, state, needed)
    bfd = best_fit_decreasing_node(job, state, needed)
    seen: set[str] = set()
    for cap, method in ((ff, "first_fit"), (bfd, "best_fit_decreasing")):
        if cap is None or cap.node_id in seen:
            continue
        if set(current_node_ids) == {cap.node_id}:
            continue
        seen.add(cap.node_id)
        gpu_ids = cap.idle_gpu_ids[:needed]
        candidates.append(
            ToolCandidate(
                kind="place",
                description=f"Place {needed} GPUs on {cap.node_id} instead of {', '.join(current_node_ids)}.",
                proposed_action={
                    "kind": "place",
                    "gpu_count": needed,
                    "gpu_ids": gpu_ids,
                    "node_ids": [cap.node_id],
                    "require_single_node": True,
                    "search_method": method,
                },
                rationale=(
                    f"At decision time {cap.node_id} had {cap.idle_gpus} idle {cap.gpu_type} GPUs. "
                    f"Search tool '{method}' found this node; it is a feasible placement, not a mandated policy."
                ),
                tool_name=f"probe_alternate_placement:{method}",
            )
        )
    return candidates


def probe_release_idle_gpus(report: UtilizationReport, alloc_gpu_ids: list[str]) -> ToolCandidate | None:
    idle_ids = [gid for gid, m in report.per_gpu_mean.items() if m < 5.0]
    if not idle_ids or report.mean_pct >= 5.0 and report.idle_gpus < 2:
        if report.mean_pct >= 5.0:
            return None
    if report.mean_pct >= 5.0:
        return None
    return ToolCandidate(
        kind="release_gpus",
        description=f"Release {len(alloc_gpu_ids)} idle GPUs held by {report.job_id}.",
        proposed_action={
            "kind": "release_gpus",
            "gpu_count": 0,
            "release_gpu_ids": list(alloc_gpu_ids),
            "original_gpu_count": report.allocated,
        },
        rationale=(
            f"Mean utilization {report.mean_pct:.2f}% over the hold period. "
            "The GPUs were allocated but not doing useful work."
        ),
        tool_name="probe_release_idle_gpus",
    )


def probe_unblocked_queue(
    waiting_job: Job,
    state: ClusterStateSnapshot,
    blocking: list[dict],
) -> ToolCandidate | None:
    """Ask whether a waiting job could have started under a different feasible hold."""
    if not blocking:
        # Could it have started on idle capacity as-is?
        cap = first_fit_node(waiting_job, state, waiting_job.requested_gpus)
        if cap is None:
            return None
        wait = 0.0
        if waiting_job.start_time and waiting_job.submit_time:
            wait = (waiting_job.start_time - waiting_job.submit_time).total_seconds()
        return ToolCandidate(
            kind="reorder",
            description=f"Start {waiting_job.job_id} on {cap.node_id} at submit time using idle capacity.",
            proposed_action={
                "kind": "reorder",
                "gpu_count": waiting_job.requested_gpus,
                "gpu_ids": cap.idle_gpu_ids[: waiting_job.requested_gpus],
                "node_ids": [cap.node_id],
                "start_job_id": waiting_job.job_id,
                "unblocked_job_ids": [waiting_job.job_id],
                "queue_time_reduction_seconds": wait,
            },
            rationale=f"{cap.node_id} had {cap.idle_gpus} idle GPUs when {waiting_job.job_id} was queued.",
            tool_name="probe_unblocked_queue:idle",
        )

    blocker = max(blocking, key=lambda b: b.get("unused", 0))
    wait = 0.0
    if waiting_job.start_time and waiting_job.submit_time:
        wait = (waiting_job.start_time - waiting_job.submit_time).total_seconds()
    return ToolCandidate(
        kind="reorder",
        description=(
            f"If {blocker['job_id']} had held {blocker['active']} GPUs instead of {blocker['allocated']}, "
            f"{waiting_job.job_id} could have started without waiting {wait / 60:.0f} minutes."
        ),
        proposed_action={
            "kind": "reorder",
            "gpu_count": waiting_job.requested_gpus,
            "start_job_id": waiting_job.job_id,
            "unblocked_job_ids": [waiting_job.job_id],
            "release_from_job_id": blocker["job_id"],
            "queue_time_reduction_seconds": wait,
            "original_gpu_count": blocker["allocated"],
        },
        rationale=(
            f"{blocker['job_id']} held {blocker['unused']} unused GPUs while higher-value work waited. "
            "This is a counterfactual on the observed hold, not a queue-policy recommendation."
        ),
        tool_name="probe_unblocked_queue:blocker",
        extra={"blocker": blocker},
    )
