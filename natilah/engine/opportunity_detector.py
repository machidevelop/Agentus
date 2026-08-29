"""Signal detectors. They observe inefficiency; they do not prescribe a fix."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import timedelta
from statistics import mean
from uuid import uuid4

from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import ClusterDataset, Observation, SchedulerDecision
from natilah.models.enums import DecisionType, OpportunityType


class SignalDetector(ABC):
    signal_type: OpportunityType

    @abstractmethod
    def detect(self, dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> list[Observation]:
        ...


def _decision_for_job(dataset: ClusterDataset, job_id: str) -> SchedulerDecision:
    for decision in dataset.decisions:
        if decision.job_id == job_id and decision.decision_type == DecisionType.ALLOCATE:
            return decision
    job = dataset.job_by_id().get(job_id)
    ts = job.start_time if job and job.start_time else (job.submit_time if job else None)
    return SchedulerDecision(
        decision_id=f"dec-inferred-{job_id}",
        timestamp=ts,
        decision_type=DecisionType.ALLOCATE,
        job_id=job_id,
        chosen_action={},
    )


class OverAllocationDetector(SignalDetector):
    signal_type = OpportunityType.OVER_ALLOCATION

    def detect(self, dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> list[Observation]:
        observations: list[Observation] = []
        samples_by_job: dict[str, list] = defaultdict(list)
        for sample in dataset.samples:
            if sample.job_id:
                samples_by_job[sample.job_id].append(sample)

        for alloc in dataset.allocations:
            if len(alloc.gpu_ids) < 4:
                continue
            job_samples = samples_by_job.get(alloc.job_id, [])
            if not job_samples:
                continue
            duration = (alloc.end_time or alloc.start_time) - alloc.start_time
            if duration < timedelta(minutes=30):
                continue
            by_gpu: dict[str, list[float]] = defaultdict(list)
            for sample in job_samples:
                by_gpu[sample.gpu_id].append(sample.gpu_utilization_pct)
            if not by_gpu:
                continue
            gpu_means = {gid: mean(vals) for gid, vals in by_gpu.items()}
            overall = mean(gpu_means.values())
            active = sum(1 for v in gpu_means.values() if v > 40.0)
            allocated = len(alloc.gpu_ids)
            if overall >= 40.0 and active > allocated * 0.5:
                continue
            observations.append(
                Observation(
                    observation_id=str(uuid4()),
                    signal_type=self.signal_type,
                    decision=_decision_for_job(dataset, alloc.job_id),
                    timestamp=alloc.start_time,
                    severity=min(1.0, (1.0 - overall / 100.0) * (1.0 - active / allocated)),
                    description=(
                        f"Job {alloc.job_id} was allocated {allocated} GPUs but only {active} "
                        f"showed mean utilization above 40% (cluster-wide mean {overall:.1f}%)."
                    ),
                    affected_job_ids=[alloc.job_id],
                    affected_gpu_ids=alloc.gpu_ids,
                    evidence={
                        "allocated_gpus": allocated,
                        "active_gpus": active,
                        "mean_utilization_pct": overall,
                        "gpu_means": gpu_means,
                        "duration_seconds": duration.total_seconds(),
                    },
                )
            )
        return observations


class PlacementDetector(SignalDetector):
    signal_type = OpportunityType.POOR_PLACEMENT

    def detect(self, dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> list[Observation]:
        observations: list[Observation] = []
        for alloc in dataset.allocations:
            if len(alloc.node_ids) < 2 or len(alloc.gpu_ids) < 2:
                continue
            job = dataset.job_by_id().get(alloc.job_id)
            if job is None:
                continue
            # Reconstruct just before the allocation so this job is not occupying the nodes.
            t = alloc.start_time - timedelta(seconds=1)
            state = reconstructor.reconstruct(t)
            gpu_type = job.requested_gpu_type
            needed = len(alloc.gpu_ids)
            single_node_options = [
                cap
                for cap in state.available_capacity.by_node.values()
                if cap.idle_gpus >= needed and (gpu_type is None or cap.gpu_type == gpu_type)
            ]
            if not single_node_options:
                continue
            observations.append(
                Observation(
                    observation_id=str(uuid4()),
                    signal_type=self.signal_type,
                    decision=_decision_for_job(dataset, alloc.job_id),
                    timestamp=alloc.start_time,
                    severity=min(1.0, 0.4 + 0.1 * len(alloc.node_ids)),
                    description=(
                        f"Job {alloc.job_id} was placed across {len(alloc.node_ids)} nodes "
                        f"({', '.join(alloc.node_ids)}) while {len(single_node_options)} node(s) "
                        f"had {needed} idle GPUs of the requested type."
                    ),
                    affected_job_ids=[alloc.job_id],
                    affected_gpu_ids=alloc.gpu_ids,
                    evidence={
                        "placed_nodes": alloc.node_ids,
                        "needed_gpus": needed,
                        "single_node_options": [c.node_id for c in single_node_options],
                        "nvlink_required": job.constraints.get("nvlink") == "required",
                    },
                )
            )
        return observations


class FragmentationDetector(SignalDetector):
    signal_type = OpportunityType.FRAGMENTATION

    def detect(self, dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> list[Observation]:
        observations: list[Observation] = []
        seen: set[tuple[str, str]] = set()
        # Sample at allocation times of 1-GPU jobs and at queue snapshots.
        checkpoints = [a.start_time for a in dataset.allocations if len(a.gpu_ids) == 1]
        checkpoints += [q.timestamp for q in dataset.queue_snapshots[::2]]
        for ts in checkpoints:
            state = reconstructor.reconstruct(ts)
            pending_8 = [j for j in state.pending_jobs if j.requested_gpus >= 8]
            if not pending_8:
                continue
            stranded_nodes = [
                cap
                for cap in state.available_capacity.by_node.values()
                if 1 <= cap.idle_gpus <= 2
            ]
            nearly_empty = [
                cap
                for cap in state.available_capacity.by_node.values()
                if cap.allocated_gpus == 1 and cap.idle_gpus >= 6
            ]
            if not stranded_nodes and not nearly_empty:
                continue
            key = (pending_8[0].job_id, ",".join(sorted(c.node_id for c in nearly_empty[:4] or stranded_nodes[:4])))
            if key in seen:
                continue
            seen.add(key)
            affected_nodes = nearly_empty or stranded_nodes
            gpu_ids = [gid for cap in affected_nodes for gid in cap.idle_gpu_ids]
            observations.append(
                Observation(
                    observation_id=str(uuid4()),
                    signal_type=self.signal_type,
                    decision=SchedulerDecision(
                        decision_id=f"dec-frag-{pending_8[0].job_id}",
                        timestamp=ts,
                        decision_type=DecisionType.PLACE,
                        job_id=pending_8[0].job_id,
                        chosen_action={"pending_job": pending_8[0].job_id},
                    ),
                    timestamp=ts,
                    severity=min(1.0, 0.3 + 0.05 * len(affected_nodes)),
                    description=(
                        f"{len(affected_nodes)} node(s) had stranded GPU capacity while "
                        f"job {pending_8[0].job_id} waited for {pending_8[0].requested_gpus} GPUs. "
                        f"Largest contiguous block was {state.available_capacity.largest_contiguous_block}."
                    ),
                    affected_job_ids=[pending_8[0].job_id] + [
                        jid
                        for cap in affected_nodes
                        for ns in state.nodes
                        if ns.node.node_id == cap.node_id
                        for jid in ns.running_job_ids
                    ],
                    affected_gpu_ids=gpu_ids,
                    evidence={
                        "pending_8gpu_jobs": [j.job_id for j in pending_8],
                        "stranded_nodes": [c.node_id for c in stranded_nodes],
                        "nearly_empty_nodes": [c.node_id for c in nearly_empty],
                        "largest_contiguous_block": state.available_capacity.largest_contiguous_block,
                        "contiguity_index": state.available_capacity.contiguity_index,
                    },
                )
            )
        return observations


class IdleAllocationDetector(SignalDetector):
    signal_type = OpportunityType.IDLE_ALLOCATION

    def detect(self, dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> list[Observation]:
        observations: list[Observation] = []
        samples_by_job: dict[str, list] = defaultdict(list)
        for sample in dataset.samples:
            if sample.job_id:
                samples_by_job[sample.job_id].append(sample)
        for alloc in dataset.allocations:
            job_samples = samples_by_job.get(alloc.job_id, [])
            if not job_samples:
                continue
            duration = (alloc.end_time or alloc.start_time) - alloc.start_time
            if duration < timedelta(minutes=15):
                continue
            overall = mean(s.gpu_utilization_pct for s in job_samples)
            if overall >= 5.0:
                continue
            observations.append(
                Observation(
                    observation_id=str(uuid4()),
                    signal_type=self.signal_type,
                    decision=_decision_for_job(dataset, alloc.job_id),
                    timestamp=alloc.start_time,
                    severity=min(1.0, 0.5 + (5.0 - overall) / 10.0),
                    description=(
                        f"Job {alloc.job_id} held {len(alloc.gpu_ids)} GPUs for "
                        f"{duration.total_seconds() / 3600:.1f}h with mean utilization {overall:.2f}%."
                    ),
                    affected_job_ids=[alloc.job_id],
                    affected_gpu_ids=alloc.gpu_ids,
                    evidence={
                        "mean_utilization_pct": overall,
                        "duration_seconds": duration.total_seconds(),
                        "allocated_gpus": len(alloc.gpu_ids),
                    },
                )
            )
        return observations


class QueueInefficiencyDetector(SignalDetector):
    signal_type = OpportunityType.QUEUE_INEFFICIENCY

    def detect(self, dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> list[Observation]:
        observations: list[Observation] = []
        jobs_by_id = dataset.job_by_id()
        alloc_by_job = dataset.allocation_by_job()
        for job in dataset.jobs:
            if job.start_time is None or job.submit_time is None:
                continue
            wait = job.start_time - job.submit_time
            if wait < timedelta(minutes=10):
                continue
            state = reconstructor.reconstruct(job.submit_time + timedelta(seconds=1))
            gpu_type = job.requested_gpu_type
            free_matching = 0
            for cap in state.available_capacity.by_node.values():
                if gpu_type is None or cap.gpu_type == gpu_type:
                    free_matching += cap.idle_gpus

            # Also look at running jobs that were holding more GPUs than they used.
            blocking = []
            for running in state.running_jobs:
                alloc = alloc_by_job.get(running.job_id)
                if alloc is None:
                    continue
                samples = [s for s in dataset.samples if s.job_id == running.job_id]
                if not samples:
                    continue
                by_gpu: dict[str, list[float]] = defaultdict(list)
                for sample in samples:
                    if sample.timestamp <= job.start_time:
                        by_gpu[sample.gpu_id].append(sample.gpu_utilization_pct)
                if not by_gpu:
                    continue
                active = sum(1 for vals in by_gpu.values() if mean(vals) > 40.0)
                unused = len(alloc.gpu_ids) - active
                if unused >= job.requested_gpus and (gpu_type is None or running.requested_gpu_type == gpu_type):
                    blocking.append(
                        {
                            "job_id": running.job_id,
                            "allocated": len(alloc.gpu_ids),
                            "active": active,
                            "unused": unused,
                            "priority": running.priority,
                        }
                    )

            if free_matching < job.requested_gpus and not blocking:
                continue
            if blocking and all(b["priority"] >= job.priority for b in blocking) and free_matching < job.requested_gpus:
                # Higher or equal priority holders — weaker signal, still record if unused GPUs exist.
                pass
            observations.append(
                Observation(
                    observation_id=str(uuid4()),
                    signal_type=self.signal_type,
                    decision=SchedulerDecision(
                        decision_id=f"dec-queue-{job.job_id}",
                        timestamp=job.submit_time,
                        decision_type=DecisionType.QUEUE,
                        job_id=job.job_id,
                        chosen_action={"queued_seconds": wait.total_seconds()},
                    ),
                    timestamp=job.submit_time,
                    severity=min(1.0, wait.total_seconds() / 3600.0),
                    description=(
                        f"Job {job.job_id} waited {wait.total_seconds() / 60:.0f} minutes. "
                        + (
                            f"At submit time, {len(blocking)} running job(s) held unused GPUs that could have covered the request."
                            if blocking
                            else f"At submit time, {free_matching} matching GPUs were idle."
                        )
                    ),
                    affected_job_ids=[job.job_id] + [b["job_id"] for b in blocking],
                    affected_gpu_ids=list(alloc_by_job[job.job_id].gpu_ids) if job.job_id in alloc_by_job else [],
                    evidence={
                        "wait_seconds": wait.total_seconds(),
                        "requested_gpus": job.requested_gpus,
                        "idle_matching_gpus": free_matching,
                        "blocking_jobs": blocking,
                        "priority": job.priority,
                    },
                )
            )
        return observations


class DetectorRegistry:
    def __init__(self, detectors: list[SignalDetector] | None = None):
        self.detectors = detectors or [
            OverAllocationDetector(),
            PlacementDetector(),
            FragmentationDetector(),
            IdleAllocationDetector(),
            QueueInefficiencyDetector(),
        ]

    def detect_all(self, dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> list[Observation]:
        observations: list[Observation] = []
        for detector in self.detectors:
            observations.extend(detector.detect(dataset, reconstructor))
        return observations
