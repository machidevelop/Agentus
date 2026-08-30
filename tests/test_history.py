from __future__ import annotations

from natilah.engine.history import HistoricalPatternIndex, job_family
from natilah.engine.opportunity_detector import DetectorRegistry
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.models.domain import ClusterDataset
from natilah.models.enums import OpportunityType


def test_job_family_collapses_run_numbers(synthetic_dataset: ClusterDataset):
    job = synthetic_dataset.jobs[0].model_copy(update={"name": "ml-train-047"})
    assert job_family(job) == "ml-train-#"
    hashed = job.model_copy(update={"name": "infer-9f3ab21c-3"})
    assert job_family(hashed) == "infer-#-#"


def test_index_profiles_every_job(synthetic_dataset: ClusterDataset):
    index = HistoricalPatternIndex(synthetic_dataset)
    assert len(index.profiles) == len(synthetic_dataset.jobs)
    profile = index.profiles[synthetic_dataset.jobs[0].job_id]
    assert profile.allocated_gpus >= 1
    assert profile.mean_utilization >= 0.0
    assert index.by_user[profile.user].jobs >= 1


def test_recurrence_counts_signals_within_a_family(synthetic_dataset: ClusterDataset):
    index = HistoricalPatternIndex(synthetic_dataset)
    reconstructor = ClusterStateReconstructor(synthetic_dataset)
    observations = DetectorRegistry().detect_all(synthetic_dataset, reconstructor)
    index.register_observations(observations)

    counted = {
        obs.decision.job_id: index.recurrence(obs.decision.job_id, obs.signal_type)
        for obs in observations
    }
    assert counted
    assert all(value >= 0 for value in counted.values())
    assert any(value > 0 for value in counted.values()), "repeated job families should recur"


def test_evidence_reports_family_and_user_context(synthetic_dataset: ClusterDataset):
    index = HistoricalPatternIndex(synthetic_dataset)
    job_id = synthetic_dataset.jobs[0].job_id
    evidence = index.evidence(job_id, OpportunityType.IDLE_ALLOCATION)
    assert evidence["available"] is True
    for key in (
        "job_family",
        "family_jobs_in_window",
        "user_mean_utilization_pct",
        "this_job_mean_utilization_pct",
        "signal_recurrence_in_family",
    ):
        assert key in evidence
    assert index.evidence("does-not-exist", OpportunityType.IDLE_ALLOCATION) == {"available": False}
