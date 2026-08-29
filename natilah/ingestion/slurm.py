"""Read-only Slurm connector.

Parses sacct, sinfo, and squeue output into the Natilah normalized model.
Optionally joins Prometheus/DCGM GPU telemetry when available.

Expected input formats:
    sacct:  sacct --format=JobID,JobName,User,Submit,Start,End,State,ReqTRES,AllocTRES,NodeList,Partition,Priority,ExitCode --parsable2 --allusers --allocations
    sinfo:  sinfo --format="%n|%c|%m|%G|%T|%P" --Node --noheader
    squeue: squeue --format="%i|%j|%u|%T|%V|%S|%N|%b|%Q" --noheader
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.ingestion.base import DataSource
from natilah.models.database import replace_cluster_data
from natilah.models.domain import (
    GPU_TYPE_CATALOG,
    Allocation,
    ClusterDataset,
    GPU,
    GPUType,
    GPUUtilizationSample,
    IngestionResult,
    Job,
    Node,
    QueueSnapshot,
    SchedulerDecision,
    ValidationIssue,
)
from natilah.models.enums import DecisionType, JobState

logger = logging.getLogger(__name__)

SLURM_GPU_TYPE_MAP: dict[str, str] = {
    "a100": "A100-80GB",
    "a100_80gb": "A100-80GB",
    "a100_sxm4_80gb": "A100-80GB",
    "nvidia_a100_80gb": "A100-80GB",
    "h100": "H100-80GB",
    "h100_80gb": "H100-80GB",
    "h100_sxm5_80gb": "H100-80GB",
    "nvidia_h100_80gb": "H100-80GB",
    "h200": "H200-141GB",
    "h200_141gb": "H200-141GB",
    "b200": "B200-192GB",
    "b200_192gb": "B200-192GB",
}

JOB_STATE_MAP: dict[str, JobState] = {
    "COMPLETED": JobState.COMPLETED,
    "FAILED": JobState.FAILED,
    "TIMEOUT": JobState.FAILED,
    "NODE_FAIL": JobState.FAILED,
    "OUT_OF_MEMORY": JobState.FAILED,
    "CANCELLED": JobState.CANCELLED,
    "CANCELLED+": JobState.CANCELLED,
    "PENDING": JobState.PENDING,
    "RUNNING": JobState.RUNNING,
    "SUSPENDED": JobState.RUNNING,
    "PREEMPTED": JobState.CANCELLED,
}

SACCT_FORMAT = "JobID,JobName,User,Submit,Start,End,State,ReqTRES,AllocTRES,NodeList,Partition,Priority,ExitCode"
SINFO_FORMAT = "%n|%c|%m|%G|%T|%P"
SQUEUE_FORMAT = "%i|%j|%u|%T|%V|%S|%N|%b|%Q"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _slurm_ts(text: str) -> datetime | None:
    if not text or text.strip() in ("Unknown", "None", "N/A", "", "0"):
        return None
    cleaned = text.strip()
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(cleaned, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _split_outside_brackets(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def expand_nodelist(compact: str) -> list[str]:
    """Expand Slurm hostlist notation to individual hostnames.

    Handles: node01, node[01-04], node[01,03,05],
    node[01-03,05,07-09], prefix[01-04],other[01-02]
    """
    if not compact or compact.strip() in ("(null)", "None", "N/A", ""):
        return []
    results: list[str] = []
    for part in _split_outside_brackets(compact.strip()):
        part = part.strip()
        if not part:
            continue
        if "[" not in part:
            results.append(part)
            continue
        idx = part.index("[")
        prefix = part[:idx]
        bracket = part[idx + 1 :].rstrip("]")
        for segment in bracket.split(","):
            if "-" in segment:
                lo, hi = segment.split("-", 1)
                width = len(lo)
                for i in range(int(lo), int(hi) + 1):
                    results.append(f"{prefix}{str(i).zfill(width)}")
            else:
                results.append(f"{prefix}{segment}")
    return results


def resolve_gpu_type(slurm_name: str | None) -> str:
    if not slurm_name:
        return "A100-80GB"
    key = slurm_name.lower().replace("-", "_")
    return SLURM_GPU_TYPE_MAP.get(key, slurm_name)


def parse_tres(tres: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not tres:
        return result
    for item in tres.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            result[k.strip()] = v.strip()
    return result


def gpu_from_tres(tres: dict[str, str]) -> tuple[str | None, int]:
    for key, val in tres.items():
        if key.startswith("gres/gpu:"):
            name = key.split(":", 1)[1]
            return name, int(val)
    plain = tres.get("gres/gpu")
    if plain:
        return None, int(plain)
    return None, 0


def parse_gres(gres: str) -> tuple[str | None, int]:
    """Parse GRES string → (gpu_type_name, count).

    Handles: gpu:a100:8(S:0-1), gpu:8, gres:gpu:8, gres/gpu:a100:8
    """
    if not gres or gres.strip() in ("(null)", "", "N/A"):
        return None, 0
    for entry in gres.split(","):
        entry = entry.strip()
        entry = re.sub(r"\(S:[^)]*\)", "", entry).strip()
        entry = re.sub(r"^gres[:/]", "", entry)
        parts = entry.split(":")
        if not parts or parts[0] != "gpu":
            continue
        if len(parts) >= 3:
            try:
                return parts[1], int(parts[2])
            except ValueError:
                return parts[1], 0
        if len(parts) == 2:
            try:
                return None, int(parts[1])
            except ValueError:
                return parts[1], 0
    return None, 0


# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def parse_sacct(text: str) -> list[dict[str, str]]:
    """Parse sacct --parsable2 output. First line = header."""
    lines = text.strip().splitlines()
    if len(lines) < 2:
        return []
    header = [h.strip() for h in lines[0].split("|")]
    records: list[dict[str, str]] = []
    for line in lines[1:]:
        if not line.strip():
            continue
        values = line.split("|")
        row = dict(zip(header, values))
        job_id = row.get("JobID", "")
        if "." in job_id:
            continue
        records.append(row)
    return records


def parse_sinfo(text: str) -> list[dict[str, str]]:
    """Parse sinfo pipe-delimited output. hostname|cpus|mem_mb|gres|state|partition"""
    field_names = ["hostname", "cpus", "mem_mb", "gres", "state", "partition"]
    records: list[dict[str, str]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.upper().startswith("HOSTNAMES") or line.upper().startswith("NODELIST"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        row = dict(zip(field_names, parts))
        for hostname in expand_nodelist(row["hostname"]):
            record = dict(row)
            record["hostname"] = hostname
            records.append(record)
    return records


def parse_squeue_snapshot(text: str) -> list[dict[str, str]]:
    """Parse squeue pipe-delimited snapshot. jobid|name|user|state|submit|start|nodelist|tres|priority"""
    field_names = ["jobid", "name", "user", "state", "submit", "start", "nodelist", "tres", "priority"]
    records: list[dict[str, str]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.upper().startswith("JOBID"):
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        records.append(dict(zip(field_names, parts)))
    return records


# ---------------------------------------------------------------------------
# Prometheus / DCGM telemetry
# ---------------------------------------------------------------------------

async def fetch_dcgm_samples(
    prometheus_url: str,
    start: datetime,
    end: datetime,
    hostname_to_node: dict[str, str],
    step: int = 300,
) -> list[GPUUtilizationSample]:
    import httpx

    base = prometheus_url.rstrip("/")
    metric_fields = {
        "DCGM_FI_DEV_GPU_UTIL": "gpu_util",
        "DCGM_FI_DEV_MEM_COPY_UTIL": "mem_util",
        "DCGM_FI_DEV_FB_USED": "mem_used_mib",
        "DCGM_FI_DEV_POWER_USAGE": "power_w",
    }
    raw: dict[tuple[str, str], dict[str, dict[float, float]]] = defaultdict(lambda: defaultdict(dict))

    async with httpx.AsyncClient(timeout=60.0) as client:
        for metric_name, field in metric_fields.items():
            chunk_start = start
            while chunk_start < end:
                chunk_end = min(chunk_start + timedelta(days=1), end)
                params = {
                    "query": metric_name,
                    "start": str(int(chunk_start.timestamp())),
                    "end": str(int(chunk_end.timestamp())),
                    "step": str(step),
                }
                try:
                    resp = await client.get(f"{base}/api/v1/query_range", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    logger.warning("Prometheus query failed: %s [%s–%s]", metric_name, chunk_start, chunk_end)
                    chunk_start = chunk_end
                    continue
                for result in data.get("data", {}).get("result", []):
                    labels = result.get("metric", {})
                    hostname = (
                        labels.get("Hostname")
                        or labels.get("hostname")
                        or labels.get("instance", "").split(":")[0]
                    )
                    gpu_idx = labels.get("gpu", "0")
                    key = (hostname, gpu_idx)
                    for ts_val in result.get("values", []):
                        ts = float(ts_val[0])
                        val = float(ts_val[1]) if ts_val[1] != "NaN" else 0.0
                        raw[key][field][ts] = val
                chunk_start = chunk_end

    samples: list[GPUUtilizationSample] = []
    for (hostname, gpu_idx), fields in raw.items():
        node_id = hostname_to_node.get(hostname, hostname)
        gpu_id = f"{node_id}-gpu-{gpu_idx}"
        for ts, gpu_util in fields.get("gpu_util", {}).items():
            samples.append(
                GPUUtilizationSample(
                    gpu_id=gpu_id,
                    timestamp=datetime.fromtimestamp(ts, tz=timezone.utc),
                    gpu_utilization_pct=gpu_util,
                    memory_utilization_pct=fields.get("mem_util", {}).get(ts, 0.0),
                    memory_used_gb=fields.get("mem_used_mib", {}).get(ts, 0.0) / 1024.0,
                    power_watts=fields.get("power_w", {}).get(ts),
                )
            )
    return samples


# ---------------------------------------------------------------------------
# SlurmDataSource
# ---------------------------------------------------------------------------

class SlurmDataSource(DataSource):
    """Read-only Slurm connector. Never modifies infrastructure."""

    def __init__(
        self,
        *,
        sacct_text: str | None = None,
        sinfo_text: str | None = None,
        sacct_path: str | Path | None = None,
        sinfo_path: str | Path | None = None,
        squeue_dir: str | Path | None = None,
        squeue_snapshots: list[tuple[datetime, str]] | None = None,
        prometheus_url: str | None = None,
        prometheus_start: datetime | None = None,
        prometheus_end: datetime | None = None,
        prometheus_step: int = 300,
        gpu_type_override: str | None = None,
    ):
        if sacct_path and sacct_text is None:
            sacct_text = Path(sacct_path).read_text(encoding="utf-8")
        if sinfo_path and sinfo_text is None:
            sinfo_text = Path(sinfo_path).read_text(encoding="utf-8")

        self.sacct_text = sacct_text or ""
        self.sinfo_text = sinfo_text or ""
        self.squeue_snapshots = list(squeue_snapshots or [])
        self.prometheus_url = prometheus_url
        self.prometheus_start = prometheus_start
        self.prometheus_end = prometheus_end
        self.prometheus_step = prometheus_step
        self.gpu_type_override = gpu_type_override

        if squeue_dir and not self.squeue_snapshots:
            self.squeue_snapshots = self._load_squeue_dir(Path(squeue_dir))

    # -- public --

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not self.sacct_text.strip():
            issues.append(ValidationIssue(field="sacct", message="No sacct data provided"))
        if not self.sinfo_text.strip():
            issues.append(ValidationIssue(field="sinfo", message="No sinfo data provided"))
        if self.sacct_text.strip():
            header_cols = {h.strip() for h in self.sacct_text.strip().splitlines()[0].split("|")}
            missing = {"JobID", "Submit", "Start", "NodeList"} - header_cols
            if missing:
                issues.append(
                    ValidationIssue(field="sacct_header", message=f"Missing columns: {', '.join(sorted(missing))}")
                )
        return issues

    def build_dataset(self) -> ClusterDataset:
        sinfo_records = parse_sinfo(self.sinfo_text)
        sacct_records = parse_sacct(self.sacct_text)

        nodes, gpus = self._build_nodes(sinfo_records)
        gpu_by_node: dict[str, list[GPU]] = defaultdict(list)
        for gpu in gpus:
            gpu_by_node[gpu.node_id].append(gpu)
        for lst in gpu_by_node.values():
            lst.sort(key=lambda g: g.gpu_index)

        known = {n.node_id for n in nodes}
        jobs, allocations, decisions = self._build_jobs(sacct_records, gpu_by_node, known)

        queue_snapshots: list[QueueSnapshot] = []
        total_gpus = len(gpus)
        for ts, text in self.squeue_snapshots:
            queue_snapshots.append(self._build_queue_snapshot(text, ts, total_gpus))
        if not queue_snapshots and jobs:
            queue_snapshots = self._synthesize_queue_snapshots(jobs, allocations, total_gpus)

        return ClusterDataset(
            nodes=nodes,
            gpus=gpus,
            jobs=jobs,
            allocations=allocations,
            samples=[],
            decisions=decisions,
            queue_snapshots=queue_snapshots,
        )

    async def ingest(self, db: AsyncSession) -> IngestionResult:
        issues = self.validate()
        if issues:
            raise ValueError("; ".join(f"{i.field}: {i.message}" for i in issues))

        dataset = self.build_dataset()

        if self.prometheus_url:
            hostname_map = {n.hostname: n.node_id for n in dataset.nodes}
            hostname_map.update({n.node_id: n.node_id for n in dataset.nodes})
            start = self.prometheus_start
            end = self.prometheus_end
            if start is None or end is None:
                times = [j.submit_time for j in dataset.jobs]
                times += [j.end_time for j in dataset.jobs if j.end_time]
                if times:
                    start = start or min(times)
                    end = end or max(times)
            if start and end:
                try:
                    samples = await fetch_dcgm_samples(
                        self.prometheus_url, start, end, hostname_map, self.prometheus_step
                    )
                    alloc_idx = _alloc_index(dataset.allocations)
                    for s in samples:
                        s.job_id = _job_at(s.gpu_id, s.timestamp, alloc_idx)
                    dataset.samples = samples
                    logger.info("Fetched %d DCGM samples from Prometheus", len(samples))
                except Exception:
                    logger.exception("Prometheus fetch failed; continuing without telemetry")

        await replace_cluster_data(db, dataset)
        return IngestionResult(
            nodes=len(dataset.nodes),
            gpus=len(dataset.gpus),
            jobs=len(dataset.jobs),
            allocations=len(dataset.allocations),
            samples=len(dataset.samples),
            decisions=len(dataset.decisions),
            source="slurm",
        )

    # -- internals --

    @staticmethod
    def _load_squeue_dir(directory: Path) -> list[tuple[datetime, str]]:
        snapshots: list[tuple[datetime, str]] = []
        for path in sorted(directory.glob("squeue_*.txt")):
            stem = path.stem.replace("squeue_", "")
            match = re.search(r"(\d{4})-?(\d{2})-?(\d{2})[T_-]?(\d{2})-?(\d{2})-?(\d{2})", stem)
            if match:
                g = match.groups()
                ts = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]), int(g[5]), tzinfo=timezone.utc)
                snapshots.append((ts, path.read_text(encoding="utf-8")))
        return snapshots

    def _build_nodes(self, sinfo_records: list[dict[str, str]]) -> tuple[list[Node], list[GPU]]:
        nodes: list[Node] = []
        gpus: list[GPU] = []
        seen: set[str] = set()
        for rec in sinfo_records:
            hostname = rec["hostname"]
            if hostname in seen:
                continue
            seen.add(hostname)
            cpus = int(rec.get("cpus", "64"))
            mem_mb = int(rec.get("mem_mb", "524288"))
            gres_name, gpu_count = parse_gres(rec.get("gres", ""))
            if gpu_count == 0:
                continue
            catalog_name = self.gpu_type_override or resolve_gpu_type(gres_name)
            gpu_type = GPU_TYPE_CATALOG.get(catalog_name)
            if gpu_type is None:
                gpu_type = GPUType(
                    name=catalog_name,
                    memory_gb=mem_mb / 1024.0 / gpu_count if gpu_count else 80.0,
                    tdp_watts=400.0,
                    compute_capability="8.0",
                    fp16_tflops=312.0,
                )
            node_id = hostname
            nodes.append(
                Node(
                    node_id=node_id,
                    hostname=hostname,
                    gpu_count=gpu_count,
                    gpu_type=gpu_type,
                    total_memory_gb=mem_mb / 1024.0,
                    cpu_cores=cpus,
                    labels={"partition": rec.get("partition", ""), "source": "slurm"},
                )
            )
            for idx in range(gpu_count):
                gpus.append(
                    GPU(gpu_id=f"{node_id}-gpu-{idx}", gpu_type=gpu_type, node_id=node_id, gpu_index=idx)
                )
        return nodes, gpus

    def _build_jobs(
        self,
        sacct_records: list[dict[str, str]],
        gpu_by_node: dict[str, list[GPU]],
        known_nodes: set[str],
    ) -> tuple[list[Job], list[Allocation], list[SchedulerDecision]]:
        jobs: list[Job] = []
        allocations: list[Allocation] = []
        decisions: list[SchedulerDecision] = []

        for rec in sacct_records:
            job_id = rec.get("JobID", "").strip()
            if not job_id:
                continue
            submit = _slurm_ts(rec.get("Submit", ""))
            start = _slurm_ts(rec.get("Start", ""))
            end = _slurm_ts(rec.get("End", ""))
            if submit is None:
                continue

            slurm_state = rec.get("State", "COMPLETED").split()[0]
            state = JOB_STATE_MAP.get(slurm_state, JobState.COMPLETED)

            alloc_tres = parse_tres(rec.get("AllocTRES", ""))
            req_tres = parse_tres(rec.get("ReqTRES", ""))
            alloc_gpu_name, alloc_gpu_count = gpu_from_tres(alloc_tres)
            req_gpu_name, req_gpu_count = gpu_from_tres(req_tres)
            gpu_count = alloc_gpu_count or req_gpu_count
            if gpu_count == 0:
                continue

            gpu_type_name = self.gpu_type_override or resolve_gpu_type(alloc_gpu_name or req_gpu_name)
            node_list = expand_nodelist(rec.get("NodeList", ""))
            node_ids = [n for n in node_list if n in known_nodes] or node_list

            priority = 0
            try:
                priority = int(rec.get("Priority", "0"))
            except ValueError:
                pass

            jobs.append(
                Job(
                    job_id=job_id,
                    name=rec.get("JobName", job_id),
                    user=rec.get("User", "unknown"),
                    submit_time=submit,
                    start_time=start,
                    end_time=end,
                    state=state,
                    requested_gpus=req_gpu_count or gpu_count,
                    requested_gpu_type=gpu_type_name,
                    priority=priority,
                    constraints={"partition": rec.get("Partition", ""), "source": "sacct"},
                )
            )

            if start and node_ids:
                gpu_ids = _assign_gpu_ids(node_ids, gpu_count, gpu_by_node)
                allocations.append(
                    Allocation(
                        allocation_id=f"alloc-{job_id}",
                        job_id=job_id,
                        gpu_ids=gpu_ids,
                        node_ids=node_ids,
                        start_time=start,
                        end_time=end,
                        decision_reason="slurm_observed_allocation",
                    )
                )
                decisions.append(
                    SchedulerDecision(
                        decision_id=f"dec-{job_id}",
                        timestamp=start,
                        decision_type=DecisionType.ALLOCATE,
                        job_id=job_id,
                        chosen_action={"gpu_ids": gpu_ids, "node_ids": node_ids, "requested_gpus": gpu_count},
                    )
                )

            if start and submit:
                wait = (start - submit).total_seconds()
                if wait > 300:
                    decisions.append(
                        SchedulerDecision(
                            decision_id=f"dec-queue-{job_id}",
                            timestamp=submit,
                            decision_type=DecisionType.QUEUE,
                            job_id=job_id,
                            chosen_action={"queued_seconds": wait},
                        )
                    )

        return jobs, allocations, decisions

    def _build_queue_snapshot(self, text: str, timestamp: datetime, total_gpus: int) -> QueueSnapshot:
        records = parse_squeue_snapshot(text)
        pending: list[str] = []
        running: list[str] = []
        allocated = 0
        for rec in records:
            st = rec.get("state", "").upper()
            jid = rec.get("jobid", "")
            if st == "PENDING":
                pending.append(jid)
            elif st == "RUNNING":
                running.append(jid)
                _, count = parse_gres(rec.get("tres", ""))
                allocated += count
        return QueueSnapshot(
            timestamp=timestamp,
            pending_jobs=pending,
            running_jobs=running,
            total_gpus=total_gpus,
            allocated_gpus=allocated,
            idle_gpus=max(0, total_gpus - allocated),
        )

    @staticmethod
    def _synthesize_queue_snapshots(
        jobs: list[Job], allocations: list[Allocation], total_gpus: int
    ) -> list[QueueSnapshot]:
        if not jobs:
            return []
        start = min(j.submit_time for j in jobs)
        end = max((j.end_time or j.submit_time) for j in jobs)
        alloc_by_job = {a.job_id: a for a in allocations}
        snapshots: list[QueueSnapshot] = []
        t = start
        step = timedelta(minutes=15)
        while t <= end:
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assign_gpu_ids(
    node_ids: list[str], gpu_count: int, gpu_by_node: dict[str, list[GPU]]
) -> list[str]:
    assigned: list[str] = []
    remaining = gpu_count
    per_node = max(1, gpu_count // len(node_ids)) if node_ids else gpu_count
    for i, nid in enumerate(node_ids):
        node_gpus = gpu_by_node.get(nid, [])
        take = min(remaining, len(node_gpus))
        if i < len(node_ids) - 1:
            take = min(per_node, take)
        assigned.extend(g.gpu_id for g in node_gpus[:take])
        remaining -= take
        if remaining <= 0:
            break
    for i in range(remaining):
        fallback = node_ids[0] if node_ids else "unknown"
        assigned.append(f"{fallback}-gpu-{len(assigned)}")
    return assigned


def _alloc_index(allocations: list[Allocation]) -> dict[str, list[Allocation]]:
    idx: dict[str, list[Allocation]] = defaultdict(list)
    for alloc in allocations:
        for gid in alloc.gpu_ids:
            idx[gid].append(alloc)
    return idx


def _job_at(gpu_id: str, timestamp: datetime, alloc_idx: dict[str, list[Allocation]]) -> str | None:
    for alloc in alloc_idx.get(gpu_id, []):
        if alloc.start_time <= timestamp and (alloc.end_time is None or alloc.end_time > timestamp):
            return alloc.job_id
    return None
