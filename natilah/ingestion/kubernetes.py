"""Read-only Kubernetes connector.

Captures Pods, Jobs, Deployments, Nodes, Events, GPU requests/assignments,
scheduling decisions, affinity rules, taints/tolerations, Kueue metadata,
and Prometheus/DCGM GPU telemetry. Maps into existing Natilah normalized model.

Supports two modes:
    - Live: reads from cluster via kubernetes python client (kubeconfig/in-cluster)
    - Snapshot: reads from JSON dumps (kubectl get pods -o json, etc.)

Never modifies cluster state. All API calls are read-only (GET/LIST).
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

GPU_RESOURCE_KEY = "nvidia.com/gpu"

K8S_GPU_LABEL_MAP: dict[str, str] = {
    "nvidia-a100-sxm4-80gb": "A100-80GB",
    "nvidia-a100-80gb": "A100-80GB",
    "a100-sxm-80gb": "A100-80GB",
    "a100": "A100-80GB",
    "nvidia-h100-sxm5-80gb": "H100-80GB",
    "nvidia-h100-80gb": "H100-80GB",
    "h100-sxm-80gb": "H100-80GB",
    "h100": "H100-80GB",
    "nvidia-h200-141gb": "H200-141GB",
    "h200": "H200-141GB",
    "nvidia-b200-192gb": "B200-192GB",
    "b200": "B200-192GB",
}

POD_PHASE_MAP: dict[str, JobState] = {
    "Pending": JobState.PENDING,
    "Running": JobState.RUNNING,
    "Succeeded": JobState.COMPLETED,
    "Failed": JobState.FAILED,
    "Unknown": JobState.FAILED,
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_k8s_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    cleaned = ts.strip().rstrip("Z")
    if "+" in cleaned[10:]:
        cleaned = cleaned[: cleaned.rindex("+")]
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def resolve_gpu_type_from_labels(labels: dict[str, str]) -> str:
    """Extract GPU type from common K8s node labels."""
    gpu_product = (
        labels.get("nvidia.com/gpu.product", "")
        or labels.get("nvidia.com/gpu.machine", "")
        or labels.get("gpu-type", "")
        or labels.get("accelerator", "")
    )
    if gpu_product:
        key = gpu_product.lower().replace(" ", "-").replace("_", "-")
        if key in K8S_GPU_LABEL_MAP:
            return K8S_GPU_LABEL_MAP[key]
        for pattern, catalog_name in K8S_GPU_LABEL_MAP.items():
            if pattern in key:
                return catalog_name
    return "A100-80GB"


def extract_gpu_count(container_spec: dict[str, Any]) -> int:
    """Extract nvidia.com/gpu count from container resource requests/limits."""
    requests = container_spec.get("resources", {}).get("requests", {})
    limits = container_spec.get("resources", {}).get("limits", {})
    gpu_str = requests.get(GPU_RESOURCE_KEY) or limits.get(GPU_RESOURCE_KEY) or "0"
    try:
        return int(gpu_str)
    except (ValueError, TypeError):
        return 0


def pod_total_gpus(pod_spec: dict[str, Any]) -> int:
    """Sum GPU requests across all containers and init containers."""
    total = 0
    for container in pod_spec.get("containers", []):
        total += extract_gpu_count(container)
    for container in pod_spec.get("initContainers", []):
        total += extract_gpu_count(container)
    return total


def extract_affinity(pod_spec: dict[str, Any]) -> dict[str, Any]:
    """Extract affinity rules, nodeSelector, tolerations from pod spec."""
    constraints: dict[str, Any] = {}
    node_selector = pod_spec.get("nodeSelector")
    if node_selector:
        constraints["nodeSelector"] = node_selector

    affinity = pod_spec.get("affinity")
    if affinity:
        node_affinity = affinity.get("nodeAffinity")
        if node_affinity:
            required = node_affinity.get("requiredDuringSchedulingIgnoredDuringExecution")
            if required:
                constraints["requiredNodeAffinity"] = _summarize_node_selector_terms(required)
            preferred = node_affinity.get("preferredDuringSchedulingIgnoredDuringExecution")
            if preferred:
                constraints["preferredNodeAffinity"] = len(preferred)

    tolerations = pod_spec.get("tolerations", [])
    non_default = [t for t in tolerations if t.get("key", "").startswith("nvidia.com") or t.get("effect") == "NoSchedule"]
    if non_default:
        constraints["gpuTolerations"] = [
            {"key": t.get("key", ""), "effect": t.get("effect", ""), "value": t.get("value", "")}
            for t in non_default
        ]

    return constraints


def _summarize_node_selector_terms(selector: dict[str, Any]) -> list[str]:
    terms = []
    for term in selector.get("nodeSelectorTerms", []):
        for expr in term.get("matchExpressions", []):
            terms.append(f"{expr.get('key')} {expr.get('operator')} {expr.get('values', [])}")
    return terms


def extract_scheduling_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a K8s Event into scheduling-relevant info."""
    reason = event.get("reason", "")
    if reason not in ("Scheduled", "FailedScheduling", "Preempted", "TriggeredScaleUp"):
        return None
    involved = event.get("involvedObject", {}) or event.get("regarding", {})
    return {
        "reason": reason,
        "message": event.get("message", ""),
        "timestamp": event.get("firstTimestamp") or event.get("eventTime") or event.get("metadata", {}).get("creationTimestamp"),
        "pod_name": involved.get("name", ""),
        "namespace": involved.get("namespace", ""),
        "pod_uid": involved.get("uid", ""),
    }


