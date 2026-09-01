"""Pricing for every meter the fleet accounts in.

The scheduling agents price GPU-hours through `ValueCalculator`. Every other
domain prices a different unit — a GB-month, a kWh, a dollar already committed
— and the platform's central promise is that those totals still add up. So all
of them run through one normalization:

    monthly value = (claimed quantity / analysis hours) x rate x hours per month

which is the same arithmetic the GPU path already uses. A 500 GB volume
orphaned for half of a 15-day window claims 250 GB-months, normalizes back to
500 GB-months per month, and prices at the tier rate — the number a finance
team would independently compute.
"""

from __future__ import annotations

from natilah.config import (
    DEFAULT_METER_RATES,
    DEFAULT_NETWORK_KIND_RATES,
    DEFAULT_STORAGE_TIER_RATES,
)
from natilah.models.domain import EconomicConfig, ResourceClaim, ValueEstimate
from natilah.models.enums import Meter


class MeterPricing:
    """Rate lookup and monthly normalization for non-GPU meters."""

    def __init__(self, config: EconomicConfig | None = None):
        self.config = config
        self.rates = dict(DEFAULT_METER_RATES)
        self.tier_rates = dict(DEFAULT_STORAGE_TIER_RATES)
        self.kind_rates = dict(DEFAULT_NETWORK_KIND_RATES)
        if config is not None and getattr(config, "meter_rates", None):
            self.rates.update(config.meter_rates)

    # ------------------------------------------------------------------ rates

    def rate_for(
        self,
        meter: Meter,
        tier: str | None = None,
        kind: str | None = None,
        gpu_rate: float | None = None,
    ) -> float:
        """Dollars per unit of `meter`, refined by tier or traffic kind."""
        if meter is Meter.GB_MONTHS and tier:
            return self.tier_rates.get(tier.lower(), self.rates["gb_months"])
        if meter is Meter.GB_TRANSFERRED and kind:
            return self.kind_rates.get(kind.lower(), self.rates["gb_transferred"])
        if meter is Meter.REPLICA_HOURS and gpu_rate:
            return gpu_rate
        if meter is Meter.GPU_HOURS and gpu_rate:
            return gpu_rate
        return self.rates.get(meter.value, 0.0)

    # ---------------------------------------------------------------- pricing

    def monthly_value(
        self,
        quantity: float,
        rate: float,
        analysis_hours: float,
        hours_per_month: float = 720.0,
    ) -> float:
        if analysis_hours <= 0:
            return 0.0
        return (quantity / analysis_hours) * rate * hours_per_month

    def estimate(
        self,
        claim: ResourceClaim,
        analysis_hours: float,
        economic_config: EconomicConfig,
        tier: str | None = None,
        kind: str | None = None,
        gpu_rate: float | None = None,
        rate_override: float | None = None,
        rate_explanation: str = "",
        extra_assumptions: list[str] | None = None,
    ) -> ValueEstimate:
        """Price a claim in its primary meter and express it as monthly value."""
        meter = claim.primary_meter
        quantity = claim.primary_quantity
        if rate_override is not None:
            rate = rate_override
        else:
            rate = self.rate_for(meter, tier=tier, kind=kind, gpu_rate=gpu_rate)
        hours_per_month = economic_config.working_hours_per_month
        monthly = self.monthly_value(quantity, rate, analysis_hours, hours_per_month)

        assumptions = [
            f"Metered in {meter.unit_label} at ${rate:,.4f} per {meter.unit_label} "
            "(cloud reference, user-configurable).",
            f"Claim of {quantity:,.2f} {meter.unit_label} comes from the agent's explicit "
            "resource claim, which is also what the coordination layer deduplicates.",
            f"Analysis window is {analysis_hours:.1f} hours; monthly hours assumed "
            f"{hours_per_month:.0f}.",
            "Value is the difference between what was observed and a feasible alternative, "
            "not a guarantee of future savings.",
            "No production change is implied or performed.",
        ]
        if rate_explanation:
            assumptions.insert(1, rate_explanation)
        if claim.basis:
            assumptions.append(f"Resource claim basis: {claim.basis}")
        if extra_assumptions:
            assumptions.extend(extra_assumptions)

        # GPU-hours stay the headline unit for cross-domain comparison only when
        # the claim is actually in GPU-hours; other meters report 0 there rather
        # than inventing an equivalence.
        gpu_hours = quantity if meter is Meter.GPU_HOURS else 0.0
        return ValueEstimate(
            gpu_hours_recovered=gpu_hours,
            compute_cost_avoided=quantity * rate,
            equivalent_gpus_recovered=(quantity / analysis_hours) if analysis_hours > 0 else 0.0,
            estimated_monthly_value=monthly,
            estimated_annual_value=monthly * 12.0,
            assumptions=assumptions,
            cost_model_used=economic_config,
            gpu_type=None,
        )
