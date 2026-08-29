from __future__ import annotations

from uuid import uuid4

from natilah.engine.comparator import Comparator
from natilah.engine.opportunity_detector import DetectorRegistry
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import Alternative, ClusterDataset


def test_comparator_delta_calculation(synthetic_dataset: ClusterDataset):
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    registry = DetectorRegistry()
    comparator = Comparator()

    observations = registry.detect_all(synthetic_dataset, reconstructor)
    assert len(observations) > 0
    obs = observations[0]
    state = reconstructor.reconstruct(obs.timestamp)

    job_id = obs.decision.job_id
    alloc = synthetic_dataset.allocation_by_job().get(job_id)
    if not alloc:
        job_id = obs.affected_job_ids[0]
        alloc = synthetic_dataset.allocation_by_job().get(job_id)

    # Propose sizing down allocation by 1 GPU
    new_count = max(1, len(alloc.gpu_ids) - 1)
    alt = Alternative(
        alternative_id=str(uuid4()),
        description="Sized down alternative",
        proposed_action={
            "kind": "resize",
            "gpu_count": new_count,
            "gpu_ids": alloc.gpu_ids[:new_count],
            "original_gpu_count": len(alloc.gpu_ids),
        },
        generation_method="test",
        agent_name="test_agent",
        agent_rationale="Test resize comparison",
    )

    comp = comparator.compare(obs, alt, synthetic_dataset, reconstructor, state)
    assert comp.actual.gpu_hours >= comp.alternative.gpu_hours
    assert comp.delta.gpu_hours_saved >= 0.0