def parse_kueue_workload(workload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract admission timing from a Kueue Workload resource."""
    metadata = workload.get("metadata", {})
    status = workload.get("status", {})
    spec = workload.get("spec", {})

    creation = metadata.get("creationTimestamp")
    admission = status.get("admission")
    conditions = status.get("conditions", [])

    admitted_at = None
    for cond in conditions:
        if cond.get("type") == "Admitted" and cond.get("status") == "True":
            admitted_at = cond.get("lastTransitionTime")
            break

    if not creation:
        return None

    pod_sets = spec.get("podSets", [])
    gpu_count = 0
    for ps in pod_sets:
        for container in ps.get("template", {}).get("spec", {}).get("containers", []):
            gpu_count += extract_gpu_count(container)

    owner_ref = metadata.get("ownerReferences", [{}])[0] if metadata.get("ownerReferences") else {}

    return {
        "name": metadata.get("name", ""),
        "namespace": metadata.get("namespace", ""),
        "creation": creation,
        "admitted_at": admitted_at,
        "cluster_queue": admission.get("clusterQueue", "") if admission else "",
        "gpu_count": gpu_count,
        "owner_kind": owner_ref.get("kind", ""),
        "owner_name": owner_ref.get("name", ""),
    }


# ---------------------------------------------------------------------------
# KubernetesDataSource
# ---------------------------------------------------------------------------


class KubernetesDataSource(DataSource):
    """Read-only Kubernetes connector. Never modifies cluster state."""

    def __init__(
        self,
        *,
        nodes_json: list[dict[str, Any]] | None = None,
        pods_json: list[dict[str, Any]] | None = None,
        events_json: list[dict[str, Any]] | None = None,
        kueue_workloads_json: list[dict[str, Any]] | None = None,
        prometheus_url: str | None = None,
        prometheus_start: datetime | None = None,
        prometheus_end: datetime | None = None,
        prometheus_step: int = 300,
        gpu_type_override: str | None = None,
        namespace_filter: str | None = None,
    ):
        self.nodes_json = nodes_json or []
        self.pods_json = pods_json or []
        self.events_json = events_json or []
        self.kueue_workloads_json = kueue_workloads_json or []
        self.prometheus_url = prometheus_url
        self.prometheus_start = prometheus_start
        self.prometheus_end = prometheus_end
        self.prometheus_step = prometheus_step
        self.gpu_type_override = gpu_type_override
        self.namespace_filter = namespace_filter

    @classmethod
    def from_snapshot_dir(cls, directory: str | Path, **kwargs: Any) -> "KubernetesDataSource":
        """Load from a directory of kubectl JSON dumps."""
        import json

        path = Path(directory)
        nodes = pods = events = kueue = []

        nodes_file = path / "nodes.json"
        if nodes_file.exists():
            data = json.loads(nodes_file.read_text(encoding="utf-8"))
            nodes = data.get("items", []) if "items" in data else [data]

        pods_file = path / "pods.json"
        if pods_file.exists():
            data = json.loads(pods_file.read_text(encoding="utf-8"))
            pods = data.get("items", []) if "items" in data else [data]

        events_file = path / "events.json"
        if events_file.exists():
            data = json.loads(events_file.read_text(encoding="utf-8"))
            events = data.get("items", []) if "items" in data else [data]

        kueue_file = path / "kueue_workloads.json"
        if kueue_file.exists():
            data = json.loads(kueue_file.read_text(encoding="utf-8"))
            kueue = data.get("items", []) if "items" in data else [data]

        return cls(
            nodes_json=nodes,
            pods_json=pods,
            events_json=events,
            kueue_workloads_json=kueue,
            **kwargs,
        )

    @classmethod
    async def from_live_cluster(
        cls,
        kubeconfig: str | None = None,
        context: str | None = None,
        namespace: str | None = None,
        since_hours: int = 168,
        **kwargs: Any,
    ) -> "KubernetesDataSource":
        """Read from live cluster. Uses kubernetes python client. Purely read-only."""
        try:
            from kubernetes import client, config
        except ImportError:
            raise ImportError("Install kubernetes package: pip install kubernetes")

        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig, context=context)
        else:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config(context=context)

        core_v1 = client.CoreV1Api()
        batch_v1 = client.BatchV1Api()

        nodes_resp = core_v1.list_node()
        nodes_json = [n.to_dict() for n in nodes_resp.items]

        list_kwargs: dict[str, Any] = {}
        if namespace:
            pods_resp = core_v1.list_namespaced_pod(namespace, **list_kwargs)
            events_resp = core_v1.list_namespaced_event(namespace)
        else:
            pods_resp = core_v1.list_pod_for_all_namespaces(**list_kwargs)
            events_resp = core_v1.list_event_for_all_namespaces()

        pods_json = [p.to_dict() for p in pods_resp.items]
        events_json = [e.to_dict() for e in events_resp.items]

        kueue_json: list[dict[str, Any]] = []
        try:
            custom_api = client.CustomObjectsApi()
            kueue_resp = custom_api.list_cluster_custom_object(
                group="kueue.x-k8s.io",
                version="v1beta1",
                plural="workloads",
            )
            kueue_json = kueue_resp.get("items", [])
        except Exception:
            logger.debug("Kueue not available or no workloads found")

        return cls(
            nodes_json=nodes_json,
            pods_json=pods_json,
            events_json=events_json,
            kueue_workloads_json=kueue_json,
            namespace_filter=namespace,
            **kwargs,
        )

    # -- public --

    def validate(self) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not self.nodes_json:
            issues.append(ValidationIssue(field="nodes", message="No node data provided"))
        if not self.pods_json:
            issues.append(ValidationIssue(field="pods", message="No pod data provided"))

        gpu_nodes = 0
        for node in self.nodes_json:
            capacity = _node_capacity(node)
            if capacity.get(GPU_RESOURCE_KEY, 0) > 0:
                gpu_nodes += 1
        if gpu_nodes == 0 and self.nodes_json:
            issues.append(ValidationIssue(field="nodes", message="No GPU nodes found in cluster"))

        gpu_pods = sum(1 for p in self.pods_json if _pod_gpu_count(p) > 0)
        if gpu_pods == 0 and self.pods_json:
            issues.append(ValidationIssue(field="pods", message="No GPU pods found"))

        return issues

    def build_dataset(self) -> ClusterDataset:
        nodes, gpus, node_gpu_type = self._build_nodes()
        gpu_by_node: dict[str, list[GPU]] = defaultdict(list)
        for gpu in gpus:
            gpu_by_node[gpu.node_id].append(gpu)

        event_index = self._index_events()
        kueue_index = self._index_kueue()

        jobs, allocations, decisions = self._build_jobs(
            gpu_by_node, node_gpu_type, event_index, kueue_index
        )

        total_gpus = len(gpus)
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
                    from natilah.ingestion.slurm import fetch_dcgm_samples
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
            source="kubernetes",
        )

    # -- internals --

    def _build_nodes(self) -> tuple[list[Node], list[GPU], dict[str, str]]:
        nodes: list[Node] = []
        gpus: list[GPU] = []
        node_gpu_type: dict[str, str] = {}

        for node_data in self.nodes_json:
            metadata = node_data.get("metadata", {})
            status = node_data.get("status", {})
            spec = node_data.get("spec", {})

            node_name = metadata.get("name", "")
            labels = metadata.get("labels", {})
            capacity = _node_capacity(node_data)
            gpu_count = capacity.get(GPU_RESOURCE_KEY, 0)

            if gpu_count == 0:
                continue

            catalog_name = self.gpu_type_override or resolve_gpu_type_from_labels(labels)
            node_gpu_type[node_name] = catalog_name
            gpu_type = GPU_TYPE_CATALOG.get(catalog_name)
            if gpu_type is None:
                gpu_type = GPUType(
                    name=catalog_name,
                    memory_gb=80.0,
                    tdp_watts=400.0,
                    compute_capability="8.0",
                    fp16_tflops=312.0,
                )

            allocatable = status.get("allocatable", {})
            mem_str = allocatable.get("memory", "0")
            memory_gb = _parse_k8s_memory(mem_str)
            cpu_str = allocatable.get("cpu", "0")
            cpu_cores = _parse_k8s_cpu(cpu_str)

            taints = spec.get("taints", [])
            node_labels = dict(labels)
            node_labels["source"] = "kubernetes"
            if taints:
                node_labels["taints"] = ",".join(
                    f"{t.get('key','')}={t.get('value','')}:{t.get('effect','')}"
                    for t in taints
                )

            nodes.append(
                Node(
                    node_id=node_name,
                    hostname=node_name,
                    gpu_count=gpu_count,
                    gpu_type=gpu_type,
                    total_memory_gb=memory_gb,
                    cpu_cores=cpu_cores,
                    labels=node_labels,
                )
            )
            for idx in range(gpu_count):
                gpus.append(
                    GPU(
                        gpu_id=f"{node_name}-gpu-{idx}",
                        gpu_type=gpu_type,
                        node_id=node_name,
                        gpu_index=idx,
                    )
                )

        return nodes, gpus, node_gpu_type

    def _build_jobs(
        self,
        gpu_by_node: dict[str, list[GPU]],
        node_gpu_type: dict[str, str],
        event_index: dict[str, list[dict[str, Any]]],
        kueue_index: dict[str, dict[str, Any]],
    ) -> tuple[list[Job], list[Allocation], list[SchedulerDecision]]:
        jobs: list[Job] = []
        allocations: list[Allocation] = []
        decisions: list[SchedulerDecision] = []

        for pod_data in self.pods_json:
            metadata = pod_data.get("metadata", {})
            spec = pod_data.get("spec", {})
            status = pod_data.get("status", {})

            namespace = metadata.get("namespace", "default")
            if self.namespace_filter and namespace != self.namespace_filter:
                continue

            pod_name = metadata.get("name", "")
            pod_uid = metadata.get("uid", "")
            gpu_count = pod_total_gpus(spec)
            if gpu_count == 0:
                continue

            creation_ts = parse_k8s_timestamp(metadata.get("creationTimestamp"))
            if creation_ts is None:
                continue

            phase = status.get("phase", "Unknown")
            state = POD_PHASE_MAP.get(phase, JobState.FAILED)

            start_time = _pod_start_time(status)
            end_time = _pod_end_time(status)

            owner_refs = metadata.get("ownerReferences", [])
            job_name = pod_name
            user = namespace
            if owner_refs:
                job_name = owner_refs[0].get("name", pod_name)
                user = f"{namespace}/{owner_refs[0].get('kind', 'Pod')}"

            labels = metadata.get("labels", {})
            annotations = metadata.get("annotations", {})

            constraints = extract_affinity(spec)
            constraints["namespace"] = namespace
            constraints["source"] = "kubernetes"
            if labels.get("kueue.x-k8s.io/queue-name"):
                constraints["kueue_queue"] = labels["kueue.x-k8s.io/queue-name"]

            node_name = spec.get("nodeName", "")
            requested_gpu_type = None
            if node_name and node_name in node_gpu_type:
                requested_gpu_type = node_gpu_type[node_name]
            elif self.gpu_type_override:
                requested_gpu_type = self.gpu_type_override

            job_id = pod_uid or f"{namespace}/{pod_name}"

            jobs.append(
                Job(
                    job_id=job_id,
                    name=job_name,
                    user=user,
                    submit_time=creation_ts,
                    start_time=start_time,
                    end_time=end_time,
                    state=state,
                    requested_gpus=gpu_count,
                    requested_gpu_type=requested_gpu_type,
                    priority=_pod_priority(spec),
                    constraints={k: str(v) for k, v in constraints.items()},
                )
            )

            if node_name and start_time:
                node_gpus = gpu_by_node.get(node_name, [])
                gpu_ids = [g.gpu_id for g in node_gpus[:gpu_count]]
                if not gpu_ids:
                    gpu_ids = [f"{node_name}-gpu-{i}" for i in range(gpu_count)]

                allocations.append(
                    Allocation(
                        allocation_id=f"alloc-{job_id}",
                        job_id=job_id,
                        gpu_ids=gpu_ids,
                        node_ids=[node_name],
                        start_time=start_time,
                        end_time=end_time,
                        decision_reason="k8s_scheduler_binding",
                    )
                )

                scheduling_reason = _get_scheduling_reason(event_index, pod_uid, pod_name, namespace)
                decisions.append(
                    SchedulerDecision(
                        decision_id=f"dec-{job_id}",
                        timestamp=start_time,
                        decision_type=DecisionType.PLACE,
                        job_id=job_id,
                        chosen_action={
                            "node": node_name,
                            "gpu_ids": gpu_ids,
                            "gpu_count": gpu_count,
                            "scheduler_reason": scheduling_reason,
                        },
                    )
                )

            if start_time and creation_ts:
                wait_seconds = (start_time - creation_ts).total_seconds()
                if wait_seconds > 300:
                    kueue_info = kueue_index.get(f"{namespace}/{job_name}", {})
                    decisions.append(
                        SchedulerDecision(
                            decision_id=f"dec-queue-{job_id}",
                            timestamp=creation_ts,
                            decision_type=DecisionType.QUEUE,
                            job_id=job_id,
                            chosen_action={
                                "queued_seconds": wait_seconds,
                                "kueue_queue": kueue_info.get("cluster_queue", ""),
                                "kueue_admitted_at": kueue_info.get("admitted_at", ""),
                            },
                        )
                    )

        return jobs, allocations, decisions

    def _index_events(self) -> dict[str, list[dict[str, Any]]]:
        """Index scheduling events by pod UID and namespace/name."""
        index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events_json:
            parsed = extract_scheduling_event(event)
            if parsed:
                uid = parsed.get("pod_uid", "")
                name_key = f"{parsed.get('namespace', '')}/{parsed.get('pod_name', '')}"
                if uid:
                    index[uid].append(parsed)
                if name_key:
                    index[name_key].append(parsed)
        return index

    def _index_kueue(self) -> dict[str, dict[str, Any]]:
        """Index Kueue workloads by namespace/owner-name."""
        index: dict[str, dict[str, Any]] = {}
        for wl in self.kueue_workloads_json:
            parsed = parse_kueue_workload(wl)
            if parsed:
                key = f"{parsed['namespace']}/{parsed['owner_name']}"
                index[key] = parsed
                name_key = f"{parsed['namespace']}/{parsed['name']}"
                index[name_key] = parsed
        return index

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


def _node_capacity(node_data: dict[str, Any]) -> dict[str, int]:
    """Get allocatable GPU count from node. Falls back to capacity."""
    status = node_data.get("status", {})
    allocatable = status.get("allocatable", {})
    capacity = status.get("capacity", {})
    result: dict[str, int] = {}
    gpu_str = allocatable.get(GPU_RESOURCE_KEY) or capacity.get(GPU_RESOURCE_KEY, "0")
    try:
        result[GPU_RESOURCE_KEY] = int(gpu_str)
    except (ValueError, TypeError):
        result[GPU_RESOURCE_KEY] = 0
    return result


def _pod_gpu_count(pod_data: dict[str, Any]) -> int:
    spec = pod_data.get("spec", {})
    return pod_total_gpus(spec)


def _parse_k8s_memory(mem_str: str) -> float:
    """Parse K8s memory string (Ki, Mi, Gi, Ti) to GB."""
    if not mem_str:
        return 0.0
    multipliers = {"Ki": 1 / (1024 * 1024), "Mi": 1 / 1024, "Gi": 1.0, "Ti": 1024.0}
    for suffix, mult in multipliers.items():
        if mem_str.endswith(suffix):
            try:
                return float(mem_str[: -len(suffix)]) * mult
            except ValueError:
                return 0.0
    try:
        return float(mem_str) / (1024**3)
    except ValueError:
        return 0.0


def _parse_k8s_cpu(cpu_str: str) -> int:
    """Parse K8s CPU string (millicores or cores) to cores."""
    if not cpu_str:
        return 0
    if cpu_str.endswith("m"):
        try:
            return int(cpu_str[:-1]) // 1000
        except ValueError:
            return 0
    try:
        return int(cpu_str)
    except ValueError:
        try:
            return int(float(cpu_str))
        except ValueError:
            return 0


def _pod_start_time(status: dict[str, Any]) -> datetime | None:
    """Get pod start time from container statuses or startTime."""
    start = status.get("startTime")
    if start:
        return parse_k8s_timestamp(start)
    for cs in status.get("containerStatuses", []):
        state_info = cs.get("state", {})
        running = state_info.get("running", {})
        if running.get("startedAt"):
            return parse_k8s_timestamp(running["startedAt"])
        terminated = state_info.get("terminated", {})
        if terminated.get("startedAt"):
            return parse_k8s_timestamp(terminated["startedAt"])
    return None


def _pod_end_time(status: dict[str, Any]) -> datetime | None:
    """Get pod completion time from container statuses."""
    for cs in status.get("containerStatuses", []):
        state_info = cs.get("state", {})
        terminated = state_info.get("terminated", {})
        if terminated.get("finishedAt"):
            return parse_k8s_timestamp(terminated["finishedAt"])
    return None


def _pod_priority(spec: dict[str, Any]) -> int:
    """Extract priority from pod spec."""
    priority = spec.get("priority")
    if priority is not None:
        try:
            return int(priority)
        except (ValueError, TypeError):
            pass
    return 0


def _get_scheduling_reason(
    event_index: dict[str, list[dict[str, Any]]],
    pod_uid: str,
    pod_name: str,
    namespace: str,
) -> str:
    """Find the scheduling event reason for a pod."""
    events = event_index.get(pod_uid, []) or event_index.get(f"{namespace}/{pod_name}", [])
    for ev in events:
        if ev["reason"] == "Scheduled":
            return ev.get("message", "Scheduled")
    return "scheduled"


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
