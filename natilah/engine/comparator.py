"""Compare observed decision X against a feasible alternative Y.

Forward-simulates only the affected jobs and immediate queue neighbors.
Does not re-schedule the cluster.
"""

from __future__ import annotations

from datetime import timedelta
from statistics import mean

from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import (
    Alternative,
    ClusterDataset,
    ClusterStateSnapshot,
    ComparisonResult,
    DecisionMetrics,
    Job,
    MetricsDelta,
    Observation,
)


def _fragmentation_score(state: ClusterStateSnapshot) -> float:
    total = state.available_capacity.total_gpus or 1
    stranded = 0
    for cap in state.available_capacity.by_node.values():
        if 0 < cap.idle_gpus < cap.total_gpus:
            stranded += cap.idle_gpus
    return stranded / total


def _job_gpu_hours(job: Job, gpu_count: int) -> float:
    if job.start_time is None or job.end_time is None:
        return 0.0
    hours = (job.end_time - job.start_time).total_seconds() / 3600.0
    return hours * gpu_count


class Comparator:
    def compare(
        self,
        observation: Observation,
        alternative: Alternative,
        dataset: ClusterDataset,
        reconstructor: ClusterStateReconstructor,
        state: ClusterStateSnapshot,
    ) -> ComparisonResult:
        jobs_by_id = dataset.job_by_id()
        alloc_by_job = dataset.allocation_by_job()
        primary_id = observation.affected_job_ids[0] if observation.affected_job_ids else observation.decision.job_id
        job = jobs_by_id.get(primary_id)
        alloc = alloc_by_job.get(primary_id)
        action = alternative.proposed_action or {}

        actual_gpu_count = len(alloc.gpu_ids) if alloc else (job.requested_gpus if job else 0)
        alt_gpu_count = int(action.get("gpu_count") or action.get("requested_gpus") or actual_gpu_count)
        if action.get("kind") == "release_gpus":
            released = len(action.get("release_gpu_ids") or [])
            alt_gpu_count = max(0, actual_gpu_count - released)

        duration_h = 0.0
        if job and job.start_time and job.end_time:
            duration_h = (job.end_time - job.start_time).total_seconds() / 3600.0
        elif alloc and alloc.end_time:
            duration_h = (alloc.end_time - alloc.start_time).total_seconds() / 3600.0

        samples = [s for s in dataset.samples if s.job_id == primary_id]
        actual_util = mean(s.gpu_utilization_pct for s in samples) if samples else 0.0
        actual_mem = mean(s.memory_utilization_pct for s in samples) if samples else 0.0
        idle_threshold = 5.0
        idle_ratio = (
            sum(1 for s in samples if s.gpu_utilization_pct < idle_threshold) / len(samples) if samples else 0.0
        )

        actual_gpu_hours = actual_gpu_count * duration_h
        alt_gpu_hours = alt_gpu_count * duration_h
        # If Y uses fewer GPUs for the same work, utilization on remaining GPUs rises.
        alt_util = actual_util
        if alt_gpu_count > 0 and alt_gpu_count < actual_gpu_count and actual_gpu_count > 0:
            alt_util = min(100.0, actual_util * (actual_gpu_count / alt_gpu_count))

        actual_frag = _fragmentation_score(state)
        alt_frag = actual_frag
        if action.get("kind") in {"place", "consolidate"} or action.get("node_ids"):
            # Single-node placement of a previously split job reduces stranded capacity.
            if alloc and len(alloc.node_ids) > 1 and len(action.get("node_ids") or []) == 1:
                alt_frag = max(0.0, actual_frag - (actual_gpu_count / max(state.available_capacity.total_gpus, 1)))
            if action.get("kind") == "consolidate":
                alt_frag = max(0.0, actual_frag * 0.5)

        actual_queue = 0.0
        alt_queue = 0.0
        extra_jobs = 0
        if job and job.start_time and job.submit_time:
            actual_queue = (job.start_time - job.submit_time).total_seconds()
        wait_reduction = float(action.get("queue_time_reduction_seconds") or 0.0)
        unblocked = action.get("unblocked_job_ids") or []
        if wait_reduction:
            alt_queue = max(0.0, actual_queue - wait_reduction)
            extra_jobs = len(unblocked) or 1
        elif unblocked:
            extra_jobs = len(unblocked)
            for uid in unblocked:
                ujob = jobs_by_id.get(uid)
                if ujob and ujob.start_time and ujob.submit_time:
                    actual_queue += (ujob.start_time - ujob.submit_time).total_seconds()
            alt_queue = 0.0

        idle_hours_actual = actual_gpu_hours * idle_ratio
        idle_hours_alt = 0.0 if alt_gpu_count < actual_gpu_count or action.get("kind") == "release_gpus" else idle_hours_actual * 0.2

        window_h = duration_h if duration_h > 0 else 1.0
        actual = DecisionMetrics(
            gpu_hours=actual_gpu_hours,
            avg_gpu_utilization=actual_util,
            avg_memory_utilization=actual_mem,
            idle_gpu_hours=idle_hours_actual,
            fragmentation_score=actual_frag,
            queue_time_seconds=actual_queue,
            jobs_completable=1,
            throughput_jobs_per_hour=1.0 / window_h,
        )
        alternative_metrics = DecisionMetrics(
            gpu_hours=alt_gpu_hours,
            avg_gpu_utilization=alt_util,
            avg_memory_utilization=actual_mem,
            idle_gpu_hours=idle_hours_alt,
            fragmentation_score=alt_frag,
            queue_time_seconds=alt_queue,
            jobs_completable=1 + extra_jobs,
            throughput_jobs_per_hour=(1.0 + extra_jobs) / window_h,
        )
        delta = MetricsDelta(
            gpu_hours_saved=max(0.0, actual.gpu_hours - alternative_metrics.gpu_hours),
            utilization_improvement=alternative_metrics.avg_gpu_utilization - actual.avg_gpu_utilization,
            idle_hours_recovered=max(0.0, actual.idle_gpu_hours - alternative_metrics.idle_gpu_hours),
            fragmentation_reduction=max(0.0, actual.fragmentation_score - alternative_metrics.fragmentation_score),
            queue_time_reduction=max(0.0, actual.queue_time_seconds - alternative_metrics.queue_time_seconds),
            additional_jobs_serviceable=max(0, extra_jobs),
        )
        return ComparisonResult(actual=actual, alternative=alternative_metrics, delta=delta)
