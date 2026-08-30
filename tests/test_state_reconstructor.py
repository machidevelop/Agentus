from __future__ import annotations

from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import ClusterDataset


def test_cluster_state_reconstructor(synthetic_dataset: ClusterDataset):
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    assert len(synthetic_dataset.allocations) > 0
    t0 = synthetic_dataset.allocations[0].start_time

    snapshot = reconstructor.reconstruct(t0)
    assert snapshot.timestamp == t0
    # Per-node states are built on demand, not on every reconstruction.
    assert snapshot.nodes == []
    assert len(snapshot.node_states()) == len(synthetic_dataset.nodes)
    assert snapshot.available_capacity.total_gpus == len(synthetic_dataset.gpus)
    assert snapshot.available_capacity.allocated_gpus + snapshot.available_capacity.idle_gpus == snapshot.available_capacity.total_gpus
    assert snapshot.available_capacity.largest_contiguous_block >= 0
    blocks = snapshot.available_capacity.blocks()
    assert all(b.size > 0 for b in blocks)
    assert max((b.size for b in blocks), default=0) == (
        snapshot.available_capacity.largest_contiguous_block
    )
