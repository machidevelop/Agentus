"""Tests for the generalized meter accounting.

The platform's central promise is that totals still add up once many agents
watch many different costs. These tests pin the three properties that promise
rests on: a meter converts to money the way a finance team would compute it,
the same waste claimed twice is credited once, and two different meters never
touch each other.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from natilah.engine.claim import ClaimLedger
from natilah.engine.meters import MeterPricing
from natilah.engine.value_calculator import default_economic_config
from natilah.models.domain import (
    GPUInterval,
    ResourceClaim,
    ResourceInterval,
    ResourceQuantity,
)
from natilah.models.enums import Meter

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
WINDOW_HOURS = 360.0  # 15 days


def gb_month_claim(resource_id: str = "vol-1", size_gb: float = 500.0, days: int = 15):
    return ResourceClaim(
        resource_intervals=[
            ResourceInterval(
                meter=Meter.GB_MONTHS,
                resource_id=resource_id,
                start=T0,
                end=T0 + timedelta(days=days),
                magnitude=size_gb,
            )
        ],
        primary_meter=Meter.GB_MONTHS,
        basis="orphaned volume",
    )


# ------------------------------------------------------------------ quantities


def test_interval_quantity_is_magnitude_times_duration():
    claim = gb_month_claim()
    # 500 GB held for half of a 30-day month.
    assert claim.primary_quantity == 250.0


def test_kwh_uses_hours_while_gb_months_uses_months():
    energy = ResourceInterval(
        meter=Meter.KWH,
        resource_id="gpu-0",
        start=T0,
        end=T0 + timedelta(hours=10),
        magnitude=0.4,  # kW
    )
    assert energy.quantity == 4.0

    storage = ResourceInterval(
        meter=Meter.GB_MONTHS,
        resource_id="vol-0",
        start=T0,
        end=T0 + timedelta(days=30),
        magnitude=100.0,
    )
    assert storage.quantity == 100.0


def test_meters_lists_only_what_is_charged():
    claim = ResourceClaim(
        intervals=[GPUInterval(gpu_id="g0", start=T0, end=T0 + timedelta(hours=1))],
        quantities=[
            ResourceQuantity(meter=Meter.GB_TRANSFERRED, resource_id="flow-1", amount=10.0)
        ],
    )
    assert claim.meters() == [Meter.GPU_HOURS, Meter.GB_TRANSFERRED]
    assert claim.quantity(Meter.GB_TRANSFERRED) == 10.0
    assert claim.quantity(Meter.KWH) == 0.0


# --------------------------------------------------------------------- pricing


def test_orphaned_volume_prices_as_a_finance_team_would():
    """500 GB left orphaned costs 500 x tier rate every month it stays."""
    value = MeterPricing().estimate(
        gb_month_claim(),
        analysis_hours=WINDOW_HOURS,
        economic_config=default_economic_config(),
        tier="ssd",
    )
    assert round(value.estimated_monthly_value, 2) == 40.0  # 500 GB x $0.08
    assert round(value.estimated_annual_value, 2) == 480.0


def test_storage_tier_changes_the_rate():
    pricing = MeterPricing()
    config = default_economic_config()
    ssd = pricing.estimate(gb_month_claim(), WINDOW_HOURS, config, tier="ssd")
    archive = pricing.estimate(gb_month_claim(), WINDOW_HOURS, config, tier="archive")
    assert ssd.estimated_monthly_value > archive.estimated_monthly_value
    assert round(archive.estimated_monthly_value, 2) == 2.0  # 500 GB x $0.004


def test_network_prices_by_traffic_kind():
    claim = ResourceClaim(
        quantities=[
            ResourceQuantity(meter=Meter.GB_TRANSFERRED, resource_id="flow-1", amount=1000.0)
        ],
        primary_meter=Meter.GB_TRANSFERRED,
    )
    pricing = MeterPricing()
    config = default_economic_config()
    cross_az = pricing.estimate(claim, WINDOW_HOURS, config, kind="cross_az")
    egress = pricing.estimate(claim, WINDOW_HOURS, config, kind="egress")
    # Same bytes, but leaving the cloud costs 4.5x crossing a zone.
    assert round(egress.estimated_monthly_value / cross_az.estimated_monthly_value, 2) == 4.5


def test_rate_override_prices_a_delta():
    """Shifting load off-peak moves the same kWh at a cheaper rate."""
    claim = ResourceClaim(
        resource_intervals=[
            ResourceInterval(
                meter=Meter.KWH,
                resource_id="node-1",
                start=T0,
                end=T0 + timedelta(hours=10),
                magnitude=1.0,
            )
        ],
        primary_meter=Meter.KWH,
    )
    value = MeterPricing().estimate(
        claim,
        analysis_hours=10.0,
        economic_config=default_economic_config(),
        rate_override=0.05,
        rate_explanation="Peak $0.18/kWh less off-peak $0.13/kWh.",
    )
    # 10 kWh over a 10h window -> 720 kWh/month at the $0.05 delta.
    assert round(value.estimated_monthly_value, 2) == 36.0
    assert any("Peak $0.18" in a for a in value.assumptions)


def test_non_gpu_meters_do_not_invent_gpu_hours():
    value = MeterPricing().estimate(
        gb_month_claim(), WINDOW_HOURS, default_economic_config(), tier="ssd"
    )
    assert value.gpu_hours_recovered == 0.0


# ---------------------------------------------------------------------- ledger


def test_same_storage_claimed_twice_is_credited_once():
    ledger = ClaimLedger()
    first = ledger.attribute("f1", gb_month_claim())
    second = ledger.attribute("f2", gb_month_claim())

    assert first.per_meter[Meter.GB_MONTHS].attributed == 250.0
    assert first.value_ratio == 1.0
    assert second.per_meter[Meter.GB_MONTHS].attributed == 0.0
    assert second.value_ratio == 0.0
    assert "f1" in second.overlapping_finding_ids


def test_partial_overlap_credits_only_the_new_span():
    ledger = ClaimLedger()
    ledger.attribute("f1", gb_month_claim(days=10))
    second = ledger.attribute("f2", gb_month_claim(days=15))
    # 5 of 15 days are new: 500 GB x 5/30 months.
    assert round(second.per_meter[Meter.GB_MONTHS].attributed, 4) == round(500.0 * 5 / 30, 4)


def test_different_meters_never_cancel_each_other():
    """A storage claim must not absorb a GPU claim, or totals stop meaning anything."""
    ledger = ClaimLedger()
    gpu = ResourceClaim(
        intervals=[GPUInterval(gpu_id="shared-id", start=T0, end=T0 + timedelta(hours=10))]
    )
    storage = ResourceClaim(
        resource_intervals=[
            ResourceInterval(
                meter=Meter.GB_MONTHS,
                resource_id="shared-id",  # deliberately the same string
                start=T0,
                end=T0 + timedelta(hours=10),
                magnitude=100.0,
            )
        ],
        primary_meter=Meter.GB_MONTHS,
    )
    first = ledger.attribute("gpu-finding", gpu)
    second = ledger.attribute("storage-finding", storage)

    assert first.attributed_gpu_hours == 10.0
    assert second.per_meter[Meter.GB_MONTHS].attributed > 0
    assert second.value_ratio == 1.0
    assert second.overlapping_finding_ids == []


def test_quantity_meters_dedup_by_high_water_mark():
    ledger = ClaimLedger()

    def flow_claim(amount: float) -> ResourceClaim:
        return ResourceClaim(
            quantities=[
                ResourceQuantity(
                    meter=Meter.GB_TRANSFERRED, resource_id="flow-1", amount=amount
                )
            ],
            primary_meter=Meter.GB_TRANSFERRED,
        )

    first = ledger.attribute("f1", flow_claim(1000.0))
    second = ledger.attribute("f2", flow_claim(1500.0))
    third = ledger.attribute("f3", flow_claim(400.0))

    assert first.per_meter[Meter.GB_TRANSFERRED].attributed == 1000.0
    assert second.per_meter[Meter.GB_TRANSFERRED].attributed == 500.0
    assert third.per_meter[Meter.GB_TRANSFERRED].attributed == 0.0


def test_value_ratio_follows_the_most_contested_meter():
    """A finding is worth what its scarcest meter allows."""
    ledger = ClaimLedger()
    ledger.attribute(
        "prior",
        ResourceClaim(
            intervals=[GPUInterval(gpu_id="g0", start=T0, end=T0 + timedelta(hours=10))]
        ),
    )
    mixed = ResourceClaim(
        intervals=[GPUInterval(gpu_id="g0", start=T0, end=T0 + timedelta(hours=10))],
        resource_intervals=[
            ResourceInterval(
                meter=Meter.REPLICA_HOURS,
                resource_id="endpoint-1",
                start=T0,
                end=T0 + timedelta(hours=10),
                magnitude=2.0,
            )
        ],
        primary_meter=Meter.REPLICA_HOURS,
    )
    credited = ledger.attribute("later", mixed)
    # Replica-hours are untouched, but the GPU-hours were already claimed.
    assert credited.per_meter[Meter.REPLICA_HOURS].attributed == 20.0
    assert credited.attributed_gpu_hours == 0.0
    assert credited.value_ratio == 0.0


# ------------------------------------------------------- backwards compatibility


def test_gpu_only_claims_behave_exactly_as_before():
    ledger = ClaimLedger()
    claim = ResourceClaim(
        intervals=[
            GPUInterval(gpu_id="g0", start=T0, end=T0 + timedelta(hours=4)),
            GPUInterval(gpu_id="g1", start=T0, end=T0 + timedelta(hours=4)),
        ],
        queue_job_ids=["job-a"],
        queue_seconds=600.0,
    )
    credited = ledger.attribute("f1", claim)
    assert claim.gpu_hours == 8.0
    assert credited.attributed_gpu_hours == 8.0
    assert credited.attributed_queue_seconds == 600.0
    assert credited.value_ratio == 1.0

    repeat = ledger.attribute("f2", claim)
    assert repeat.attributed_gpu_hours == 0.0
    assert repeat.attributed_queue_seconds == 0.0
