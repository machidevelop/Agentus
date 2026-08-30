"""Translate technical X vs Y deltas into economic value. Every assumption is exposed."""

from __future__ import annotations

from natilah.config import DEFAULT_GPU_COSTS
from natilah.models.domain import (
    ClusterDataset,
    ComparisonResult,
    EconomicConfig,
    Observation,
    ValueEstimate,
)


def default_economic_config(overrides: dict[str, float] | None = None) -> EconomicConfig:
    costs = dict(DEFAULT_GPU_COSTS)
    if overrides:
        costs.update(overrides)
    return EconomicConfig(
        cost_per_gpu_hour=costs,
        gpu_acquisition_cost={
            "A100-80GB": 15000.0,
            "H100-80GB": 30000.0,
            "H200-141GB": 35000.0,
            "B200-192GB": 40000.0,
        },
        gpu_amortization_years=3.0,
        facility_cost_multiplier=1.4,
        working_hours_per_month=720.0,
    )


class ValueCalculator:
    def __init__(self, config: EconomicConfig | None = None):
        self.config = config or default_economic_config()

    def estimate(
        self,
        comparison: ComparisonResult,
        observation: Observation,
        dataset: ClusterDataset,
        analysis_hours: float | None = None,
        gpu_hours_override: float | None = None,
        extra_assumptions: list[str] | None = None,
    ) -> ValueEstimate:
        gpu_type = self._gpu_type(observation, dataset)
        rate = self.config.cost_per_gpu_hour.get(gpu_type, min(self.config.cost_per_gpu_hour.values() or [2.21]))
        gpu_hours = comparison.delta.gpu_hours_saved
        if gpu_hours_override is not None and gpu_hours_override > 0:
            # A specialized agent priced its own claim: exactly which GPUs, for
            # exactly how long. That claim is what the coordination layer
            # deduplicates, so value must be computed from the same number.
            gpu_hours = gpu_hours_override
        # Queue-time recovery also implies GPU-hours that could have been used.
        if gpu_hours <= 0 and comparison.delta.queue_time_reduction > 0:
            job = dataset.job_by_id().get(observation.decision.job_id)
            requested = job.requested_gpus if job else 1
            gpu_hours = (comparison.delta.queue_time_reduction / 3600.0) * requested
        if gpu_hours <= 0 and comparison.delta.idle_hours_recovered > 0:
            gpu_hours = comparison.delta.idle_hours_recovered

        if analysis_hours is None:
            jobs = dataset.jobs
            if jobs:
                start = min(j.submit_time for j in jobs)
                end = max((j.end_time or j.submit_time) for j in jobs)
                analysis_hours = max((end - start).total_seconds() / 3600.0, 1.0)
            else:
                analysis_hours = 24.0

        compute_cost = gpu_hours * rate
        equivalent = gpu_hours / analysis_hours
        hourly_savings = gpu_hours / analysis_hours * rate
        monthly = hourly_savings * self.config.working_hours_per_month
        annual = monthly * 12.0

        assumptions = [
            f"GPU type priced as {gpu_type} at ${rate:.2f} per GPU-hour (cloud reference, user-configurable).",
            "Value is the difference between observed decision X and feasible alternative Y, not a guarantee of future savings.",
            "Linear scaling of GPU-hours to monthly/annual value assumes a similar mix of work continues.",
            f"Analysis window is {analysis_hours:.1f} hours; monthly hours assumed {self.config.working_hours_per_month:.0f}.",
            f"Facility multiplier {self.config.facility_cost_multiplier} is recorded but not applied to the headline compute-cost figure.",
            "No production change is implied or performed.",
        ]
        if gpu_hours_override is not None and gpu_hours_override > 0:
            assumptions.insert(
                1,
                f"GPU-hours come from the agent's explicit resource claim ({gpu_hours:.2f} GPU-h), "
                "not from the generic comparator delta.",
            )
        if extra_assumptions:
            assumptions.extend(extra_assumptions)
        return ValueEstimate(
            gpu_hours_recovered=gpu_hours,
            compute_cost_avoided=compute_cost,
            equivalent_gpus_recovered=equivalent,
            estimated_monthly_value=monthly,
            estimated_annual_value=annual,
            assumptions=assumptions,
            cost_model_used=self.config,
            gpu_type=gpu_type,
        )

    def _gpu_type(self, observation: Observation, dataset: ClusterDataset) -> str:
        gpus = dataset.gpu_by_id()
        for gid in observation.affected_gpu_ids:
            if gid in gpus:
                return gpus[gid].gpu_type.name
        job = dataset.job_by_id().get(observation.decision.job_id)
        if job and job.requested_gpu_type:
            return job.requested_gpu_type
        return next(iter(self.config.cost_per_gpu_hour), "A100-80GB")
