"""Point-in-time reconstruction of observed cluster state. Read-only."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
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
    # Four agents and five detectors ask for the same instants repeatedly, and a
    # snapshot costs a pass over every node and GPU, so recent ones are kept.
    CACHE_SIZE = 256

    def __init__(self, dataset: ClusterDataset, cache_size: int | None = None):
        self.dataset = dataset
        self._cache: OrderedDict[datetime, ClusterStateSnapshot] = OrderedDict()
        self._cache_size = self.CACHE_SIZE if cache_size is None else cache_size
        self.jobs_by_id = dataset.job_by_id()
        self.gpus_by_id = dataset.gpu_by_id()
        self.nodes_by_id = dataset.node_by_id()
        self.gpus_by_node: dict[str, list[GPU]] = defaultdict(list)
        for gpu in dataset.gpus:
            self.gpus_by_node[gpu.node_id].append(gpu)
        for node_id in self.gpus_by_node:
            self.gpus_by_node[node_id].sort(key=lambda g: g.gpu_index)
        # Plain id lists: capacity is recomputed per snapshot and attribute
        # access on thousands of GPU models is the bulk of that cost.
        self.gpu_ids_by_node: dict[str, list[str]] = {
            node_id: [gpu.gpu_id for gpu in gpus] for node_id, gpus in self.gpus_by_node.items()
        }
        self.allocations = list(dataset.allocations)
        self._samples_by_gpu: dict[str, list] = defaultdict(list)
        for sample in dataset.samples:
            self._samples_by_gpu[sample.gpu_id].append(sample)
        for gpu_id in self._samples_by_gpu:
            self._samples_by_gpu[gpu_id].sort(key=lambda s: s.timestamp)

    def reconstruct(self, timestamp: datetime) -> ClusterStateSnapshot:
        cached = self._cache.get(timestamp)
        if cached is not None:
            self._cache.move_to_end(timestamp)
            return cached
        snapshot = self._reconstruct_uncached(timestamp)
        if self._cache_size > 0:
            self._cache[timestamp] = snapshot
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return snapshot

    def _reconstruct_uncached(self, timestamp: datetime) -> ClusterStateSnapshot:
        active = [a for a in self.allocations if self._active_at(a, timestamp)]
        gpu_to_job: dict[str, str | None] = {gpu.gpu_id: None for gpu in self.dataset.gpus}
        job_ids_running: set[str] = set()
        for alloc in active:
            job_ids_running.add(alloc.job_id)
            for gid in alloc.gpu_ids:
                gpu_to_job[gid] = alloc.job_id

        running_jobs = [
            self.jobs_by_id[jid] for jid in sorted(job_ids_running) if jid in self.jobs_by_id
        ]
        pending_jobs = [
            job
            for job in self.dataset.jobs
            if job.submit_time <= timestamp and (job.start_time is None or job.start_time > timestamp)
        ]
        idle_gpus = [gid for gid, jid in gpu_to_job.items() if jid is None]
        capacity = self._capacity_map(gpu_to_job)
        # Every input here is already a validated model; re-validating the whole
        # cluster on each snapshot is the single most expensive thing analysis does.
        snapshot = ClusterStateSnapshot.model_construct(
            timestamp=timestamp,
            nodes=[],
            running_jobs=running_jobs,
            pending_jobs=pending_jobs,
            gpu_allocations=gpu_to_job,
            idle_gpus=idle_gpus,
            available_capacity=capacity,
        )
        snapshot._node_builder = self._node_states
        return snapshot

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

        lcb = 0
        for node in self.dataset.nodes:
            gpu_ids = self.gpu_ids_by_node.get(node.node_id, [])
            idle_ids = [gid for gid in gpu_ids if gpu_to_job.get(gid) is None]
            total_n = len(gpu_ids)
            idle_n = len(idle_ids)
            alloc_n = total_n - idle_n
            idle_total += idle_n
            allocated_total += alloc_n
            by_type[node.gpu_type.name] += idle_n
            by_node[node.node_id] = NodeCapacity.model_construct(
                node_id=node.node_id,
                total_gpus=total_n,
                allocated_gpus=alloc_n,
                idle_gpus=idle_n,
                gpu_type=node.gpu_type.name,
                idle_gpu_ids=idle_ids,
            )
            if idle_n:
                if idle_n > lcb:
                    lcb = idle_n
                contig_numer += idle_n**2
                contig_denom += idle_n * max(total_n, 1)

        contiguity = (contig_numer / contig_denom) if contig_denom else 1.0
        capacity = CapacityMap.model_construct(
            total_gpus=len(self.dataset.gpus),
            allocated_gpus=allocated_total,
            idle_gpus=idle_total,
            by_node=by_node,
            by_gpu_type=dict(by_type),
            contiguous_blocks=blocks,
            contiguity_index=contiguity,
            largest_contiguous_block=lcb,
        )
        capacity._block_builder = lambda: self._blocks(by_node)
        return capacity

    @staticmethod
    def _blocks(by_node: dict[str, NodeCapacity]) -> list[Block]:
        blocks = [
            Block.model_construct(
                node_id=cap.node_id,
                gpu_ids=cap.idle_gpu_ids,
                size=cap.idle_gpus,
                clique_type=_clique_type(cap.idle_gpus),
            )
            for cap in by_node.values()
            if cap.idle_gpus
        ]
        blocks.sort(key=lambda b: b.size, reverse=True)
        return blocks

    def _node_states(self, gpu_to_job: dict[str, str | None]) -> list[NodeState]:
        states: list[NodeState] = []
        for node in self.dataset.nodes:
            node_gpus = self.gpus_by_node.get(node.node_id, [])
            allocated = [g.gpu_id for g in node_gpus if gpu_to_job.get(g.gpu_id)]
            idle = [g.gpu_id for g in node_gpus if gpu_to_job.get(g.gpu_id) is None]
            running = sorted({gpu_to_job[gid] for gid in allocated if gpu_to_job.get(gid)})
            states.append(
                NodeState.model_construct(
                    node=node,
                    gpus=node_gpus,
                    allocated_gpu_ids=allocated,
                    idle_gpu_ids=idle,
                    running_job_ids=[jid for jid in running if jid],
                )
            )
        return states
