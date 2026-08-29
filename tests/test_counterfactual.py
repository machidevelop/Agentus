from __future__ import annotations

from uuid import uuid4

from natilah.engine.counterfactual import CounterfactualValidator
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import Alternative, ClusterDataset


def test_counterfactual_validator_valid_and_invalid(synthetic_dataset: ClusterDataset):
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    validator = CounterfactualValidator()

    job = synthetic_dataset.jobs[0]
    alloc = synthetic_dataset.allocation_by_job().get(job.job_id)
    assert alloc is not None
    t0 = alloc.start_time
    state = reconstructor.reconstruct(t0)

    # Valid candidate alternative: same node, valid GPU IDs
    valid_alt = Alternative(
        alternative_id=str(uuid4()),
        description="Feasible placement test",
        proposed_action={
            "kind": "place",
            "gpu_count": len(alloc.gpu_ids),
            "gpu_ids": alloc.gpu_ids,
            "node_ids": alloc.node_ids,
        },
        generation_method="test",
        agent_name="test_agent",
        agent_rationale="Testing validator",
    )

    res_valid = validator.validate(valid_alt, job, state, synthetic_dataset, exclude_job_id=job.job_id)
    assert res_valid.feasible is True

    # Invalid candidate alternative: non-existent GPU ID
    invalid_alt = Alternative(
        alternative_id=str(uuid4()),
        description="Invalid GPU ID test",
        proposed_action={
            "kind": "place",
            "gpu_count": 1,
            "gpu_ids": ["non-existent-gpu-999"],
            "node_ids": ["non-existent-node"],
        },
        generation_method="test",
        agent_name="test_agent",
        agent_rationale="Testing validator failure",
    )

    res_invalid = validator.validate(invalid_alt, job, state, synthetic_dataset)
    assert res_invalid.feasible is False
    assert len(res_invalid.violations) > 0
