"""Read-only investigation toolbox shared by the specialized agents.

Every tool answers a question about what the cluster actually looked like at
the moment of the observed decision. Tools never mutate anything, never call
a model, and never return a recommendation: they return evidence.

The registry exists so the LLM can *select* tools during investigation. The
LLM does not execute them and cannot invent their results; the runtime runs
the selected tool against the reconstructed state and hands back real numbers.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Any, Callable

from natilah.agents.tools import (
    UtilizationReport,
    best_fit_decreasing_node,
    first_fit_node,
    inspect_utilization,
    list_idle_capacity,
    probe_alternate_placement,
    probe_headroom_size,
    probe_release_idle_gpus,
)
from natilah.engine.history import HistoricalPatternIndex
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import (
    Allocation,
    ClusterDataset,
    ClusterStateSnapshot,
    Job,
    Observation,
    gpu_type_matches,
)

ACTIVE_PCT = 40.0
IDLE_PCT = 5.0


@dataclass
class AgentContext:
    """Everything an agent may look at for one observed decision."""

    dataset: ClusterDataset
    reconstructor: ClusterStateReconstructor
    history: HistoricalPatternIndex
    observation: Observation
    state: ClusterStateSnapshot
    job: Job | None
    allocation: Allocation | None
    utilization: UtilizationReport | None = None
    tools_invoked: list[str] | None = None

    def record_tool(self, name: str) -> None:
        if self.tools_invoked is None:
            self.tools_invoked = []
        if name not in self.tools_invoked:
            self.tools_invoked.append(name)

    @property
    def allocated_gpu_ids(self) -> list[str]:
        return list(self.allocation.gpu_ids) if self.allocation else []

    def hold_window(self) -> tuple[datetime, datetime] | None:
        """The window over which the observed allocation actually held GPUs."""
        alloc = self.allocation
        if alloc is None:
            return None
        end = alloc.end_time
        if end is None and self.job is not None:
            end = self.job.end_time
        if end is None:
            samples = [s.timestamp for s in self.dataset.samples if s.job_id == alloc.job_id]
            end = max(samples) if samples else None
        if end is None or end <= alloc.start_time:
            return None
        return alloc.start_time, end


# --------------------------------------------------------------------- tools


def tool_inspect_utilization(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    job_id = str(args.get("job_id") or (ctx.job.job_id if ctx.job else ""))
    report = inspect_utilization(ctx.dataset, job_id)
    if report is None:
        return {"available": False, "job_id": job_id}
    return {
        "available": True,
        "job_id": report.job_id,
        "allocated_gpus": report.allocated,
        "mean_utilization_pct": round(report.mean_pct, 2),
        "peak_utilization_pct": round(report.peak_pct, 2),
        "active_gpus_above_40pct": report.active_gpus,
        "idle_gpus_below_5pct": report.idle_gpus,
        "per_gpu_mean_pct": {k: round(v, 2) for k, v in report.per_gpu_mean.items()},
    }


def tool_list_idle_capacity(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    min_gpus = int(args.get("min_gpus") or 1)
    gpu_type = args.get("gpu_type")
    if gpu_type is None and ctx.job is not None:
        gpu_type = ctx.job.requested_gpu_type
    caps = list_idle_capacity(ctx.state, gpu_type=gpu_type, min_gpus=min_gpus)
    return {
        "timestamp": ctx.state.timestamp.isoformat(),
        "gpu_type_filter": gpu_type,
        "matching_nodes": len(caps),
        "total_idle_gpus": sum(c.idle_gpus for c in caps),
        "nodes": [
            {
                "node_id": c.node_id,
                "idle_gpus": c.idle_gpus,
                "total_gpus": c.total_gpus,
                "gpu_type": c.gpu_type,
                "idle_gpu_ids": c.idle_gpu_ids[:8],
            }
            for c in caps[:12]
        ],
    }


def tool_inspect_job_constraints(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    job = ctx.job
    if job is None:
        return {"available": False}
    return {
        "available": True,
        "job_id": job.job_id,
        "user": job.user,
        "priority": job.priority,
        "requested_gpus": job.requested_gpus,
        "allocated_gpus": len(ctx.allocated_gpu_ids),
        "requested_gpu_type": job.requested_gpu_type,
        "constraints": dict(job.constraints),
        "nvlink_required": job.constraints.get("nvlink") == "required",
        "min_memory_gb": job.constraints.get("min_memory_gb"),
        "submit_time": job.submit_time.isoformat(),
        "start_time": job.start_time.isoformat() if job.start_time else None,
        "end_time": job.end_time.isoformat() if job.end_time else None,
    }


def tool_inspect_topology(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    node_ids = args.get("node_ids") or (ctx.allocation.node_ids if ctx.allocation else [])
    nodes_by_id = ctx.dataset.node_by_id()
    caps = ctx.state.available_capacity
    out = []
    for node_id in list(node_ids)[:8]:
        node = nodes_by_id.get(node_id)
        cap = caps.by_node.get(node_id)
        if node is None:
            continue
        out.append(
            {
                "node_id": node_id,
                "gpu_type": node.gpu_type.name,
                "gpu_count": node.gpu_count,
                "idle_gpus": cap.idle_gpus if cap else 0,
                "allocated_gpus": cap.allocated_gpus if cap else node.gpu_count,
                "labels": dict(node.labels),
            }
        )
    return {
        "nodes": out,
        "cluster_total_gpus": caps.total_gpus,
        "cluster_idle_gpus": caps.idle_gpus,
        "largest_contiguous_block": caps.largest_contiguous_block,
        "contiguity_index": round(caps.contiguity_index, 4),
        "blocks_by_size": _block_histogram(ctx.state),
    }


def _block_histogram(state: ClusterStateSnapshot) -> dict[str, int]:
    hist: dict[str, int] = defaultdict(int)
    for block in state.available_capacity.blocks():
        hist[str(block.size)] += 1
    return dict(sorted(hist.items(), key=lambda kv: int(kv[0])))


def tool_inspect_queue(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit") or 15)
    pending = []
    for job in ctx.state.pending_jobs[:limit]:
        wait = 0.0
        if job.start_time:
            wait = max(0.0, (job.start_time - job.submit_time).total_seconds())
        pending.append(
            {
                "job_id": job.job_id,
                "requested_gpus": job.requested_gpus,
                "gpu_type": job.requested_gpu_type,
                "priority": job.priority,
                "eventual_wait_seconds": round(wait, 1),
            }
        )
    return {
        "timestamp": ctx.state.timestamp.isoformat(),
        "pending_jobs": len(ctx.state.pending_jobs),
        "running_jobs": len(ctx.state.running_jobs),
        "idle_gpus": ctx.state.available_capacity.idle_gpus,
        "queue": pending,
    }


def tool_inspect_history(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    job_id = str(args.get("job_id") or (ctx.job.job_id if ctx.job else ""))
    return ctx.history.evidence(job_id, ctx.observation.signal_type)


def tool_probe_alternate_placement(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    if ctx.job is None:
        return {"available": False}
    needed = int(args.get("gpu_count") or len(ctx.allocated_gpu_ids) or ctx.job.requested_gpus)
    current = list(ctx.allocation.node_ids) if ctx.allocation else []
    candidates = probe_alternate_placement(ctx.job, ctx.state, current, needed)
    return {
        "available": bool(candidates),
        "needed_gpus": needed,
        "current_nodes": current,
        "options": [
            {
                "description": c.description,
                "node_ids": c.proposed_action.get("node_ids"),
                "search_method": c.proposed_action.get("search_method"),
            }
            for c in candidates
        ],
    }


def tool_probe_headroom_size(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    if ctx.utilization is None:
        return {"available": False}
    headroom = float(args.get("headroom") or 0.20)
    candidate = probe_headroom_size(ctx.utilization, headroom=headroom)
    if candidate is None:
        return {
            "available": False,
            "reason": "Observed peak needs the full allocation at this headroom.",
            "headroom": headroom,
        }
    return {
        "available": True,
        "headroom": headroom,
        "gpu_count": candidate.proposed_action.get("gpu_count"),
        "original_gpu_count": candidate.proposed_action.get("original_gpu_count"),
        "rationale": candidate.rationale,
    }


def tool_probe_release_idle_gpus(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    if ctx.utilization is None:
        return {"available": False}
    dead = [gid for gid, m in ctx.utilization.per_gpu_mean.items() if m < IDLE_PCT]
    candidate = probe_release_idle_gpus(ctx.utilization, ctx.allocated_gpu_ids)
    return {
        "available": candidate is not None,
        "dead_gpu_ids": dead,
        "dead_gpu_count": len(dead),
        "mean_utilization_pct": round(ctx.utilization.mean_pct, 2),
    }


def tool_probe_blocking_jobs(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    """Running jobs that held GPUs they were not using, of a usable type."""
    job = ctx.job
    if job is None:
        return {"available": False}
    blocking = list(ctx.observation.evidence.get("blocking_jobs") or [])
    if blocking:
        return {"available": True, "source": "detector", "blocking_jobs": blocking[:10]}

    alloc_by_job = ctx.dataset.allocation_by_job()
    found = []
    for running in ctx.state.running_jobs:
        alloc = alloc_by_job.get(running.job_id)
        if alloc is None:
            continue
        if not gpu_type_matches(job.requested_gpu_type, running.requested_gpu_type):
            continue
        per_gpu: dict[str, list[float]] = defaultdict(list)
        for sample in ctx.dataset.samples_for_job(running.job_id):
            per_gpu[sample.gpu_id].append(sample.gpu_utilization_pct)
        if not per_gpu:
            continue
        means = {gid: mean(v) for gid, v in per_gpu.items() if v}
        active = sum(1 for v in means.values() if v > ACTIVE_PCT)
        unused = len(alloc.gpu_ids) - active
        if unused >= job.requested_gpus:
            found.append(
                {
                    "job_id": running.job_id,
                    "allocated": len(alloc.gpu_ids),
                    "active": active,
                    "unused": unused,
                    "priority": running.priority,
                    "unused_gpu_ids": [gid for gid, v in means.items() if v <= ACTIVE_PCT][:16],
                }
            )
    found.sort(key=lambda b: (-b["unused"], b["job_id"]))
    return {"available": bool(found), "source": "probe", "blocking_jobs": found[:10]}


def tool_probe_backfill_candidates(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    """Pending jobs that would fit if the named GPUs were freed."""
    freed = list(args.get("gpu_ids") or ctx.observation.affected_gpu_ids or [])
    gpus_by_id = ctx.dataset.gpu_by_id()
    by_node: dict[str, list[str]] = defaultdict(list)
    for gid in freed:
        gpu = gpus_by_id.get(gid)
        if gpu:
            by_node[gpu.node_id].append(gid)
    fits = []
    for pending in ctx.state.pending_jobs[:40]:
        gpu_type = pending.requested_gpu_type
        for node_id, gids in by_node.items():
            node_gpu_type = gpus_by_id[gids[0]].gpu_type.name if gids else None
            if not gpu_type_matches(gpu_type, node_gpu_type):
                continue
            if len(gids) >= pending.requested_gpus:
                fits.append(
                    {
                        "job_id": pending.job_id,
                        "requested_gpus": pending.requested_gpus,
                        "node_id": node_id,
                        "gpu_ids": gids[: pending.requested_gpus],
                        "priority": pending.priority,
                    }
                )
                break
    return {
        "available": bool(fits),
        "freed_gpu_count": len(freed),
        "freed_nodes": sorted(by_node),
        "backfill_candidates": fits[:10],
    }


def tool_probe_consolidation_move(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    """Small running jobs whose relocation would rebuild a contiguous block."""
    needed = int(args.get("needed_gpus") or 8)
    caps = ctx.state.available_capacity
    alloc_by_job = ctx.dataset.allocation_by_job()
    gpus_by_id = ctx.dataset.gpu_by_id()
    moves = []
    for node_id, cap in caps.by_node.items():
        if cap.idle_gpus <= 0 or cap.idle_gpus >= needed:
            continue
        blockers = [
            job
            for job in ctx.state.running_jobs
            if node_id in (alloc_by_job.get(job.job_id).node_ids if alloc_by_job.get(job.job_id) else [])
        ]
        for blocker in blockers:
            alloc = alloc_by_job.get(blocker.job_id)
            if alloc is None or len(alloc.node_ids) != 1:
                continue
            held = len(alloc.gpu_ids)
            if held > cap.total_gpus - needed + cap.idle_gpus:
                continue
            if cap.idle_gpus + held < needed:
                continue
            target = None
            for other_id, other in caps.by_node.items():
                if other_id == node_id or other.idle_gpus < held:
                    continue
                if not gpu_type_matches(cap.gpu_type, other.gpu_type):
                    continue
                target = other
                break
            if target is None:
                continue
            moves.append(
                {
                    "move_job_id": blocker.job_id,
                    "from_node": node_id,
                    "to_node": target.node_id,
                    "gpus_moved": held,
                    "block_created": cap.idle_gpus + held,
                    "target_gpu_ids": target.idle_gpu_ids[:held],
                    "gpu_type": cap.gpu_type,
                    "source_gpu_ids": [
                        gid for gid in alloc.gpu_ids if gpus_by_id.get(gid) and gpus_by_id[gid].node_id == node_id
                    ],
                }
            )
    moves.sort(key=lambda m: (-m["block_created"], m["from_node"], m["move_job_id"]))
    return {"available": bool(moves), "needed_gpus": needed, "moves": moves[:6]}


def tool_probe_single_node_fit(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    if ctx.job is None:
        return {"available": False}
    needed = int(args.get("gpu_count") or ctx.job.requested_gpus)
    ff = first_fit_node(ctx.job, ctx.state, needed)
    bfd = best_fit_decreasing_node(ctx.job, ctx.state, needed)
    return {
        "available": ff is not None or bfd is not None,
        "needed_gpus": needed,
        "first_fit_node": ff.node_id if ff else None,
        "best_fit_node": bfd.node_id if bfd else None,
        "best_fit_idle_gpus": bfd.idle_gpus if bfd else 0,
    }


def tool_inspect_utilization_timeline(ctx: AgentContext, args: dict[str, Any]) -> dict[str, Any]:
    """Coarse utilization timeline for the job, to see ramp-up versus dead hold."""
    job_id = str(args.get("job_id") or (ctx.job.job_id if ctx.job else ""))
    samples = ctx.dataset.samples_for_job(job_id)
    if not samples:
        return {"available": False, "job_id": job_id}
    by_ts: dict[datetime, list[float]] = defaultdict(list)
    for sample in samples:
        by_ts[sample.timestamp].append(sample.gpu_utilization_pct)
    ordered = sorted(by_ts.items())
    step = max(1, len(ordered) // 12)
    points = [
        {"timestamp": ts.isoformat(), "mean_pct": round(mean(vals), 2)}
        for ts, vals in ordered[::step][:12]
    ]
    first_active = next(
        (ts.isoformat() for ts, vals in ordered if mean(vals) > ACTIVE_PCT),
        None,
    )
    last_active = next(
        (ts.isoformat() for ts, vals in reversed(ordered) if mean(vals) > ACTIVE_PCT),
        None,
    )
    return {
        "available": True,
        "job_id": job_id,
        "samples": len(samples),
        "first_active_timestamp": first_active,
        "last_active_timestamp": last_active,
        "timeline": points,
    }


@dataclass
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]
    run: Callable[[AgentContext, dict[str, Any]], dict[str, Any]]


TOOL_REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            "inspect_utilization",
            "Per-GPU mean utilization for a job, with active and dead GPU counts.",
            {"job_id": "job to inspect (default: the observed job)"},
            tool_inspect_utilization,
        ),
        ToolSpec(
            "inspect_utilization_timeline",
            "Coarse utilization timeline for a job: when it first and last did real work.",
            {"job_id": "job to inspect (default: the observed job)"},
            tool_inspect_utilization_timeline,
        ),
        ToolSpec(
            "list_idle_capacity",
            "Nodes with idle GPUs at the decision timestamp, filtered by GPU type.",
            {"min_gpus": "minimum idle GPUs per node", "gpu_type": "GPU type filter"},
            tool_list_idle_capacity,
        ),
        ToolSpec(
            "inspect_job_constraints",
            "Hard constraints on the job: GPU type, NVLink, memory, priority, timing.",
            {},
            tool_inspect_job_constraints,
        ),
        ToolSpec(
            "inspect_topology",
            "Node layout, contiguous free blocks, and cluster-wide contiguity index.",
            {"node_ids": "nodes to inspect (default: the job's nodes)"},
            tool_inspect_topology,
        ),
        ToolSpec(
            "inspect_queue",
            "Pending and running jobs at the decision timestamp with their sizes.",
            {"limit": "max pending jobs to return"},
            tool_inspect_queue,
        ),
        ToolSpec(
            "inspect_history",
            "Recurrence of this signal for the job family and user across the window.",
            {"job_id": "job to inspect (default: the observed job)"},
            tool_inspect_history,
        ),
        ToolSpec(
            "probe_alternate_placement",
            "Feasible single-node placements for the job at the decision timestamp.",
            {"gpu_count": "GPUs to place"},
            tool_probe_alternate_placement,
        ),
        ToolSpec(
            "probe_headroom_size",
            "Smallest allocation that still covers the observed peak plus headroom.",
            {"headroom": "fractional headroom, e.g. 0.2"},
            tool_probe_headroom_size,
        ),
        ToolSpec(
            "probe_release_idle_gpus",
            "GPUs in the allocation that never showed measurable work.",
            {},
            tool_probe_release_idle_gpus,
        ),
        ToolSpec(
            "probe_blocking_jobs",
            "Running jobs holding unused GPUs of a type the waiting job could use.",
            {},
            tool_probe_blocking_jobs,
        ),
        ToolSpec(
            "probe_backfill_candidates",
            "Pending jobs that would fit if the named GPUs were freed.",
            {"gpu_ids": "GPU ids assumed freed"},
            tool_probe_backfill_candidates,
        ),
        ToolSpec(
            "probe_consolidation_move",
            "Single-node jobs whose relocation would rebuild a contiguous block.",
            {"needed_gpus": "block size the pending job needs"},
            tool_probe_consolidation_move,
        ),
        ToolSpec(
            "probe_single_node_fit",
            "Whether one node could hold the whole request (first-fit and best-fit).",
            {"gpu_count": "GPUs needed"},
            tool_probe_single_node_fit,
        ),
    ]
}


def tool_catalog() -> list[dict[str, Any]]:
    """Catalog handed to the LLM so it can choose what to investigate."""
    return [
        {"name": spec.name, "description": spec.description, "args": spec.args}
        for spec in TOOL_REGISTRY.values()
    ]


def run_tool(name: str, ctx: AgentContext, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a registered read-only tool. Unknown names are refused, not guessed."""
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return {"error": f"Unknown tool {name}", "known_tools": sorted(TOOL_REGISTRY)}
    ctx.record_tool(name)
    try:
        return spec.run(ctx, args or {})
    except Exception as exc:  # a broken probe must not kill the analysis
        return {"error": f"{type(exc).__name__}: {exc}", "tool": name}


