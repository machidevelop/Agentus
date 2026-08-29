"""Synthetic cluster observations with injected inefficiencies.

This generator creates what an existing scheduler *actually did*.
It does not encode a preferred alternative policy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from natilah.ingestion.base import DataSource
from natilah.models.database import replace_cluster_data
from natilah.models.domain import (
    GPU_TYPE_CATALOG,
    Allocation,
    ClusterDataset,
    GPU,
    GPUUtilizationSample,
    IngestionResult,
    Job,
    Node,
    QueueSnapshot,
    SchedulerDecision,
    ValidationIssue,
)
from natilah.models.enums import DecisionType, JobState

EPOCH = datetime(2026, 1, 15, tzinfo=timezone.utc)

INJECTED_OVERALLOC = "ml-train-047"
INJECTED_PLACEMENT = "ml-train-split-001"
INJECTED_IDLE = "ml-idle-001"
INJECTED_FRAG_PREFIX = "ml-infer-frag-"
INJECTED_QUEUE_BLOCKER = "ml-queue-blocker-001"
INJECTED_QUEUE_VICTIM = "ml-queue-high-001"
INJECTED_QUEUED_8GPU = "ml-train-8gpu-queued"


class SyntheticDataGenerator(DataSource):
    def __init__(
        self,
        num_nodes: int = 64,
        gpus_per_node: int = 8,
        gpu_types: list[str] | None = None,
        num_jobs: int = 500,
        time_window_hours: int = 24,
        utilization_mean: float = 0.65,
        utilization_stddev: float = 0.20,
        over_alloc_ratio: float = 0.15,
        poor_placement_ratio: float = 0.10,
        sample_interval_minutes: int = 5,
        seed: int = 42,
    ):
        self.num_nodes = num_nodes
        self.gpus_per_node = gpus_per_node
        self.gpu_types = gpu_types or ["A100-80GB", "H100-80GB"]
        self.num_jobs = num_jobs
        self.time_window_hours = time_window_hours
        self.utilization_mean = utilization_mean
        self.utilization_stddev = utilization_stddev
        self.over_alloc_ratio = over_alloc_ratio
        self.poor_placement_ratio = poor_placement_ratio
        self.sample_interval_minutes = sample_interval_minutes
        self.seed = seed
        self._dataset: ClusterDataset | None = None

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if self.num_nodes < 8:
            issues.append(ValidationIssue(field="num_nodes", message="Need at least 8 nodes for injected patterns"))
        if self.gpus_per_node < 8:
            issues.append(ValidationIssue(field="gpus_per_node", message="Need 8 GPUs per node"))
        if self.num_jobs < 20:
            issues.append(ValidationIssue(field="num_jobs", message="Need at least 20 jobs"))
        return issues

    def generate(self) -> ClusterDataset:
        rng = np.random.default_rng(self.seed)
        window = timedelta(hours=self.time_window_hours)
        end_horizon = EPOCH + window

        nodes, gpus = self._build_cluster()
        gpu_by_node: dict[str, list[GPU]] = {}
        for gpu in gpus:
            gpu_by_node.setdefault(gpu.node_id, []).append(gpu)
        for lst in gpu_by_node.values():
            lst.sort(key=lambda g: g.gpu_index)

        jobs: list[Job] = []
        allocations: list[Allocation] = []
        samples: list[GPUUtilizationSample] = []
        decisions: list[SchedulerDecision] = []

        reserved_nodes = self._inject_canonical_patterns(
            rng, nodes, gpu_by_node, jobs, allocations, samples, decisions, end_horizon
        )

        occupancy: dict[str, list[tuple[datetime, datetime, str]]] = {n.node_id: [] for n in nodes}
        for alloc in allocations:
            for node_id in alloc.node_ids:
                occupancy[node_id].append((alloc.start_time, alloc.end_time or end_horizon, alloc.job_id))

        remaining = max(0, self.num_jobs - len(jobs))
        users = ["ml-platform", "research", "inference", "fine-tune", "eval"]
        sizes = [1, 1, 1, 2, 2, 4, 4, 8]
        fill_nodes = [n for n in nodes if n.node_id not in reserved_nodes]

        for i in range(remaining):
            gpu_n = int(rng.choice(sizes))
            duration_h = float(np.clip(rng.normal(2.0, 1.2), 0.4, 8.0))
            submit_offset_h = float(rng.uniform(0.2, max(1.0, self.time_window_hours - duration_h - 0.5)))
            submit = EPOCH + timedelta(hours=submit_offset_h)
            wait_min = float(rng.uniform(0, 25))
            start = submit + timedelta(minutes=wait_min)
            end = start + timedelta(hours=duration_h)
            if end > end_horizon:
                end = end_horizon
            node = fill_nodes[int(rng.integers(0, len(fill_nodes)))]
            gpu_type_name = node.gpu_type.name
            over_alloc = rng.random() < self.over_alloc_ratio and gpu_n >= 4
            split = rng.random() < self.poor_placement_ratio and gpu_n >= 4

            job_id = f"job-{i:04d}"
            job = Job(
                job_id=job_id,
                name=f"{rng.choice(['train', 'infer', 'ft', 'eval'])}-{i:04d}",
                user=str(rng.choice(users)),
                submit_time=submit,
                start_time=start,
                end_time=end,
                state=JobState.COMPLETED,
                requested_gpus=gpu_n,
                requested_gpu_type=gpu_type_name,
                priority=int(rng.integers(1, 10)),
                constraints={},
            )
            node_gpus = gpu_by_node[node.node_id]
            chosen_gpus = [g.gpu_id for g in node_gpus[:gpu_n]]
            node_ids = [node.node_id]
            if split:
                other = fill_nodes[int(rng.integers(0, len(fill_nodes)))]
                if other.node_id != node.node_id and other.gpu_type.name == gpu_type_name:
                    half = max(1, gpu_n // 2)
                    chosen_gpus = [g.gpu_id for g in node_gpus[:half]]
                    chosen_gpus += [g.gpu_id for g in gpu_by_node[other.node_id][: gpu_n - half]]
                    node_ids = [node.node_id, other.node_id]

            alloc = Allocation(
                allocation_id=f"alloc-{job_id}",
                job_id=job_id,
                gpu_ids=chosen_gpus,
                node_ids=node_ids,
                start_time=start,
                end_time=end,
                decision_reason="observed_scheduler_allocation",
            )
            jobs.append(job)
            allocations.append(alloc)
            decisions.append(
                SchedulerDecision(
                    decision_id=f"dec-{job_id}",
                    timestamp=start,
                    decision_type=DecisionType.ALLOCATE,
                    job_id=job_id,
                    chosen_action={
                        "gpu_ids": chosen_gpus,
                        "node_ids": node_ids,
                        "requested_gpus": gpu_n,
                    },
                )
            )
            if wait_min > 5:
                decisions.append(
                    SchedulerDecision(
                        decision_id=f"dec-queue-{job_id}",
                        timestamp=submit,
                        decision_type=DecisionType.QUEUE,
                        job_id=job_id,
                        chosen_action={"queued_seconds": wait_min * 60},
                    )
                )
            samples.extend(
                self._samples_for_allocation(
                    rng, alloc, gpus, over_alloc=over_alloc, idle=False, active_count=max(1, gpu_n // 2) if over_alloc else gpu_n
                )
            )
            for nid in node_ids:
                occupancy[nid].append((start, end, job_id))

        queues = self._queue_snapshots(jobs, allocations, len(gpus), end_horizon)
        self._dataset = ClusterDataset(
            nodes=nodes,
            gpus=gpus,
            jobs=jobs,
            allocations=allocations,
            samples=samples,
            decisions=decisions,
            queue_snapshots=queues,
        )
        return self._dataset

    def _build_cluster(self) -> tuple[list[Node], list[GPU]]:
        nodes: list[Node] = []
        gpus: list[GPU] = []
        half = self.num_nodes // 2
        for i in range(self.num_nodes):
            type_name = self.gpu_types[0] if i < half else self.gpu_types[min(1, len(self.gpu_types) - 1)]
            gpu_type = GPU_TYPE_CATALOG[type_name]
            node_id = f"gpu-node-{i:02d}"
            nodes.append(
                Node(
                    node_id=node_id,
                    hostname=f"{node_id}.cluster.local",
                    gpu_count=self.gpus_per_node,
                    gpu_type=gpu_type,
                    total_memory_gb=gpu_type.memory_gb * self.gpus_per_node,
                    cpu_cores=64,
                    labels={"zone": "a" if i % 2 == 0 else "b", "gpu_type": type_name},
                )
            )
            for idx in range(self.gpus_per_node):
                gpus.append(
                    GPU(
                        gpu_id=f"{node_id}-gpu-{idx}",
                        gpu_type=gpu_type,
                        node_id=node_id,
                        gpu_index=idx,
                    )
                )
        return nodes, gpus

    def _inject_canonical_patterns(
        self,
        rng: np.random.Generator,
        nodes: list[Node],
        gpu_by_node: dict[str, list[GPU]],
        jobs: list[Job],
        allocations: list[Allocation],
        samples: list[GPUUtilizationSample],
        decisions: list[SchedulerDecision],
        end_horizon: datetime,
    ) -> set[str]:
        reserved: set[str] = set()
        a100_nodes = [n for n in nodes if n.gpu_type.name == "A100-80GB"]
        h100_nodes = [n for n in nodes if n.gpu_type.name == "H100-80GB"]
        if len(a100_nodes) < 4 or len(h100_nodes) < 3:
            mid = max(1, len(nodes) // 2)
            a100_nodes = nodes[:mid]
            h100_nodes = nodes[mid:]

        # 1. Over-allocation: 8 GPUs, only ~5 active. Showcase job from the dashboard spec.
        node03 = next((n for n in a100_nodes if n.node_id == "gpu-node-03"), a100_nodes[0])
        reserved.add(node03.node_id)
        start = EPOCH + timedelta(hours=1, minutes=2)
        end = start + timedelta(hours=4, minutes=12)
        gpu_ids = [g.gpu_id for g in gpu_by_node[node03.node_id]]
        self._add_job(
            jobs,
            allocations,
            decisions,
            samples,
            rng,
            job_id=INJECTED_OVERALLOC,
            name="ml-train-047",
            user="research",
            submit=EPOCH + timedelta(hours=1),
            start=start,
            end=end,
            gpus=8,
            gpu_type=node03.gpu_type.name,
            gpu_ids=gpu_ids,
            node_ids=[node03.node_id],
            priority=5,
            over_alloc=True,
            active_count=5,
            constraints={"injected_pattern": "over_allocation"},
        )

        # 2. Poor placement: 8-GPU job split across two H100 nodes while a full node is idle.
        idle_full = h100_nodes[0]
        split_a, split_b = h100_nodes[1], h100_nodes[2]
        reserved.update({idle_full.node_id, split_a.node_id, split_b.node_id})
        p_start = EPOCH + timedelta(hours=3)
        p_end = p_start + timedelta(hours=2, minutes=30)
        split_gpus = [g.gpu_id for g in gpu_by_node[split_a.node_id][:4]] + [
            g.gpu_id for g in gpu_by_node[split_b.node_id][:4]
        ]
        self._add_job(
            jobs,
            allocations,
            decisions,
            samples,
            rng,
            job_id=INJECTED_PLACEMENT,
            name="distributed-pretrain-split",
            user="ml-platform",
            submit=p_start - timedelta(minutes=4),
            start=p_start,
            end=p_end,
            gpus=8,
            gpu_type=idle_full.gpu_type.name,
            gpu_ids=split_gpus,
            node_ids=[split_a.node_id, split_b.node_id],
            priority=6,
            constraints={
                "injected_pattern": "poor_placement",
                "idle_full_node": idle_full.node_id,
                "nvlink": "required",
            },
        )

        # 3. Fragmentation: single-GPU jobs on empty 8-GPU nodes while an 8-GPU job waits.
        # Skip nodes used by other injected patterns (0, 1, 3, 5).
        frag_pool = [n for n in a100_nodes if n.node_id not in {"gpu-node-00", "gpu-node-01", "gpu-node-03", "gpu-node-05"}]
        frag_nodes = frag_pool[:8] if len(frag_pool) >= 8 else frag_pool
        f_start = EPOCH + timedelta(hours=6)
        f_end = f_start + timedelta(hours=3)
        for idx, node in enumerate(frag_nodes):
            reserved.add(node.node_id)
            jid = f"{INJECTED_FRAG_PREFIX}{idx:03d}"
            self._add_job(
                jobs,
                allocations,
                decisions,
                samples,
                rng,
                job_id=jid,
                name=f"single-gpu-infer-{idx}",
                user="inference",
                submit=f_start - timedelta(minutes=2),
                start=f_start,
                end=f_end,
                gpus=1,
                gpu_type=node.gpu_type.name,
                gpu_ids=[gpu_by_node[node.node_id][0].gpu_id],
                node_ids=[node.node_id],
                priority=3,
                constraints={"injected_pattern": "fragmentation"},
            )
        q_submit = f_start + timedelta(minutes=10)
        q_start = f_start + timedelta(hours=3, minutes=5)
        q_end = min(q_start + timedelta(hours=2), end_horizon)
        # The 8-GPU job is queued during the fragmentation window; it starts after singles end.
        queued_node = frag_nodes[0]
        self._add_job(
            jobs,
            allocations,
            decisions,
            samples,
            rng,
            job_id=INJECTED_QUEUED_8GPU,
            name="full-node-train-queued",
            user="research",
            submit=q_submit,
            start=q_start,
            end=q_end,
            gpus=8,
            gpu_type=queued_node.gpu_type.name,
            gpu_ids=[g.gpu_id for g in gpu_by_node[queued_node.node_id]],
            node_ids=[queued_node.node_id],
            priority=8,
            constraints={"injected_pattern": "fragmentation_queued"},
        )
        decisions.append(
            SchedulerDecision(
                decision_id=f"dec-queue-{INJECTED_QUEUED_8GPU}",
                timestamp=q_submit,
                decision_type=DecisionType.QUEUE,
                job_id=INJECTED_QUEUED_8GPU,
                chosen_action={"queued_seconds": (q_start - q_submit).total_seconds()},
            )
        )

        # 4. Idle allocation: 4 GPUs held ~3h at <5% utilization.
        idle_node = next((n for n in a100_nodes if n.node_id == "gpu-node-05"), a100_nodes[-1])
        reserved.add(idle_node.node_id)
        i_start = EPOCH + timedelta(hours=8)
        i_end = i_start + timedelta(hours=3)
        idle_gpus = [g.gpu_id for g in gpu_by_node[idle_node.node_id][:4]]
        self._add_job(
            jobs,
            allocations,
            decisions,
            samples,
            rng,
            job_id=INJECTED_IDLE,
            name="stalled-dataloader-job",
            user="research",
            submit=i_start - timedelta(minutes=3),
            start=i_start,
            end=i_end,
            gpus=4,
            gpu_type=idle_node.gpu_type.name,
            gpu_ids=idle_gpus,
            node_ids=[idle_node.node_id],
            priority=4,
            idle=True,
            constraints={"injected_pattern": "idle_allocation"},
        )

        # 5. Queue cascade: low-priority over-allocation blocks a high-priority 4-GPU job for 45 min.
        block_node = next((n for n in a100_nodes if n.node_id == "gpu-node-00"), a100_nodes[0])
        reserved.add(block_node.node_id)
        b_start = EPOCH + timedelta(hours=12)
        b_end = b_start + timedelta(hours=2)
        blocker_gpus = [g.gpu_id for g in gpu_by_node[block_node.node_id]]
        self._add_job(
            jobs,
            allocations,
            decisions,
            samples,
            rng,
            job_id=INJECTED_QUEUE_BLOCKER,
            name="low-priority-wide-train",
            user="eval",
            submit=b_start - timedelta(minutes=1),
            start=b_start,
            end=b_end,
            gpus=8,
            gpu_type=block_node.gpu_type.name,
            gpu_ids=blocker_gpus,
            node_ids=[block_node.node_id],
            priority=2,
            over_alloc=True,
            active_count=4,
            constraints={"injected_pattern": "queue_blocker"},
        )
        v_submit = b_start + timedelta(minutes=2)
        v_start = b_start + timedelta(minutes=47)
        v_end = v_start + timedelta(hours=1, minutes=20)
        # Victim eventually runs on a different node. The observation is that it waited
        # 45 minutes while 4 of the blocker's GPUs sat unused on node-00.
        victim_node = next((n for n in a100_nodes if n.node_id == "gpu-node-01"), a100_nodes[min(1, len(a100_nodes) - 1)])
        reserved.add(victim_node.node_id)
        self._add_job(
            jobs,
            allocations,
            decisions,
            samples,
            rng,
            job_id=INJECTED_QUEUE_VICTIM,
            name="high-priority-finetune",
            user="ml-platform",
            submit=v_submit,
            start=v_start,
            end=v_end,
            gpus=4,
            gpu_type=victim_node.gpu_type.name,
            gpu_ids=[g.gpu_id for g in gpu_by_node[victim_node.node_id][:4]],
            node_ids=[victim_node.node_id],
            priority=9,
            constraints={"injected_pattern": "queue_victim", "blocked_by": INJECTED_QUEUE_BLOCKER},
        )
        decisions.append(
            SchedulerDecision(
                decision_id=f"dec-queue-{INJECTED_QUEUE_VICTIM}",
                timestamp=v_submit,
                decision_type=DecisionType.QUEUE,
                job_id=INJECTED_QUEUE_VICTIM,
                chosen_action={"queued_seconds": (v_start - v_submit).total_seconds()},
            )
        )
        return reserved

    def _add_job(
        self,
        jobs: list[Job],
        allocations: list[Allocation],
        decisions: list[SchedulerDecision],
        samples: list[GPUUtilizationSample],
        rng: np.random.Generator,
        *,
        job_id: str,
        name: str,
        user: str,
        submit: datetime,
        start: datetime,
        end: datetime,
        gpus: int,
        gpu_type: str,
        gpu_ids: list[str],
        node_ids: list[str],
        priority: int,
        constraints: dict[str, str],
        over_alloc: bool = False,
        idle: bool = False,
        active_count: int | None = None,
    ) -> None:
        jobs.append(
            Job(
                job_id=job_id,
                name=name,
                user=user,
                submit_time=submit,
                start_time=start,
                end_time=end,
                state=JobState.COMPLETED,
                requested_gpus=gpus,
                requested_gpu_type=gpu_type,
                priority=priority,
                constraints=constraints,
            )
        )
        alloc = Allocation(
            allocation_id=f"alloc-{job_id}",
            job_id=job_id,
            gpu_ids=gpu_ids,
            node_ids=node_ids,
            start_time=start,
            end_time=end,
            decision_reason="observed_scheduler_allocation",
        )
        allocations.append(alloc)
        decisions.append(
            SchedulerDecision(
                decision_id=f"dec-{job_id}",
                timestamp=start,
                decision_type=DecisionType.ALLOCATE,
                job_id=job_id,
                chosen_action={
                    "gpu_ids": gpu_ids,
                    "node_ids": node_ids,
                    "requested_gpus": gpus,
                },
            )
        )
        gpu_objs = [
            GPU(gpu_id=gid, gpu_type=GPU_TYPE_CATALOG[gpu_type], node_id=gid.rsplit("-gpu-", 1)[0], gpu_index=0)
            for gid in gpu_ids
        ]
        samples.extend(
            self._samples_for_allocation(
                rng,
                alloc,
                gpu_objs,
                over_alloc=over_alloc,
                idle=idle,
                active_count=active_count or gpus,
            )
        )

    def _samples_for_allocation(
        self,
        rng: np.random.Generator,
        alloc: Allocation,
        gpus: list[GPU],
        *,
        over_alloc: bool,
        idle: bool,
        active_count: int,
    ) -> list[GPUUtilizationSample]:
        gpu_lookup = {g.gpu_id: g for g in gpus}
        interval = timedelta(minutes=self.sample_interval_minutes)
        t = alloc.start_time
        end = alloc.end_time or (alloc.start_time + timedelta(hours=1))
        out: list[GPUUtilizationSample] = []
        active_ids = set(alloc.gpu_ids[:active_count])
        while t < end:
            for gid in alloc.gpu_ids:
                gpu = gpu_lookup.get(gid)
                mem = gpu.gpu_type.memory_gb if gpu else 80.0
                if idle:
                    util = float(np.clip(rng.normal(0.03, 0.01), 0.005, 0.049)) * 100
                    mem_pct = float(np.clip(rng.normal(0.04, 0.01), 0.01, 0.08)) * 100
                elif over_alloc and gid not in active_ids:
                    util = float(np.clip(rng.normal(0.02, 0.008), 0.0, 0.03)) * 100
                    mem_pct = float(np.clip(rng.normal(0.03, 0.01), 0.01, 0.08)) * 100
                else:
                    util = float(np.clip(rng.normal(self.utilization_mean, self.utilization_stddev), 0.15, 0.98)) * 100
                    mem_pct = float(np.clip(rng.normal(0.55, 0.12), 0.10, 0.95)) * 100
                out.append(
                    GPUUtilizationSample(
                        gpu_id=gid,
                        timestamp=t,
                        gpu_utilization_pct=util,
                        memory_utilization_pct=mem_pct,
                        memory_used_gb=mem * (mem_pct / 100.0),
                        power_watts=(gpu.gpu_type.tdp_watts * (0.2 + 0.7 * util / 100.0)) if gpu else None,
                        job_id=alloc.job_id,
                    )
                )
            t += interval
        return out

    def _queue_snapshots(
        self,
        jobs: list[Job],
        allocations: list[Allocation],
        total_gpus: int,
        end_horizon: datetime,
    ) -> list[QueueSnapshot]:
        snapshots: list[QueueSnapshot] = []
        t = EPOCH
        step = timedelta(minutes=15)
        alloc_by_job = {a.job_id: a for a in allocations}
        while t <= end_horizon:
            pending: list[str] = []
            running: list[str] = []
            allocated = 0
            for job in jobs:
                if job.submit_time <= t and (job.start_time is None or job.start_time > t):
                    pending.append(job.job_id)
                elif job.start_time and job.start_time <= t and (job.end_time is None or job.end_time > t):
                    running.append(job.job_id)
                    alloc = alloc_by_job.get(job.job_id)
                    if alloc:
                        allocated += len(alloc.gpu_ids)
            snapshots.append(
                QueueSnapshot(
                    timestamp=t,
                    pending_jobs=pending,
                    running_jobs=running,
                    total_gpus=total_gpus,
                    allocated_gpus=allocated,
                    idle_gpus=max(0, total_gpus - allocated),
                )
            )
            t += step
        return snapshots

    async def ingest(self, db: AsyncSession) -> IngestionResult:
        issues = self.validate()
        if issues:
            raise ValueError("; ".join(f"{i.field}: {i.message}" for i in issues))
        dataset = self.generate()
        await replace_cluster_data(db, dataset)
        return IngestionResult(
            nodes=len(dataset.nodes),
            gpus=len(dataset.gpus),
            jobs=len(dataset.jobs),
            allocations=len(dataset.allocations),
            samples=len(dataset.samples),
            decisions=len(dataset.decisions),
            source="synthetic",
        )
