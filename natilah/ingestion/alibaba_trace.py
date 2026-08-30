"""Alibaba GPU Cluster Trace ingestion connectors.

Supports two trace formats:
  - OpenB 2023 (ATC '23): Kubernetes scheduler trace with node specs + pod lists.
    No placement or utilization data — connector simulates placement and synthesizes
    utilization for end-to-end pipeline validation.
  - v2026 (OSDI '26): Full execution trace with hourly pod/server data in Parquet.
    Has real placement (server_id), real utilization (avg_gpu_sm_util), and
    scheduling delays. Requires pyarrow.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from natilah.models.domain import (
    ALIBABA_GPU_ALIASES,
    Allocation,
    ClusterDataset,
    GPU,
    GPUType,
    GPUUtilizationSample,
    Job,
    Node,
    QueueSnapshot,
    SchedulerDecision,
    resolve_gpu_type,
)
from natilah.models.enums import DecisionType, JobState

logger = logging.getLogger(__name__)

OPENB_GPU_MAP: dict[str, str] = {
    "P100": "P100-16GB",
    "T4": "T4-16GB",
    "V100M16": "V100-16GB",
    "V100M32": "V100-32GB",
    "A10": "A10-24GB",
    "G2": "A100-40GB",
    "G3": "A100-80GB",
}

OPENB_PHASE_MAP: dict[str, JobState] = {
    "Running": JobState.RUNNING,
    "Succeeded": JobState.COMPLETED,
    "Failed": JobState.FAILED,
    "Pending": JobState.PENDING,
}


def _int_or(val: Any, default: int = 0) -> int:
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _float_or(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ---- Trace epoch anchor: 2023-01-01 UTC (arbitrary, for readable timestamps)
_EPOCH_ANCHOR = datetime(2023, 1, 1, tzinfo=timezone.utc)


def _relative_to_dt(seconds: float) -> datetime:
    return _EPOCH_ANCHOR + timedelta(seconds=seconds)


# ===========================================================================
# OpenB 2023 connector
# ===========================================================================

class OpenB2023Config:
    def __init__(
        self,
        trace_dir: str,
        *,
        pod_file: str = "openb_pod_list_default.csv",
        node_file: str = "openb_node_list_gpu_node.csv",
        time_window_hours: float | None = None,
        max_jobs: int | None = None,
        start_offset_hours: float = 0.0,
        gpu_type_filter: str | None = None,
        include_zero_gpu: bool = False,
    ):
        self.trace_dir = trace_dir
        self.pod_file = pod_file
        self.node_file = node_file
        self.time_window_hours = time_window_hours
        self.max_jobs = max_jobs
        self.start_offset_hours = start_offset_hours
        self.gpu_type_filter = gpu_type_filter
        self.include_zero_gpu = include_zero_gpu


class OpenB2023Connector:
    """Converts OpenB 2023 CSVs into a Natilah ClusterDataset.

    Since the trace has no placement or utilization data, this connector:
    1. Builds nodes/GPUs from the node spec CSV.
    2. Builds jobs from the pod CSV (creation/scheduled/deletion times).
    3. Simulates placement using first-fit decreasing by GPU count.
    4. Synthesizes utilization samples based on job duration heuristics.
    """

    def __init__(self, config: OpenB2023Config):
        self.config = config

    def load(self) -> ClusterDataset:
        logger.info("Loading OpenB 2023 trace from %s", self.config.trace_dir)
        nodes = self._load_nodes()
        gpus = self._build_gpus(nodes)
        raw_jobs = self._load_pods()
        jobs = self._filter_jobs(raw_jobs)
        allocations = self._simulate_placement(jobs, nodes, gpus)
        samples = self._synthesize_utilization(allocations)
        decisions = self._build_decisions(jobs, allocations)
        queue_snapshots = self._build_queue_snapshots(jobs, nodes)

        dataset = ClusterDataset(
            nodes=nodes, gpus=gpus, jobs=jobs,
            allocations=allocations, samples=samples,
            decisions=decisions, queue_snapshots=queue_snapshots,
        )
        logger.info(
            "Loaded: %d nodes, %d GPUs, %d jobs, %d allocs, %d samples, %d queue snaps",
            len(nodes), len(gpus), len(jobs), len(allocations),
            len(samples), len(queue_snapshots),
        )
        return dataset

    def _load_nodes(self) -> list[Node]:
        path = Path(self.config.trace_dir) / self.config.node_file
        nodes: list[Node] = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                sn = row["sn"]
                model = row.get("model", "T4")
                gpu_count = _int_or(row.get("gpu"), 1)
                if gpu_count == 0:
                    continue
                if self.config.gpu_type_filter:
                    mapped = OPENB_GPU_MAP.get(model, model)
                    target = OPENB_GPU_MAP.get(self.config.gpu_type_filter, self.config.gpu_type_filter)
                    if mapped != target:
                        continue
                gpu_type_name = OPENB_GPU_MAP.get(model, "T4-16GB")
                gpu_type = resolve_gpu_type(gpu_type_name)
                mem_mib = _float_or(row.get("memory_mib"), 262144)
                cpu_milli = _int_or(row.get("cpu_milli"), 64000)
                nodes.append(Node(
                    node_id=sn,
                    hostname=sn,
                    gpu_count=gpu_count,
                    gpu_type=gpu_type,
                    total_memory_gb=mem_mib / 1024,
                    cpu_cores=cpu_milli // 1000,
                ))
        logger.info("Loaded %d GPU nodes", len(nodes))
        return nodes

    def _build_gpus(self, nodes: list[Node]) -> list[GPU]:
        gpus: list[GPU] = []
        for node in nodes:
            for i in range(node.gpu_count):
                gpus.append(GPU(
                    gpu_id=f"{node.node_id}-gpu-{i}",
                    gpu_type=node.gpu_type,
                    node_id=node.node_id,
                    gpu_index=i,
                ))
        return gpus

    def _load_pods(self) -> list[Job]:
        path = Path(self.config.trace_dir) / self.config.pod_file
        jobs: list[Job] = []
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                num_gpu = _int_or(row.get("num_gpu"), 0)
                if num_gpu == 0 and not self.config.include_zero_gpu:
                    continue

                name = row["name"]
                creation = _float_or(row.get("creation_time"), 0)
                scheduled = _float_or(row.get("scheduled_time"), 0)
                deletion = _float_or(row.get("deletion_time"), 0)

                submit_time = _relative_to_dt(creation)
                has_scheduled = row.get("scheduled_time", "") not in ("", None)
                start_time = _relative_to_dt(scheduled) if has_scheduled else None
                end_time = _relative_to_dt(deletion) if deletion > 0 else None

                if start_time and start_time < submit_time:
                    start_time = submit_time

                phase = row.get("pod_phase", "Running")
                state = OPENB_PHASE_MAP.get(phase, JobState.COMPLETED)

                gpu_spec = row.get("gpu_spec", "")
                requested_type = None
                if gpu_spec and gpu_spec != "nan":
                    first_spec = gpu_spec.split("|")[0].strip()
                    requested_type = OPENB_GPU_MAP.get(first_spec, first_spec)

                qos = row.get("qos", "")
                priority = {"LS": 100, "BE": 10, "Burstable": 50}.get(qos, 50)

                constraints: dict[str, str] = {}
                if qos:
                    constraints["qos"] = qos
                gpu_milli = _int_or(row.get("gpu_milli"), 1000)
                if gpu_milli < 1000 and num_gpu == 1:
                    constraints["gpu_share"] = str(gpu_milli)
                cpu_milli = _int_or(row.get("cpu_milli"), 0)
                mem_mib = _int_or(row.get("memory_mib"), 0)
                if cpu_milli > 0:
                    constraints["min_cpu"] = str(cpu_milli / 1000)
                if mem_mib > 0:
                    constraints["min_memory_gb"] = str(mem_mib / 1024)

                jobs.append(Job(
                    job_id=name,
                    name=name,
                    user=f"user-{hashlib.md5(name.encode()).hexdigest()[:6]}",
                    submit_time=submit_time,
                    start_time=start_time,
                    end_time=end_time,
                    state=state,
                    requested_gpus=max(num_gpu, 1),
                    requested_gpu_type=requested_type,
                    priority=priority,
                    constraints=constraints,
                ))
        logger.info("Loaded %d GPU pods", len(jobs))
        return jobs

    def _filter_jobs(self, jobs: list[Job]) -> list[Job]:
        if not jobs:
            return jobs

        offset_s = self.config.start_offset_hours * 3600
        window_start = _EPOCH_ANCHOR + timedelta(seconds=offset_s)

        if self.config.time_window_hours:
            window_end = window_start + timedelta(hours=self.config.time_window_hours)
        else:
            window_end = max(j.end_time or j.submit_time for j in jobs) + timedelta(hours=1)

        filtered = [
            j for j in jobs
            if j.submit_time < window_end
            and (j.end_time is None or j.end_time > window_start)
        ]

        if self.config.max_jobs and len(filtered) > self.config.max_jobs:
            filtered.sort(key=lambda j: j.submit_time)
            filtered = filtered[: self.config.max_jobs]

        logger.info("After filtering: %d jobs (window: %s to %s)", len(filtered), window_start, window_end)
        return filtered

    def _simulate_placement(
        self, jobs: list[Job], nodes: list[Node], gpus: list[GPU],
    ) -> list[Allocation]:
        """First-fit placement simulator.

        Assigns each job to the first node that has enough idle GPUs of
        the right type at the job's start time. If no single node fits,
        spreads across multiple nodes (creating fragmentation opportunities
        for Natilah to detect).
        """
        gpus_by_node: dict[str, list[GPU]] = defaultdict(list)
        for g in gpus:
            gpus_by_node[g.node_id].append(g)
        for nid in gpus_by_node:
            gpus_by_node[nid].sort(key=lambda g: g.gpu_index)

        gpu_free_at: dict[str, float] = {g.gpu_id: 0.0 for g in gpus}
        node_type: dict[str, str] = {n.node_id: n.gpu_type.name for n in nodes}

        scheduled = [j for j in jobs if j.start_time is not None]
        scheduled.sort(key=lambda j: j.start_time)

        allocations: list[Allocation] = []

        for job in scheduled:
            needed = job.requested_gpus
            start_ts = job.start_time.timestamp()
            end_ts = (job.end_time or (job.start_time + timedelta(hours=1))).timestamp()

            assigned_gpus: list[str] = []
            assigned_nodes: list[str] = []

            sorted_nodes = sorted(nodes, key=lambda n: len(gpus_by_node.get(n.node_id, [])), reverse=True)

            for node in sorted_nodes:
                if job.requested_gpu_type and node_type[node.node_id] != job.requested_gpu_type:
                    continue
                nid = node.node_id
                node_gpus = gpus_by_node.get(nid, [])
                free = [g for g in node_gpus if gpu_free_at[g.gpu_id] <= start_ts]
                take = min(len(free), needed - len(assigned_gpus))
                if take <= 0:
                    continue
                for g in free[:take]:
                    assigned_gpus.append(g.gpu_id)
                    gpu_free_at[g.gpu_id] = end_ts
                if nid not in assigned_nodes:
                    assigned_nodes.append(nid)
                if len(assigned_gpus) >= needed:
                    break

            if not assigned_gpus:
                continue

            intentional_fragmentation = False
            h = int(hashlib.md5(job.job_id.encode()).hexdigest()[:4], 16)
            if needed >= 2 and len(assigned_nodes) == 1 and h % 5 == 0:
                other_nodes = [
                    n for n in nodes
                    if n.node_id != assigned_nodes[0]
                    and gpu_type_matches(job.requested_gpu_type, node_type[n.node_id])
                ]
                if other_nodes and len(gpus_by_node.get(other_nodes[0].node_id, [])) > 0:
                    split_node = other_nodes[h % len(other_nodes)]
                    split_gpus = gpus_by_node.get(split_node.node_id, [])
                    free_on_split = [g for g in split_gpus if gpu_free_at[g.gpu_id] <= start_ts]
                    if free_on_split and len(assigned_gpus) >= 2:
                        old_gpu = assigned_gpus[-1]
                        gpu_free_at[old_gpu] = gpu_free_at.get(old_gpu, 0)
                        replacement = free_on_split[0]
                        assigned_gpus[-1] = replacement.gpu_id
                        gpu_free_at[replacement.gpu_id] = end_ts
                        if split_node.node_id not in assigned_nodes:
                            assigned_nodes.append(split_node.node_id)
                        intentional_fragmentation = True

            allocations.append(Allocation(
                allocation_id=f"alloc-{job.job_id}",
                job_id=job.job_id,
                gpu_ids=assigned_gpus,
                node_ids=assigned_nodes,
                start_time=job.start_time,
                end_time=job.end_time,
                decision_reason="simulated:first_fit" + (":fragmented" if intentional_fragmentation else ""),
            ))

        logger.info("Simulated %d allocations (%d multi-node)",
                     len(allocations),
                     sum(1 for a in allocations if len(a.node_ids) > 1))
        return allocations

    def _synthesize_utilization(self, allocations: list[Allocation]) -> list[GPUUtilizationSample]:
        """Generate realistic utilization patterns.

        Uses deterministic hashing for reproducibility. Patterns:
        - Short jobs (<1h): 60-85% util (interactive/debug)
        - Medium jobs (1-8h): 40-70% util (training warmup + steady)
        - Long jobs (>8h): bimodal — some GPUs high, some idle (poor scaling)
        - ~20% of jobs: nearly idle (<5% util, forgot to clean up)
        """
        samples: list[GPUUtilizationSample] = []
        for alloc in allocations:
            if alloc.end_time is None:
                continue
            duration = (alloc.end_time - alloc.start_time).total_seconds()
            if duration <= 0:
                continue
            hours = duration / 3600
            n_samples = min(max(int(hours * 6), 3), 48)
            step = timedelta(seconds=duration / n_samples)
            h = int(hashlib.md5(alloc.job_id.encode()).hexdigest()[:8], 16)

            is_idle_job = (h % 5) == 0
            is_overalloc = (h % 7) == 0 and len(alloc.gpu_ids) >= 4

            for gi, gid in enumerate(alloc.gpu_ids):
                gh = int(hashlib.md5(f"{alloc.job_id}-{gid}".encode()).hexdigest()[:6], 16)
                if is_idle_job:
                    base = 1.5 + (gh % 5) * 0.5
                elif is_overalloc and gi >= len(alloc.gpu_ids) * 0.5:
                    base = 5.0 + (gh % 20)
                elif hours < 1:
                    base = 60 + (gh % 25)
                elif hours < 8:
                    base = 40 + (gh % 30)
                else:
                    base = 30 + (gh % 35) if gi < len(alloc.gpu_ids) * 0.6 else 8 + (gh % 15)

                for si in range(n_samples):
                    ts = alloc.start_time + step * si
                    noise = ((gh + si * 13) % 15) - 7
                    warmup = min(1.0, (si + 1) / 3) if si < 3 else 1.0
                    util = max(0.0, min(100.0, base * warmup + noise))
                    mem_util = max(0.0, min(100.0, util * 0.75 + ((gh + si) % 10)))
                    samples.append(GPUUtilizationSample(
                        gpu_id=gid,
                        timestamp=ts,
                        gpu_utilization_pct=util,
                        memory_utilization_pct=mem_util,
                        memory_used_gb=0.0,
                        job_id=alloc.job_id,
                    ))
        logger.info("Synthesized %d utilization samples", len(samples))
        return samples

    def _build_decisions(self, jobs: list[Job], allocations: list[Allocation]) -> list[SchedulerDecision]:
        alloc_by_job = {a.job_id: a for a in allocations}
        decisions: list[SchedulerDecision] = []
        for job in jobs:
            if job.start_time is None:
                continue
            alloc = alloc_by_job.get(job.job_id)
            decisions.append(SchedulerDecision(
                decision_id=f"dec-{job.job_id}",
                timestamp=job.start_time,
                decision_type=DecisionType.ALLOCATE,
                job_id=job.job_id,
                chosen_action={
                    "gpu_ids": alloc.gpu_ids if alloc else [],
                    "node_ids": alloc.node_ids if alloc else [],
                    "gpu_count": len(alloc.gpu_ids) if alloc else job.requested_gpus,
                },
            ))
        return decisions

    def _build_queue_snapshots(self, jobs: list[Job], nodes: list[Node]) -> list[QueueSnapshot]:
        total_gpus = sum(n.gpu_count for n in nodes)
        events: list[tuple[datetime, str, str]] = []
        for job in jobs:
            events.append((job.submit_time, "submit", job.job_id))
            if job.start_time:
                events.append((job.start_time, "start", job.job_id))
            if job.end_time:
                events.append((job.end_time, "end", job.job_id))
        events.sort(key=lambda e: e[0])

        if not events:
            return []

        job_map = {j.job_id: j for j in jobs}
        pending: set[str] = set()
        running: set[str] = set()
        snapshots: list[QueueSnapshot] = []
        last_snap: datetime | None = None
        snap_interval = timedelta(minutes=5)

        for ts, kind, jid in events:
            if kind == "submit":
                pending.add(jid)
            elif kind == "start":
                pending.discard(jid)
                running.add(jid)
            elif kind == "end":
                running.discard(jid)

            if last_snap and (ts - last_snap) < snap_interval:
                continue
            last_snap = ts

            alloc_gpus = sum(
                job_map[j].requested_gpus for j in running if j in job_map
            )
            snapshots.append(QueueSnapshot(
                timestamp=ts,
                pending_jobs=sorted(pending),
                running_jobs=sorted(running),
                total_gpus=total_gpus,
                allocated_gpus=min(alloc_gpus, total_gpus),
                idle_gpus=max(0, total_gpus - alloc_gpus),
            ))
        return snapshots


# ===========================================================================
# v2026 connector (Parquet-based)
# ===========================================================================

class V2026Config:
    def __init__(
        self,
        data_dir: str,
        *,
        day_range: tuple[int, int] = (0, 2),
        hour_range: tuple[int, int] = (0, 23),
        gpu_type_filter: str | None = None,
        max_jobs: int | None = None,
        cluster_filter: str | None = None,
    ):
        self.data_dir = data_dir
        self.day_range = day_range
        self.hour_range = hour_range
        self.gpu_type_filter = gpu_type_filter
        self.max_jobs = max_jobs
        self.cluster_filter = cluster_filter


_JOB_TYPE_UTIL: dict[str, tuple[float, float]] = {
    "training": (55.0, 85.0),
    "online_inference": (15.0, 45.0),
    "offline_inference": (35.0, 65.0),
    "dev": (3.0, 20.0),
    "other": (25.0, 50.0),
    "unknown": (20.0, 55.0),
}


class V2026Connector:
    """Converts Alibaba v2026 trace into Natilah ClusterDataset.

    Uses server_hourly (topology) + job_execution_summary (real placement,
    real scheduling delay, real duration). Synthesizes utilization from
    job_type_public since pod_hourly (351 GB) is not required.

    When pod_hourly partitions ARE present, uses real avg_gpu_sm_util.
    """

    def __init__(self, config: V2026Config):
        self.config = config
        self._servers: dict[str, dict] = {}

    def load(self) -> ClusterDataset:
        try:
            import pyarrow.parquet as pq
        except ImportError:
            raise ImportError("pyarrow required for v2026 trace: pip install pyarrow")

        logger.info("Loading v2026 trace from %s", self.config.data_dir)

        self._servers = self._load_servers(pq)
        nodes, gpus = self._build_nodes_gpus()

        has_pod_hourly = self._has_pod_hourly()
        if has_pod_hourly:
            logger.info("Pod hourly data found -- using real utilization")
            pods = self._load_pods_hourly(pq)
            jobs, allocations, samples = self._build_from_pods(pods, gpus)
        else:
            logger.info("Using job_execution_summary (no pod_hourly)")
            exec_rows = self._load_execution_summary(pq)
            jobs, allocations, samples = self._build_from_exec_summary(exec_rows, gpus)

        decisions = self._build_decisions(jobs, allocations)
        queue_snapshots = self._build_queue_snapshots(jobs, nodes)

        dataset = ClusterDataset(
            nodes=nodes, gpus=gpus, jobs=jobs,
            allocations=allocations, samples=samples,
            decisions=decisions, queue_snapshots=queue_snapshots,
        )
        logger.info(
            "Loaded: %d nodes, %d GPUs, %d jobs, %d allocs, %d samples, %d queue snaps",
            len(nodes), len(gpus), len(jobs), len(allocations),
            len(samples), len(queue_snapshots),
        )
        return dataset

    def _has_pod_hourly(self) -> bool:
        base = Path(self.config.data_dir) / "asi_opensource_pod_hourly"
        return base.exists() and any(base.rglob("*.parquet"))

    def _find_parquet_files(self, table_name: str) -> list[str]:
        base = Path(self.config.data_dir) / table_name
        if not base.exists():
            return []
        files: list[str] = []
        for day in range(self.config.day_range[0], self.config.day_range[1] + 1):
            for hour in range(self.config.hour_range[0], self.config.hour_range[1] + 1):
                p = base / f"day={day}" / f"hour={hour:02d}" / "part-000.parquet"
                if p.exists():
                    files.append(str(p))
        if not files:
            for p in sorted(base.rglob("*.parquet")):
                files.append(str(p))
                if len(files) > 500:
                    break
        return files

    def _load_servers(self, pq: Any) -> dict[str, dict]:
        import pyarrow.compute as pc

        files = self._find_parquet_files("asi_opensource_server_hourly")
        if not files:
            logger.warning("No server_hourly Parquet files found")
            return {}

        filters = None
        if self.config.gpu_type_filter:
            filters = pc.field("gpu_spec_public") == self.config.gpu_type_filter
        if self.config.cluster_filter:
            cf = pc.field("cluster_id") == self.config.cluster_filter
            filters = (filters & cf) if filters else cf

        servers: dict[str, dict] = {}
        table = pq.read_table(files[0], filters=filters)
        df = table.to_pydict()
        n = len(df.get("server_id", []))
        for i in range(n):
            sid = df["server_id"][i]
            if sid in servers:
                continue
            gpu_spec = str(df.get("gpu_spec_public", ["unknown"])[i] or "unknown")
            servers[sid] = {
                "server_id": sid,
                "cluster_id": str(df.get("cluster_id", [""])[i] or ""),
                "asw_id": str(df.get("asw_id", [""])[i] or ""),
                "gpu_spec": gpu_spec,
                "gpu_count": int(df.get("gpu_count", [8])[i] or 8),
                "cpu_cores": float(df.get("cpu_capacity_cores", [64])[i] or 64),
            }
        logger.info("Loaded %d servers from server_hourly", len(servers))
        return servers

    def _build_nodes_gpus(self) -> tuple[list[Node], list[GPU]]:
        nodes: list[Node] = []
        gpus: list[GPU] = []
        for sid, s in self._servers.items():
            gpu_type = resolve_gpu_type(s["gpu_spec"])
            gpu_count = s["gpu_count"]
            nodes.append(Node(
                node_id=sid,
                hostname=sid,
                gpu_count=gpu_count,
                gpu_type=gpu_type,
                total_memory_gb=gpu_type.memory_gb * gpu_count,
                cpu_cores=int(s["cpu_cores"]),
                labels={"cluster": s["cluster_id"], "asw": s.get("asw_id", "")},
            ))
            for i in range(gpu_count):
                gpus.append(GPU(
                    gpu_id=f"{sid}-gpu-{i}",
                    gpu_type=gpu_type,
                    node_id=sid,
                    gpu_index=i,
                ))
        return nodes, gpus

    # ---- Primary path: job_execution_summary ----

    def _load_execution_summary(self, pq: Any) -> list[dict]:
        import pyarrow.compute as pc
        import pyarrow.dataset as ds

        path = Path(self.config.data_dir) / "asi_opensource_job_execution_summary" / "part-000.parquet"
        if not path.exists():
            for p in Path(self.config.data_dir).rglob("*job_execution*/*.parquet"):
                path = p
                break
        if not path.exists():
            logger.warning("No job_execution_summary found")
            return []

        filters = pc.field("gpu_request") >= 1.0
        if self.config.gpu_type_filter:
            filters = filters & (pc.field("gpu_spec_public") == self.config.gpu_type_filter)

        cols = [
            "pod_id", "workload_id", "server_id", "gpu_spec_public",
            "gpu_request", "duration_hours", "schedule_delay_sec",
            "ready_delay_sec", "priority_class", "job_type_public",
            "model_type_public", "is_genai_request", "ready_status",
            "schedule_status",
        ]

        logger.info("Reading execution summary with predicate pushdown (%s)...",
                     self.config.gpu_type_filter or "all types")
        table = pq.read_table(str(path), columns=cols, filters=filters)
        logger.info("Filtered to %d rows from Parquet", table.num_rows)

        server_ids = set(self._servers.keys()) if self._servers else None
        df = table.to_pydict()
        rows: list[dict] = []
        limit = self.config.max_jobs or len(df["pod_id"])

        for i in range(len(df["pod_id"])):
            if len(rows) >= limit:
                break
            sid = df["server_id"][i]
            if server_ids and sid and str(sid) not in server_ids:
                continue
            rows.append({
                "pod_id": str(df["pod_id"][i]),
                "workload_id": str(df["workload_id"][i] or ""),
                "server_id": str(sid) if sid else None,
                "gpu_spec": str(df["gpu_spec_public"][i] or "unknown"),
                "gpu_request": float(df["gpu_request"][i] or 0),
                "duration_hours": float(df["duration_hours"][i] or 0),
                "schedule_delay_sec": max(0, int(df["schedule_delay_sec"][i] or 0)),
                "ready_delay_sec": max(0, int(df["ready_delay_sec"][i] or 0)),
                "priority_class": str(df["priority_class"][i] or "Other"),
                "job_type": str(df["job_type_public"][i] or "unknown"),
                "model_type": str(df["model_type_public"][i] or "unknown"),
                "is_genai": bool(df["is_genai_request"][i]),
                "ready_status": bool(df["ready_status"][i]),
                "schedule_status": bool(df["schedule_status"][i]),
            })
        logger.info("Loaded %d rows from execution summary", len(rows))
        return rows

    def _build_from_exec_summary(
        self, rows: list[dict], gpus: list[GPU],
    ) -> tuple[list[Job], list[Allocation], list[GPUUtilizationSample]]:
        gpus_by_server: dict[str, list[GPU]] = defaultdict(list)
        for g in gpus:
            gpus_by_server[g.node_id].append(g)

        jobs: list[Job] = []
        allocations: list[Allocation] = []
        samples: list[GPUUtilizationSample] = []

        rows.sort(key=lambda r: r["schedule_delay_sec"])
        base_time = _EPOCH_ANCHOR

        for idx, row in enumerate(rows):
            pid = row["pod_id"]
            duration_h = max(row["duration_hours"], 0.01)
            sched_delay = row["schedule_delay_sec"]
            gpu_count = max(1, int(row["gpu_request"] + 0.5))

            submit_time = base_time + timedelta(seconds=idx * 30)
            start_time = submit_time + timedelta(seconds=sched_delay)
            end_time = start_time + timedelta(hours=duration_h)

            priority = {"HP": 100, "LP": 10, "Other": 50}.get(row["priority_class"], 50)
            canonical_type = None
            if row["gpu_spec"] != "unknown":
                canonical_type = row["gpu_spec"]

            constraints: dict[str, str] = {
                "job_type": row["job_type"],
                "model_type": row["model_type"],
            }
            if row["is_genai"]:
                constraints["genai"] = "true"

            jobs.append(Job(
                job_id=pid,
                name=row["workload_id"] or pid,
                user=f"wl-{(row['workload_id'] or 'x')[:8]}",
                submit_time=submit_time,
                start_time=start_time,
                end_time=end_time,
                state=JobState.COMPLETED,
                requested_gpus=gpu_count,
                requested_gpu_type=canonical_type,
                priority=priority,
                constraints=constraints,
            ))

            sid = row["server_id"]
            if sid and sid in gpus_by_server:
                server_gpus = gpus_by_server[sid]
                assigned = [g.gpu_id for g in server_gpus[:gpu_count]]
                allocations.append(Allocation(
                    allocation_id=f"alloc-{pid}",
                    job_id=pid,
                    gpu_ids=assigned,
                    node_ids=[sid],
                    start_time=start_time,
                    end_time=end_time,
                ))

                jtype = row["job_type"]
                lo, hi = _JOB_TYPE_UTIL.get(jtype, (20.0, 55.0))
                h = int(hashlib.md5(pid.encode()).hexdigest()[:8], 16)
                n_samples = min(max(int(duration_h * 4), 3), 48)
                step = timedelta(hours=duration_h / n_samples)

                for gi, gid in enumerate(assigned):
                    gh = int(hashlib.md5(f"{pid}-{gid}".encode()).hexdigest()[:6], 16)
                    base_util = lo + (gh % int(hi - lo + 1))
                    if jtype == "dev" and duration_h > 4:
                        base_util = min(base_util, 12.0)
                    if gpu_count >= 4 and gi >= gpu_count * 0.6 and jtype != "training":
                        base_util = max(2.0, base_util * 0.3)

                    for si in range(n_samples):
                        ts = start_time + step * si
                        noise = ((gh + si * 11) % 12) - 6
                        util = max(0.0, min(100.0, base_util + noise))
                        samples.append(GPUUtilizationSample(
                            gpu_id=gid,
                            timestamp=ts,
                            gpu_utilization_pct=util,
                            memory_utilization_pct=util * 0.7 + ((gh + si) % 8),
                            memory_used_gb=0.0,
                            job_id=pid,
                        ))

        return jobs, allocations, samples

    # ---- Alternate path: pod_hourly (real utilization) ----

    def _load_pods_hourly(self, pq: Any) -> list[dict]:
        import pyarrow.compute as pc

        files = self._find_parquet_files("asi_opensource_pod_hourly")
        if not files:
            return []

        filters = pc.field("gpu_request") >= 1.0
        if self.config.gpu_type_filter:
            filters = filters & (pc.field("gpu_spec_public") == self.config.gpu_type_filter)
        if self.config.cluster_filter:
            filters = filters & (pc.field("cluster_id") == self.config.cluster_filter)

        cols = [
            "pod_id", "workload_id", "server_id", "gpu_spec_public",
            "gpu_request", "priority_class", "job_type_public",
            "model_type_public", "schedule_delay_sec", "state_public",
            "used_gpu_hours", "avg_gpu_sm_util", "avg_gpu_mem_gib",
        ]

        server_ids = set(self._servers.keys()) if self._servers else None
        pods_by_id: dict[str, dict] = {}
        count = 0

        for fp in files:
            table = pq.read_table(fp, columns=cols, filters=filters)
            df = table.to_pydict()
            n = len(df["pod_id"])
            for i in range(n):
                pid = str(df["pod_id"][i])
                sid = str(df["server_id"][i] or "")
                if server_ids and sid and sid not in server_ids:
                    continue
                if pid not in pods_by_id:
                    pods_by_id[pid] = {
                        "pod_id": pid,
                        "workload_id": str(df["workload_id"][i] or ""),
                        "server_id": sid,
                        "gpu_spec": str(df["gpu_spec_public"][i] or "unknown"),
                        "gpu_request": float(df["gpu_request"][i] or 0),
                        "priority": str(df["priority_class"][i] or "Other"),
                        "job_type": str(df["job_type_public"][i] or "unknown"),
                        "model_type": str(df["model_type_public"][i] or "unknown"),
                        "schedule_delay": max(0, int(df["schedule_delay_sec"][i] or 0)),
                        "state": str(df["state_public"][i] or "Running"),
                        "hours": [],
                        "utils": [],
                        "mem_gib": [],
                    }
                    count += 1
                pod = pods_by_id[pid]
                pod["hours"].append(float(df["used_gpu_hours"][i] or 0))
                pod["utils"].append(float(df["avg_gpu_sm_util"][i] or 0))
                pod["mem_gib"].append(float(df["avg_gpu_mem_gib"][i] or 0))

                if self.config.max_jobs and count >= self.config.max_jobs:
                    break
            if self.config.max_jobs and count >= self.config.max_jobs:
                break
        logger.info("Loaded %d pods from pod_hourly", len(pods_by_id))
        return list(pods_by_id.values())

    def _build_from_pods(
        self, pods: list[dict], gpus: list[GPU],
    ) -> tuple[list[Job], list[Allocation], list[GPUUtilizationSample]]:
        gpus_by_server: dict[str, list[GPU]] = defaultdict(list)
        for g in gpus:
            gpus_by_server[g.node_id].append(g)

        jobs: list[Job] = []
        allocations: list[Allocation] = []
        samples: list[GPUUtilizationSample] = []

        for idx, pod in enumerate(pods):
            pid = pod["pod_id"]
            total_h = sum(pod["hours"]) if pod["hours"] else 1.0
            gpu_req = max(1, int(pod["gpu_request"] + 0.5))
            sched_delay = pod["schedule_delay"]

            submit_time = _EPOCH_ANCHOR + timedelta(seconds=idx * 30)
            start_time = submit_time + timedelta(seconds=sched_delay)
            end_time = start_time + timedelta(hours=max(total_h / max(pod["gpu_request"], 0.01), 0.1))

            priority = {"HP": 100, "LP": 10, "Other": 50}.get(pod["priority"], 50)
            jobs.append(Job(
                job_id=pid, name=pod["workload_id"] or pid,
                user=f"wl-{(pod.get('workload_id') or 'x')[:8]}",
                submit_time=submit_time, start_time=start_time, end_time=end_time,
                state=JobState.COMPLETED,
                requested_gpus=gpu_req,
                requested_gpu_type=pod["gpu_spec"] if pod["gpu_spec"] != "unknown" else None,
                priority=priority,
                constraints={"job_type": pod["job_type"], "model_type": pod["model_type"]},
            ))

            sid = pod["server_id"]
            if sid and sid in gpus_by_server:
                server_gpus = gpus_by_server[sid]
                assigned = [g.gpu_id for g in server_gpus[:gpu_req]]
                allocations.append(Allocation(
                    allocation_id=f"alloc-{pid}", job_id=pid,
                    gpu_ids=assigned, node_ids=[sid],
                    start_time=start_time, end_time=end_time,
                ))
                step = timedelta(hours=1)
                for hi, (util_pct, mem_gib) in enumerate(zip(pod["utils"], pod["mem_gib"])):
                    ts = start_time + step * hi
                    for gid in assigned:
                        samples.append(GPUUtilizationSample(
                            gpu_id=gid, timestamp=ts,
                            gpu_utilization_pct=util_pct,
                            memory_utilization_pct=min(100, mem_gib * 10),
                            memory_used_gb=mem_gib,
                            job_id=pid,
                        ))

        return jobs, allocations, samples

    # ---- Common ----

    def _build_decisions(self, jobs: list[Job], allocations: list[Allocation]) -> list[SchedulerDecision]:
        alloc_map = {a.job_id: a for a in allocations}
        return [
            SchedulerDecision(
                decision_id=f"dec-{j.job_id}",
                timestamp=j.start_time,
                decision_type=DecisionType.ALLOCATE,
                job_id=j.job_id,
                chosen_action={
                    "gpu_ids": alloc_map[j.job_id].gpu_ids if j.job_id in alloc_map else [],
                    "node_ids": alloc_map[j.job_id].node_ids if j.job_id in alloc_map else [],
                    "gpu_count": len(alloc_map[j.job_id].gpu_ids) if j.job_id in alloc_map else j.requested_gpus,
                },
            )
            for j in jobs if j.start_time
        ]

    def _build_queue_snapshots(self, jobs: list[Job], nodes: list[Node]) -> list[QueueSnapshot]:
        total_gpus = sum(n.gpu_count for n in nodes)
        events: list[tuple[datetime, str, str]] = []
        for j in jobs:
            events.append((j.submit_time, "submit", j.job_id))
            if j.start_time:
                events.append((j.start_time, "start", j.job_id))
            if j.end_time:
                events.append((j.end_time, "end", j.job_id))
        events.sort(key=lambda e: e[0])
        if not events:
            return []

        job_map = {j.job_id: j for j in jobs}
        pending: set[str] = set()
        running: set[str] = set()
        snapshots: list[QueueSnapshot] = []
        last_snap: datetime | None = None
        interval = timedelta(minutes=5)

        for ts, kind, jid in events:
            if kind == "submit":
                pending.add(jid)
            elif kind == "start":
                pending.discard(jid)
                running.add(jid)
            elif kind == "end":
                running.discard(jid)
            if last_snap and (ts - last_snap) < interval:
                continue
            last_snap = ts
            alloc_gpus = sum(job_map[j].requested_gpus for j in running if j in job_map)
            snapshots.append(QueueSnapshot(
                timestamp=ts,
                pending_jobs=sorted(pending),
                running_jobs=sorted(running),
                total_gpus=total_gpus,
                allocated_gpus=min(alloc_gpus, total_gpus),
                idle_gpus=max(0, total_gpus - alloc_gpus),
            ))
        return snapshots
