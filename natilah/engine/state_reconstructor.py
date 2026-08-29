"""Point-in-time reconstruction of observed cluster state. Read-only."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from natilah.models.domain import (
    Allocation,
    Block,
    CapacityMap,
    ClusterDataset,
    ClusterStateSnapshot,
    GPU,
    Job,
    Node,
    NodeCapacity,
    NodeState,
)


def _clique_type(size: int) -> str:
    if size >= 8:
        return "full8"
    if size >= 4:
        return "quad4"
    if size >= 2:
        return "pair2"
    return "single"


class ClusterStateReconstructor:
    def __init__(self, dataset: ClusterDataset):
        self.dataset = dataset
        self.jobs_by_id = dataset.job_by_id()
        self.gpus_by_id = dataset.gpu_by_id()
        self.nodes_by_id = dataset.node_by_id()
        self.gpus_by_node: dict[str, list[GPU]] = defaultdict(list)
        for gpu in dataset.gpus:
            self.gpus_by_node[gpu.node_id].append(gpu)
        for node_id in self.gpus_by_node:
            self.gpus_by_node[node_id].sort(key=lambda g: g.gpu_index)
        self.allocations = list(dataset.allocations)
        self._samples_by_gpu: dict[str, list] = defaultdict(list)
        for sample in dataset.samples:
            self._samples_by_gpu[sample.gpu_id].append(sample)
        for gpu_id in self._samples_by_gpu:
            self._samples_by_gpu[gpu_id].sort(key=lambda s: s.timestamp)

    def reconstruct(self, timestamp: datetime) -> ClusterStateSnapshot:
        active = [a for a in self.allocations if self._active_at(a, timestamp)]
        gpu_to_job: dict[str, str | None] = {gpu.gpu_id: None for gpu in self.dataset.gpus}
        job_ids_running: set[str] = set()
        for alloc in active:
            job_ids_running.add(alloc.job_id)
            for gid in alloc.gpu_ids:
                gpu_to_job[gid] = alloc.job_id

        running_jobs = [self.jobs_by_id[jid] for jid in job_ids_running if jid in self.jobs_by_id]
        pending_jobs = [
            job
            for job in self.dataset.jobs
            if job.submit_time <= timestamp and (job.start_time is None or job.start_time > timestamp)
        ]
        idle_gpus = [gid for gid, jid in gpu_to_job.items() if jid is None]
        capacity = self._capacity_map(gpu_to_job)
        node_states = self._node_states(gpu_to_job)
        return ClusterStateSnapshot(
            timestamp=timestamp,
            nodes=node_states,
            running_jobs=running_jobs,
            pending_jobs=pending_jobs,
            gpu_allocations=gpu_to_job,
            idle_gpus=idle_gpus,
            available_capacity=capacity,
        )

    def materialize_snapshots(self, interval_minutes: int = 5) -> list[ClusterStateSnapshot]:
        if not self.dataset.jobs:
            return []
        start = min(j.submit_time for j in self.dataset.jobs)
        end = max((j.end_time or j.submit_time) for j in self.dataset.jobs)
        snapshots: list[ClusterStateSnapshot] = []
        t = start
        step = timedelta(minutes=interval_minutes)
        while t <= end:
            snapshots.append(self.reconstruct(t))
            t += step
        return snapshots

    def latest_utilization(self, gpu_id: str, timestamp: datetime) -> float | None:
        samples = self._samples_by_gpu.get(gpu_id, [])
        latest = None
        for sample in samples:
            if sample.timestamp <= timestamp:
                latest = sample.gpu_utilization_pct
            else:
                break
        return latest

    def samples_for_job(self, job_id: str) -> list:
        return [s for s in self.dataset.samples if s.job_id == job_id]

    def allocation_for_job(self, job_id: str) -> Allocation | None:
        for alloc in self.allocations:
            if alloc.job_id == job_id:
                return alloc
        return None

    @staticmethod
    def _active_at(alloc: Allocation, timestamp: datetime) -> bool:
        if alloc.start_time > timestamp:
            return False
        if alloc.end_time is None:
            return True
        return alloc.end_time > timestamp

    def _capacity_map(self, gpu_to_job: dict[str, str | None]) -> CapacityMap:
        by_node: dict[str, NodeCapacity] = {}
        by_type: dict[str, int] = defaultdict(int)
        blocks: list[Block] = []
        idle_total = 0
        allocated_total = 0
        contig_numer = 0.0
        contig_denom = 0.0

        for node in self.dataset.nodes:
            node_gpus = self.gpus_by_node.get(node.node_id, [])
            idle_ids = [g.gpu_id for g in node_gpus if gpu_to_job.get(g.gpu_id) is None]
            alloc_n = len(node_gpus) - len(idle_ids)
            idle_total += len(idle_ids)
            allocated_total += alloc_n
            by_type[node.gpu_type.name] += len(idle_ids)
            by_node[node.node_id] = NodeCapacity(
                node_id=node.node_id,
                total_gpus=len(node_gpus),
                allocated_gpus=alloc_n,
                idle_gpus=len(idle_ids),
                gpu_type=node.gpu_type.name,
                idle_gpu_ids=idle_ids,
            )
            if idle_ids:
                blocks.append(
                    Block(
                        node_id=node.node_id,
                        gpu_ids=idle_ids,
                        size=len(idle_ids),
                        clique_type=_clique_type(len(idle_ids)),
                    )
                )
                contig_numer += len(idle_ids) ** 2
                contig_denom += len(idle_ids) * max(len(node_gpus), 1)

        lcb = max((b.size for b in blocks), default=0)
        contiguity = (contig_numer / contig_denom) if contig_denom else 1.0
        blocks.sort(key=lambda b: b.size, reverse=True)
        return CapacityMap(
            total_gpus=len(self.dataset.gpus),
            allocated_gpus=allocated_total,
            idle_gpus=idle_total,
            by_node=by_node,
            by_gpu_type=dict(by_type),
            contiguous_blocks=blocks,
            contiguity_index=contiguity,
            largest_contiguous_block=lcb,
        )

    def _node_states(self, gpu_to_job: dict[str, str | None]) -> list[NodeState]:
        states: list[NodeState] = []
        for node in self.dataset.nodes:
            node_gpus = self.gpus_by_node.get(node.node_id, [])
            allocated = [g.gpu_id for g in node_gpus if gpu_to_job.get(g.gpu_id)]
            idle = [g.gpu_id for g in node_gpus if gpu_to_job.get(g.gpu_id) is None]
            running = sorted({gpu_to_job[gid] for gid in allocated if gpu_to_job.get(gid)})
            states.append(
                NodeState(
                    node=node,
                    gpus=node_gpus,
                    allocated_gpu_ids=allocated,
                    idle_gpu_ids=idle,
                    running_job_ids=[jid for jid in running if jid],
                )
            )
        return states
