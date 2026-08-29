from __future__ import annotations

from natilah.engine.comparator import Comparator
from natilah.engine.opportunity_detector import DetectorRegistry
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.engine.value_calculator import ValueCalculator
from natilah.models.domain import Alternative, ClusterDataset


def test_value_calculator_projections(synthetic_dataset: ClusterDataset):
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    registry = DetectorRegistry()
    comparator = Comparator()
    calc = ValueCalculator()

    observations = registry.detect_all(synthetic_dataset, reconstructor)
    obs = observations[0]
    state = reconstructor.reconstruct(obs.timestamp)

    job_id = obs.affected_job_ids[0]
    alloc = synthetic_dataset.allocation_by_job()[job_id]

    alt = Alternative(
        alternative_id="alt-val-test",
        description="Sized down",
        proposed_action={"kind": "resize", "gpu_count": max(1, len(alloc.gpu_ids) - 1)},
        generation_method="test",
        agent_name="test",
        agent_rationale="val test",
    )

    comp = comparator.compare(obs, alt, synthetic_dataset, reconstructor, state)
    val = calc.estimate(comp, obs, synthetic_dataset)

    assert val.gpu_hours_recovered >= 0.0
    assert val.compute_cost_avoided >= 0.0
    assert val.estimated_monthly_value >= 0.0
    assert val.estimated_annual_value == val.estimated_monthly_value * 12.0
    assert len(val.assumptions) > 0
