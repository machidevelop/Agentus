"""Counterfactual container and operational feasibility checks.

This module does not generate alternative decisions. Agents propose Y;
this layer only asks whether Y was feasible in the reconstructed state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from natilah.models.domain import Alternative, ClusterDataset, ClusterStateSnapshot, Job


@dataclass
class FeasibilityResult:
    feasible: bool
    constraints_checked: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


class CounterfactualValidator:
    """Hard constraint validation for agent-proposed alternatives."""

    def validate(
        self,
        alternative: Alternative,
        job: Job,
        state: ClusterStateSnapshot,
        dataset: ClusterDataset,
        *,
        exclude_job_id: str | None = None,
    ) -> FeasibilityResult:
        action = alternative.proposed_action or {}
        checked: list[str] = []
        violations: list[str] = []

        gpu_ids = list(action.get("gpu_ids") or [])
        node_ids = list(action.get("node_ids") or [])
        requested = int(action.get("gpu_count") or action.get("requested_gpus") or job.requested_gpus)

        gpus_by_id = dataset.gpu_by_id()
        nodes_by_id = dataset.node_by_id()

        checked.append("gpu_identity")
        for gid in gpu_ids:
            if gid not in gpus_by_id:
                violations.append(f"Unknown GPU {gid}")

        checked.append("node_identity")
        for nid in node_ids:
            if nid not in nodes_by_id:
                violations.append(f"Unknown node {nid}")

        if gpu_ids:
            checked.append("gpu_count_matches_ids")
            if len(gpu_ids) != requested and "gpu_count" in action:
                if len(gpu_ids) != int(action["gpu_count"]):
                    violations.append("gpu_ids length does not match gpu_count")

            checked.append("gpu_architecture_compatibility")
            required_type = job.requested_gpu_type
            if required_type:
                for gid in gpu_ids:
                    gpu = gpus_by_id.get(gid)
                    if gpu and gpu.gpu_type.name != required_type:
                        violations.append(
                            f"GPU {gid} is {gpu.gpu_type.name}, job requires {required_type}"
                        )

            checked.append("vram_capacity")
            mem_needed = float(job.constraints.get("min_memory_gb", 0) or 0)
            if mem_needed:
                for gid in gpu_ids:
                    gpu = gpus_by_id.get(gid)
                    if gpu and gpu.gpu_type.memory_gb < mem_needed:
                        violations.append(
                            f"GPU {gid} has {gpu.gpu_type.memory_gb}GB, job needs {mem_needed}GB"
                        )

            checked.append("gpus_idle_at_decision_time")
            occupier = state.gpu_allocations
            for gid in gpu_ids:
                holder = occupier.get(gid)
                if holder and holder != exclude_job_id and holder != job.job_id:
                    violations.append(f"GPU {gid} was allocated to {holder} at decision time")

            checked.append("nvlink_single_node")
            nvlink = job.constraints.get("nvlink") == "required" or action.get("require_single_node")
            derived_nodes = {gpus_by_id[gid].node_id for gid in gpu_ids if gid in gpus_by_id}
            if nvlink and len(derived_nodes) > 1:
                violations.append("Tensor-parallel / NVLink job cannot span multiple nodes")
            if node_ids and derived_nodes and set(node_ids) != derived_nodes:
                # Node list should match the GPUs chosen.
                extra = set(node_ids) - derived_nodes
                missing = derived_nodes - set(node_ids)
                if extra or missing:
                    violations.append("node_ids do not match gpu_ids topology")

        if action.get("kind") == "reorder" or action.get("start_job_id"):
            checked.append("queued_job_exists")
            start_id = action.get("start_job_id") or action.get("unblocked_job_id")
            if start_id and start_id not in dataset.job_by_id():
                violations.append(f"Unknown queued job {start_id}")

        if action.get("kind") == "release_gpus":
            checked.append("release_subset_of_allocation")
            current = dataset.allocation_by_job().get(job.job_id)
            if current:
                releasing = set(action.get("release_gpu_ids") or [])
                if releasing - set(current.gpu_ids):
                    violations.append("Cannot release GPUs that were not in the observed allocation")

        return FeasibilityResult(
            feasible=len(violations) == 0,
            constraints_checked=checked,
            violations=violations,
        )


class CounterfactualEngine:
    """Keeps the counterfactual record; generation is the agent's job."""

    def __init__(self):
        self.validator = CounterfactualValidator()

    def validate(self, *args, **kwargs) -> FeasibilityResult:
        return self.validator.validate(*args, **kwargs)
