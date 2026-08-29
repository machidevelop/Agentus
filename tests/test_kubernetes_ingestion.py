"""Tests for the Kubernetes connector: parsing, dataset build, and full pipeline integration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from natilah.ingestion.kubernetes import (
    KubernetesDataSource,
    extract_affinity,
    extract_gpu_count,
    extract_scheduling_event,
    parse_k8s_timestamp,
    parse_kueue_workload,
    pod_total_gpus,
    resolve_gpu_type_from_labels,
)
from natilah.models.database import Base
from natilah.models.enums import DecisionType


# ---------------------------------------------------------------------------
# Fixtures: realistic K8s JSON structures
# ---------------------------------------------------------------------------

SAMPLE_NODES = [
    {
        "metadata": {
            "name": "gpu-node-01",
            "labels": {
                "nvidia.com/gpu.product": "NVIDIA-A100-SXM4-80GB",
                "topology.kubernetes.io/zone": "us-east-1a",
            },
        },
        "spec": {"taints": [{"key": "nvidia.com/gpu", "effect": "NoSchedule", "value": "present"}]},
        "status": {
            "capacity": {"nvidia.com/gpu": "8", "cpu": "64", "memory": "524288Mi"},
            "allocatable": {"nvidia.com/gpu": "8", "cpu": "62", "memory": "500000Mi"},
        },
    },
    {
        "metadata": {
            "name": "gpu-node-02",
            "labels": {
                "nvidia.com/gpu.product": "NVIDIA-A100-SXM4-80GB",
                "topology.kubernetes.io/zone": "us-east-1b",
            },
        },
        "spec": {"taints": [{"key": "nvidia.com/gpu", "effect": "NoSchedule", "value": "present"}]},
        "status": {
            "capacity": {"nvidia.com/gpu": "8", "cpu": "64", "memory": "524288Mi"},
            "allocatable": {"nvidia.com/gpu": "8", "cpu": "62", "memory": "500000Mi"},
        },
    },
    {
        "metadata": {
            "name": "gpu-node-03",
            "labels": {
                "nvidia.com/gpu.product": "NVIDIA-H100-SXM5-80GB",
                "topology.kubernetes.io/zone": "us-east-1a",
            },
        },
        "spec": {},
        "status": {
            "capacity": {"nvidia.com/gpu": "8", "cpu": "128", "memory": "1048576Mi"},
            "allocatable": {"nvidia.com/gpu": "8", "cpu": "126", "memory": "1000000Mi"},
        },
    },
    {
        "metadata": {"name": "cpu-node-01", "labels": {}},
        "spec": {},
        "status": {
            "capacity": {"cpu": "96", "memory": "262144Mi"},
            "allocatable": {"cpu": "94", "memory": "250000Mi"},
        },
    },
]

SAMPLE_PODS = [
    {
        "metadata": {
            "name": "train-gpt-0",
            "namespace": "ml-team",
            "uid": "uid-1001",
            "creationTimestamp": "2026-08-22T08:00:00Z",
            "ownerReferences": [{"kind": "Job", "name": "train-gpt"}],
            "labels": {},
        },
        "spec": {
            "nodeName": "gpu-node-01",
            "containers": [
                {"name": "trainer", "resources": {"requests": {"nvidia.com/gpu": "8"}, "limits": {"nvidia.com/gpu": "8"}}}
            ],
            "nodeSelector": {"nvidia.com/gpu.product": "NVIDIA-A100-SXM4-80GB"},
            "tolerations": [{"key": "nvidia.com/gpu", "effect": "NoSchedule", "operator": "Exists"}],
            "priority": 1000,
        },
        "status": {
            "phase": "Succeeded",
            "startTime": "2026-08-22T08:05:00Z",
            "containerStatuses": [
                {"state": {"terminated": {"startedAt": "2026-08-22T08:05:00Z", "finishedAt": "2026-08-22T16:00:00Z"}}}
            ],
        },
    },
    {
        "metadata": {
            "name": "inference-server-abc12",
            "namespace": "ml-team",
            "uid": "uid-1002",
            "creationTimestamp": "2026-08-22T09:00:00Z",
            "ownerReferences": [{"kind": "Deployment", "name": "inference-server"}],
            "labels": {},
        },
        "spec": {
            "nodeName": "gpu-node-02",
            "containers": [
                {"name": "serve", "resources": {"requests": {"nvidia.com/gpu": "2"}, "limits": {"nvidia.com/gpu": "2"}}}
            ],
            "tolerations": [{"key": "nvidia.com/gpu", "effect": "NoSchedule", "operator": "Exists"}],
        },
        "status": {
            "phase": "Running",
            "startTime": "2026-08-22T09:02:00Z",
            "containerStatuses": [
                {"state": {"running": {"startedAt": "2026-08-22T09:02:00Z"}}}
            ],
        },
    },
    {
        "metadata": {
            "name": "finetune-llm-0",
            "namespace": "research",
            "uid": "uid-1003",
            "creationTimestamp": "2026-08-22T10:00:00Z",
            "ownerReferences": [{"kind": "Job", "name": "finetune-llm"}],
            "labels": {"kueue.x-k8s.io/queue-name": "research-queue"},
        },
        "spec": {
            "nodeName": "gpu-node-02",
            "containers": [
                {"name": "finetune", "resources": {"requests": {"nvidia.com/gpu": "4"}, "limits": {"nvidia.com/gpu": "4"}}}
            ],
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {"matchExpressions": [{"key": "nvidia.com/gpu.product", "operator": "In", "values": ["NVIDIA-A100-SXM4-80GB"]}]}
                        ]
                    }
                }
            },
            "tolerations": [{"key": "nvidia.com/gpu", "effect": "NoSchedule", "operator": "Exists"}],
        },
        "status": {
            "phase": "Succeeded",
            "startTime": "2026-08-22T11:00:00Z",
            "containerStatuses": [
                {"state": {"terminated": {"startedAt": "2026-08-22T11:00:00Z", "finishedAt": "2026-08-22T18:00:00Z"}}}
            ],
        },
    },
    {
        "metadata": {
            "name": "eval-bench-0",
            "namespace": "ml-team",
            "uid": "uid-1004",
            "creationTimestamp": "2026-08-22T11:30:00Z",
            "ownerReferences": [{"kind": "Job", "name": "eval-bench"}],
            "labels": {},
        },
        "spec": {
            "nodeName": "gpu-node-03",
            "containers": [
                {"name": "eval", "resources": {"requests": {"nvidia.com/gpu": "8"}, "limits": {"nvidia.com/gpu": "8"}}}
            ],
            "tolerations": [],
        },
        "status": {
            "phase": "Succeeded",
            "startTime": "2026-08-22T12:15:00Z",
            "containerStatuses": [
                {"state": {"terminated": {"startedAt": "2026-08-22T12:15:00Z", "finishedAt": "2026-08-22T14:00:00Z"}}}
            ],
        },
    },
    {
        "metadata": {
            "name": "data-prep-xyz",
            "namespace": "ml-team",
            "uid": "uid-1005",
            "creationTimestamp": "2026-08-22T14:00:00Z",
            "ownerReferences": [{"kind": "Job", "name": "data-prep"}],
            "labels": {},
        },
        "spec": {
            "nodeName": "gpu-node-01",
            "containers": [
                {"name": "prep", "resources": {"requests": {"nvidia.com/gpu": "1"}, "limits": {"nvidia.com/gpu": "1"}}}
            ],
            "tolerations": [{"key": "nvidia.com/gpu", "effect": "NoSchedule", "operator": "Exists"}],
        },
        "status": {
            "phase": "Succeeded",
            "startTime": "2026-08-22T14:01:00Z",
            "containerStatuses": [
                {"state": {"terminated": {"startedAt": "2026-08-22T14:01:00Z", "finishedAt": "2026-08-22T15:00:00Z"}}}
            ],
        },
    },
    {
        "metadata": {
            "name": "long-wait-pod-0",
            "namespace": "batch",
            "uid": "uid-1006",
            "creationTimestamp": "2026-08-22T06:00:00Z",
            "ownerReferences": [{"kind": "Job", "name": "long-wait-pod"}],
            "labels": {},
        },
        "spec": {
            "nodeName": "gpu-node-01",
            "containers": [
                {"name": "compute", "resources": {"requests": {"nvidia.com/gpu": "2"}, "limits": {"nvidia.com/gpu": "2"}}}
            ],
            "tolerations": [{"key": "nvidia.com/gpu", "effect": "NoSchedule", "operator": "Exists"}],
        },
        "status": {
            "phase": "Succeeded",
            "startTime": "2026-08-22T08:30:00Z",
            "containerStatuses": [
                {"state": {"terminated": {"startedAt": "2026-08-22T08:30:00Z", "finishedAt": "2026-08-22T09:30:00Z"}}}
            ],
        },
    },
    # Non-GPU pod — should be ignored
    {
        "metadata": {
            "name": "web-server-abc",
            "namespace": "default",
            "uid": "uid-9999",
            "creationTimestamp": "2026-08-22T01:00:00Z",
            "labels": {},
        },
        "spec": {
            "nodeName": "cpu-node-01",
            "containers": [
                {"name": "web", "resources": {"requests": {"cpu": "2", "memory": "4Gi"}}}
            ],
        },
        "status": {"phase": "Running", "startTime": "2026-08-22T01:01:00Z"},
    },
]

SAMPLE_EVENTS = [
    {
        "reason": "Scheduled",
        "message": "Successfully assigned ml-team/train-gpt-0 to gpu-node-01",
        "involvedObject": {"name": "train-gpt-0", "namespace": "ml-team", "uid": "uid-1001"},
        "firstTimestamp": "2026-08-22T08:05:00Z",
    },
    {
        "reason": "FailedScheduling",
        "message": "0/4 nodes are available: 3 Insufficient nvidia.com/gpu, 1 node(s) had untolerated taint",
        "involvedObject": {"name": "eval-bench-0", "namespace": "ml-team", "uid": "uid-1004"},
        "firstTimestamp": "2026-08-22T11:30:00Z",
    },
    {
        "reason": "Scheduled",
        "message": "Successfully assigned ml-team/eval-bench-0 to gpu-node-03",
        "involvedObject": {"name": "eval-bench-0", "namespace": "ml-team", "uid": "uid-1004"},
        "firstTimestamp": "2026-08-22T12:15:00Z",
    },
]

SAMPLE_KUEUE_WORKLOAD = {
    "metadata": {
        "name": "finetune-llm-wl",
        "namespace": "research",
        "creationTimestamp": "2026-08-22T10:00:00Z",
        "ownerReferences": [{"kind": "Job", "name": "finetune-llm"}],
    },
    "spec": {
        "podSets": [
            {
                "template": {
                    "spec": {
                        "containers": [
                            {"name": "main", "resources": {"requests": {"nvidia.com/gpu": "4"}}}
                        ]
                    }
                }
            }
        ]
    },
    "status": {
        "admission": {"clusterQueue": "gpu-cluster-queue"},
        "conditions": [
            {"type": "Admitted", "status": "True", "lastTransitionTime": "2026-08-22T10:45:00Z"}
        ],
    },
}


# ---------------------------------------------------------------------------
# Unit tests: parsing helpers
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_iso_with_z(self):
        ts = parse_k8s_timestamp("2026-08-22T08:00:00Z")
        assert ts == datetime(2026, 8, 22, 8, 0, 0, tzinfo=timezone.utc)

    def test_iso_with_tz(self):
        ts = parse_k8s_timestamp("2026-08-22T08:00:00+00:00")
        assert ts is not None
        assert ts.tzinfo is not None

    def test_none(self):
        assert parse_k8s_timestamp(None) is None
        assert parse_k8s_timestamp("") is None


class TestResolveGpuType:
    def test_a100_label(self):
        labels = {"nvidia.com/gpu.product": "NVIDIA-A100-SXM4-80GB"}
        assert resolve_gpu_type_from_labels(labels) == "A100-80GB"

    def test_h100_label(self):
        labels = {"nvidia.com/gpu.product": "NVIDIA-H100-SXM5-80GB"}
        assert resolve_gpu_type_from_labels(labels) == "H100-80GB"

    def test_generic_label(self):
        labels = {"accelerator": "a100"}
        assert resolve_gpu_type_from_labels(labels) == "A100-80GB"

    def test_no_label(self):
        assert resolve_gpu_type_from_labels({}) == "A100-80GB"


class TestExtractGpuCount:
    def test_from_requests(self):
        container = {"resources": {"requests": {"nvidia.com/gpu": "4"}}}
        assert extract_gpu_count(container) == 4

    def test_from_limits(self):
        container = {"resources": {"limits": {"nvidia.com/gpu": "2"}}}
        assert extract_gpu_count(container) == 2

    def test_no_gpu(self):
        container = {"resources": {"requests": {"cpu": "4", "memory": "8Gi"}}}
        assert extract_gpu_count(container) == 0

    def test_empty(self):
        assert extract_gpu_count({}) == 0


class TestPodTotalGpus:
    def test_single_container(self):
        spec = {"containers": [{"resources": {"requests": {"nvidia.com/gpu": "8"}}}]}
        assert pod_total_gpus(spec) == 8

    def test_multi_container(self):
        spec = {
            "containers": [
                {"resources": {"requests": {"nvidia.com/gpu": "4"}}},
                {"resources": {"requests": {"nvidia.com/gpu": "2"}}},
            ]
        }
        assert pod_total_gpus(spec) == 6

    def test_init_containers(self):
        spec = {
            "containers": [{"resources": {"requests": {"nvidia.com/gpu": "4"}}}],
            "initContainers": [{"resources": {"requests": {"nvidia.com/gpu": "1"}}}],
        }
        assert pod_total_gpus(spec) == 5


class TestExtractAffinity:
    def test_node_selector(self):
        spec = {"nodeSelector": {"nvidia.com/gpu.product": "NVIDIA-A100-SXM4-80GB"}}
        result = extract_affinity(spec)
        assert "nodeSelector" in result
        assert result["nodeSelector"]["nvidia.com/gpu.product"] == "NVIDIA-A100-SXM4-80GB"

    def test_required_affinity(self):
        spec = {
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {"matchExpressions": [{"key": "gpu-type", "operator": "In", "values": ["a100"]}]}
                        ]
                    }
                }
            }
        }
        result = extract_affinity(spec)
        assert "requiredNodeAffinity" in result

    def test_gpu_tolerations(self):
        spec = {
            "tolerations": [
                {"key": "nvidia.com/gpu", "effect": "NoSchedule", "operator": "Exists"},
                {"key": "node.kubernetes.io/not-ready", "effect": "NoExecute"},
            ]
        }
        result = extract_affinity(spec)
        assert "gpuTolerations" in result
        assert len(result["gpuTolerations"]) == 1

    def test_empty(self):
        assert extract_affinity({}) == {}


class TestExtractSchedulingEvent:
    def test_scheduled(self):
        event = {
            "reason": "Scheduled",
            "message": "Assigned pod to gpu-node-01",
            "involvedObject": {"name": "pod-1", "namespace": "ns", "uid": "uid-1"},
            "firstTimestamp": "2026-08-22T10:00:00Z",
        }
        result = extract_scheduling_event(event)
        assert result is not None
        assert result["reason"] == "Scheduled"
        assert result["pod_name"] == "pod-1"

    def test_failed_scheduling(self):
        event = {
            "reason": "FailedScheduling",
            "message": "Insufficient GPU",
            "involvedObject": {"name": "pod-2", "namespace": "ns", "uid": "uid-2"},
            "firstTimestamp": "2026-08-22T10:00:00Z",
        }
        result = extract_scheduling_event(event)
        assert result is not None
        assert result["reason"] == "FailedScheduling"

    def test_irrelevant_event(self):
        event = {"reason": "Pulled", "message": "Image pulled", "involvedObject": {"name": "pod-3"}}
        assert extract_scheduling_event(event) is None


class TestParseKueueWorkload:
    def test_basic(self):
        result = parse_kueue_workload(SAMPLE_KUEUE_WORKLOAD)
        assert result is not None
        assert result["name"] == "finetune-llm-wl"
        assert result["namespace"] == "research"
        assert result["gpu_count"] == 4
        assert result["cluster_queue"] == "gpu-cluster-queue"
        assert result["admitted_at"] == "2026-08-22T10:45:00Z"
        assert result["owner_name"] == "finetune-llm"

    def test_empty(self):
        assert parse_kueue_workload({"metadata": {}}) is None


# ---------------------------------------------------------------------------
# Integration: KubernetesDataSource.build_dataset
# ---------------------------------------------------------------------------


class TestKubernetesDatasetBuild:
    def test_builds_gpu_nodes_only(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        assert len(ds.nodes) == 3
        assert all(n.gpu_count == 8 for n in ds.nodes)
        node_names = {n.node_id for n in ds.nodes}
        assert "cpu-node-01" not in node_names

    def test_builds_correct_gpu_count(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        assert len(ds.gpus) == 24  # 3 GPU nodes × 8 GPUs

    def test_gpu_type_detection(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        node_types = {n.node_id: n.gpu_type.name for n in ds.nodes}
        assert node_types["gpu-node-01"] == "A100-80GB"
        assert node_types["gpu-node-02"] == "A100-80GB"
        assert node_types["gpu-node-03"] == "H100-80GB"

    def test_filters_gpu_pods_only(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        assert len(ds.jobs) == 6
        assert all(j.requested_gpus > 0 for j in ds.jobs)

    def test_builds_allocations(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        assert len(ds.allocations) == 6
        alloc_1001 = next(a for a in ds.allocations if a.job_id == "uid-1001")
        assert alloc_1001.node_ids == ["gpu-node-01"]
        assert len(alloc_1001.gpu_ids) == 8

    def test_placement_decisions(self):
        source = KubernetesDataSource(
            nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS, events_json=SAMPLE_EVENTS
        )
        ds = source.build_dataset()
        place_decs = [d for d in ds.decisions if d.decision_type == DecisionType.PLACE]
        assert len(place_decs) == 6

    def test_queue_decisions_for_long_waits(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        queue_decs = [d for d in ds.decisions if d.decision_type == DecisionType.QUEUE]
        waited_jobs = {d.job_id for d in queue_decs}
        assert "uid-1003" in waited_jobs  # 60 min wait
        assert "uid-1006" in waited_jobs  # 150 min wait
        assert "uid-1004" in waited_jobs  # 45 min wait

    def test_kueue_metadata_in_decisions(self):
        source = KubernetesDataSource(
            nodes_json=SAMPLE_NODES,
            pods_json=SAMPLE_PODS,
            kueue_workloads_json=[SAMPLE_KUEUE_WORKLOAD],
        )
        ds = source.build_dataset()
        queue_dec_1003 = next(
            (d for d in ds.decisions if d.decision_type == DecisionType.QUEUE and d.job_id == "uid-1003"),
            None,
        )
        assert queue_dec_1003 is not None
        assert queue_dec_1003.chosen_action.get("kueue_queue") == "gpu-cluster-queue"

    def test_scheduling_event_context(self):
        source = KubernetesDataSource(
            nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS, events_json=SAMPLE_EVENTS
        )
        ds = source.build_dataset()
        dec_1001 = next(
            (d for d in ds.decisions if d.decision_type == DecisionType.PLACE and d.job_id == "uid-1001"),
            None,
        )
        assert dec_1001 is not None
        assert "Successfully assigned" in dec_1001.chosen_action.get("scheduler_reason", "")

    def test_synthesizes_queue_snapshots(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        assert len(ds.queue_snapshots) > 0
        assert all(q.total_gpus == 24 for q in ds.queue_snapshots)

    def test_namespace_filter(self):
        source = KubernetesDataSource(
            nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS, namespace_filter="ml-team"
        )
        ds = source.build_dataset()
        assert all("ml-team" in j.constraints.get("namespace", "") for j in ds.jobs)

    def test_gpu_type_override(self):
        source = KubernetesDataSource(
            nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS, gpu_type_override="H100-80GB"
        )
        ds = source.build_dataset()
        assert all(n.gpu_type.name == "H100-80GB" for n in ds.nodes)

    def test_validation(self):
        source = KubernetesDataSource(nodes_json=[], pods_json=[])
        issues = source.validate()
        assert len(issues) >= 2
        fields = {i.field for i in issues}
        assert "nodes" in fields
        assert "pods" in fields

    def test_validation_no_gpu_nodes(self):
        cpu_only = [SAMPLE_NODES[3]]
        source = KubernetesDataSource(nodes_json=cpu_only, pods_json=SAMPLE_PODS)
        issues = source.validate()
        assert any("No GPU nodes" in i.message for i in issues)

    def test_constraints_capture_affinity(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        job_1001 = next(j for j in ds.jobs if j.job_id == "uid-1001")
        assert "nvidia.com/gpu.product" in str(job_1001.constraints)

    def test_constraints_capture_kueue_queue(self):
        source = KubernetesDataSource(nodes_json=SAMPLE_NODES, pods_json=SAMPLE_PODS)
        ds = source.build_dataset()
        job_1003 = next(j for j in ds.jobs if j.job_id == "uid-1003")
        assert job_1003.constraints.get("kueue_queue") == "research-queue"


# ---------------------------------------------------------------------------
# Integration: full pipeline (K8s → ingest → analyze → findings)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def k8s_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def k8s_session(k8s_engine: AsyncEngine) -> AsyncSession:
    factory = sessionmaker(k8s_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


async def test_k8s_ingest_and_analyze(k8s_session: AsyncSession):
    """Acceptance test: K8s data → ingest → full pipeline → findings produced."""
    source = KubernetesDataSource(
        nodes_json=SAMPLE_NODES,
        pods_json=SAMPLE_PODS,
        events_json=SAMPLE_EVENTS,
        kueue_workloads_json=[SAMPLE_KUEUE_WORKLOAD],
    )
    result = await source.ingest(k8s_session)

    assert result.source == "kubernetes"
    assert result.nodes == 3
    assert result.gpus == 24
    assert result.jobs == 6
    assert result.allocations == 6

    from natilah.agents.gpu_allocation_agent import GPUAllocationAgent

    agent = GPUAllocationAgent()
    findings = await agent.analyze(k8s_session)

    assert len(findings) > 0, "Pipeline must produce at least one finding from K8s data"
    for f in findings:
        assert f.value.estimated_monthly_value >= 0
        assert f.confidence.score > 0
        assert f.alternative.agent_name == "gpu_allocation"
        assert len(f.alternative.constraints_satisfied) > 0
