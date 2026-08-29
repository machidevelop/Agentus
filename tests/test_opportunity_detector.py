from __future__ import annotations

from natilah.engine.opportunity_detector import DetectorRegistry
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import ClusterDataset


def test_detector_registry_finds_signals(synthetic_dataset: ClusterDataset):
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    registry = DetectorRegistry()

    observations = registry.detect_all(synthetic_dataset, reconstructor)
    assert len(observations) > 0

    observed_types = {obs.signal_type for obs in observations}
    # At least some of the injected patterns should be detected
    assert len(observed_types) >= 1
