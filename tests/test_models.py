from __future__ import annotations

from datetime import datetime, timezone

from natilah.models.domain import (
    GPU,
    GPU_TYPE_CATALOG,
    Allocation,
    GPUType,
    Job,
    Node,
    SchedulerDecision,
)
from natilah.models.enums import DecisionType, JobState, OpportunityType, SafetyMode


def test_gpu_catalog():
    assert "A100-80GB" in GPU_TYPE_CATALOG
    assert "H100-80GB" in GPU_TYPE_CATALOG
    a100 = GPU_TYPE_CATALOG["A100-80GB"]
    assert a100.memory_gb == 80.0
    assert a100.tdp_watts == 400.0


def test_domain_models_creation():
    gpu_type = GPU_TYPE_CATALOG["A100-80GB"]
    node = Node(
        node_id="node-01",
        hostname="gpu-node-01",
        gpu_count=8,
        gpu_type=gpu_type,
        total_memory_gb=640.0,
        cpu_cores=128,
    )
    gpu = GPU(
        gpu_id="node-01-gpu-0",
        gpu_type=gpu_type,
        node_id="node-01",
        gpu_index=0,
    )
    now = datetime.now(timezone.utc)
    job = Job(
        job_id="job-001",
        name="training-run",
        user="alice",
        submit_time=now,
        state=JobState.RUNNING,
        requested_gpus=4,
        requested_gpu_type="A100-80GB",
    )
    alloc = Allocation(
        allocation_id="alloc-001",
        job_id="job-001",
        gpu_ids=["node-01-gpu-0", "node-01-gpu-1"],
        node_ids=["node-01"],
        start_time=now,
    )
    decision = SchedulerDecision(
        decision_id="dec-001",
        timestamp=now,
        decision_type=DecisionType.ALLOCATE,
        job_id="job-001",
        chosen_action={"gpus": 4},
    )

    assert node.gpu_count == 8
    assert gpu.gpu_index == 0
    assert job.state == JobState.RUNNING
    assert len(alloc.gpu_ids) == 2
    assert decision.decision_type == DecisionType.ALLOCATE


def test_enums():
    assert JobState.PENDING == "pending"
    assert OpportunityType.OVER_ALLOCATION == "over_allocation"
    assert SafetyMode.READ_ONLY == "read_only"