def gpu_means_for(ctx: AgentContext) -> dict[str, float]:
    """Mean utilization per GPU of the observed allocation."""
    if ctx.utilization is not None:
        return dict(ctx.utilization.per_gpu_mean)
    per_gpu: dict[str, list[float]] = defaultdict(list)
    job_id = ctx.job.job_id if ctx.job else ""
    for sample in ctx.dataset.samples_for_job(job_id):
        per_gpu[sample.gpu_id].append(sample.gpu_utilization_pct)
    return {gid: mean(vals) for gid, vals in per_gpu.items() if vals}


def dead_and_active_gpus(ctx: AgentContext) -> tuple[list[str], list[str]]:
    """Split the allocation into GPUs that did work and GPUs that did not."""
    means = gpu_means_for(ctx)
    allocated = ctx.allocated_gpu_ids or sorted(means)
    dead = [gid for gid in allocated if means.get(gid, 0.0) < IDLE_PCT]
    active = [gid for gid in allocated if means.get(gid, 0.0) >= IDLE_PCT]
    return dead, active


def gpus_ranked_by_activity(ctx: AgentContext) -> list[str]:
    """Allocation GPU ids, busiest first. Used when choosing which to keep."""
    means = gpu_means_for(ctx)
    allocated = ctx.allocated_gpu_ids or sorted(means)
    return sorted(allocated, key=lambda gid: means.get(gid, 0.0), reverse=True)


def wait_window(job: Job) -> tuple[datetime, datetime] | None:
    """Submit-to-start window of a job that queued."""
    if job.start_time is None or job.submit_time is None:
        return None
    if job.start_time <= job.submit_time:
        return None
    return job.submit_time, job.start_time


def clamp_window(
    window: tuple[datetime, datetime],
    max_hours: float,
) -> tuple[datetime, datetime]:
    start, end = window
    if (end - start) > timedelta(hours=max_hours):
        return start, start + timedelta(hours=max_hours)
    return start, end
