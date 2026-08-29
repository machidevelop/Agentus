"""Convert raw cluster events into the normalized domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from natilah.models.domain import (
    GPU_TYPE_CATALOG,
    Allocation,
    ClusterDataset,
    GPU,
    GPUType,
    GPUUtilizationSample,
    Job,
    Node,
    QueueSnapshot,
    SchedulerDecision,
    ValidationIssue,
)
from natilah.models.enums import DecisionType, JobState


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _gpu_type(name: Any, extra: dict[str, Any] | None = None) -> GPUType:
    if isinstance(name, dict):
        extra = name
        name = name.get("name", "A100-80GB")
    if isinstance(name, str) and name in GPU_TYPE_CATALOG:
        return GPU_TYPE_CATALOG[name]
    extra = extra or {}
    return GPUType(
        name=str(name),
        memory_gb=float(extra.get("memory_gb", 80.0)),
        tdp_watts=float(extra.get("tdp_watts", 400.0)),
        compute_capability=str(extra.get("compute_capability", "8.0")),
        fp16_tflops=float(extra.get("fp16_tflops", 312.0)),
    )


def validate_raw(payload: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(payload, dict):
        return [ValidationIssue(field="root", message="Payload must be a JSON object")]
    for key in ("nodes", "gpus", "jobs", "allocations"):
        if key not in payload or not isinstance(payload[key], list):
            issues.append(ValidationIssue(field=key, message=f"Missing or invalid '{key}' array"))
    return issues


def normalize(payload: dict[str, Any]) -> ClusterDataset:
    nodes = [
        Node(
            node_id=n["node_id"],
            hostname=n.get("hostname", n["node_id"]),
            gpu_count=int(n.get("gpu_count", 8)),
            gpu_type=_gpu_type(n.get("gpu_type", n.get("gpu_type_name", "A100-80GB")), n),
            total_memory_gb=float(n.get("total_memory_gb", 640.0)),
            cpu_cores=int(n.get("cpu_cores", 64)),
            labels=n.get("labels") or {},
        )
        for n in payload.get("nodes", [])
    ]
    gpus = [
        GPU(
            gpu_id=g["gpu_id"],
            gpu_type=_gpu_type(g.get("gpu_type", g.get("gpu_type_name", "A100-80GB")), g),
            node_id=g["node_id"],
            gpu_index=int(g.get("gpu_index", 0)),
        )
        for g in payload.get("gpus", [])
    ]
    jobs = [
        Job(
            job_id=j["job_id"],
            name=j.get("name", j["job_id"]),
            user=j.get("user", "unknown"),
            submit_time=_parse_dt(j["submit_time"]),
            start_time=_parse_dt(j.get("start_time")),
            end_time=_parse_dt(j.get("end_time")),
            state=JobState(j.get("state", "completed")),
            requested_gpus=int(j.get("requested_gpus", 1)),
            requested_gpu_type=j.get("requested_gpu_type"),
            priority=int(j.get("priority", 0)),
            constraints=j.get("constraints") or {},
        )
        for j in payload.get("jobs", [])
    ]
    allocations = [
        Allocation(
            allocation_id=a.get("allocation_id", f"alloc-{a['job_id']}"),
            job_id=a["job_id"],
            gpu_ids=list(a.get("gpu_ids", [])),
            node_ids=list(a.get("node_ids", [])),
            start_time=_parse_dt(a["start_time"]),
            end_time=_parse_dt(a.get("end_time")),
            decision_reason=a.get("decision_reason"),
        )
        for a in payload.get("allocations", [])
    ]
    samples = [
        GPUUtilizationSample(
            gpu_id=s["gpu_id"],
            timestamp=_parse_dt(s["timestamp"]),
            gpu_utilization_pct=float(s.get("gpu_utilization_pct", 0.0)),
            memory_utilization_pct=float(s.get("memory_utilization_pct", 0.0)),
            memory_used_gb=float(s.get("memory_used_gb", 0.0)),
            power_watts=s.get("power_watts"),
            job_id=s.get("job_id"),
        )
        for s in payload.get("utilization_samples", payload.get("samples", []))
    ]
    decisions = [
        SchedulerDecision(
            decision_id=d.get("decision_id", f"dec-{d['job_id']}"),
            timestamp=_parse_dt(d["timestamp"]),
            decision_type=DecisionType(d.get("decision_type", "allocate")),
            job_id=d["job_id"],
            chosen_action=d.get("chosen_action") or {},
            cluster_state_id=d.get("cluster_state_id"),
        )
        for d in payload.get("scheduler_decisions", payload.get("decisions", []))
    ]
    queues = [
        QueueSnapshot(
            timestamp=_parse_dt(q["timestamp"]),
            pending_jobs=list(q.get("pending_jobs", [])),
            running_jobs=list(q.get("running_jobs", [])),
            total_gpus=int(q.get("total_gpus", 0)),
            allocated_gpus=int(q.get("allocated_gpus", 0)),
            idle_gpus=int(q.get("idle_gpus", 0)),
        )
        for q in payload.get("queue_snapshots", [])
    ]
    return ClusterDataset(
        nodes=nodes,
        gpus=gpus,
        jobs=jobs,
        allocations=allocations,
        samples=samples,
        decisions=decisions,
        queue_snapshots=queues,
    )
