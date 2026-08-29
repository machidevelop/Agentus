from __future__ import annotations

from natilah.engine.confidence import ConfidenceScorer
from natilah.engine.opportunity_detector import DetectorRegistry
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import Alternative, ClusterDataset


def test_confidence_scorer(synthetic_dataset: ClusterDataset):
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    registry = DetectorRegistry()
    scorer = ConfidenceScorer()

    observations = registry.detect_all(synthetic_dataset, reconstructor)
    obs = observations[0]

    alt = Alternative(
        alternative_id="alt-conf-test",
        description="Confidence test alternative",
        proposed_action={"gpu_count": 2},
        generation_method="test",
        agent_name="test",
        agent_rationale="test",
    )

    checked = ["gpu_architecture_compatibility", "vram_capacity", "nvlink_single_node"]
    assessment = scorer.assess(obs, alt, synthetic_dataset, checked, similar_count=2)

    assert 0.0 <= assessment.score <= 1.0
    assert assessment.level in {"high", "medium", "low"}
    assert len(assessment.factors) == 5
    assert len(assessment.explanation) > 0
