from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from natilah.agents.coordinator import AgentCoordinator
from natilah.engine.claim import GPUHourLedger, merge_intervals
from natilah.models.domain import ClusterDataset, GPUInterval, ResourceClaim
from natilah.models.enums import Resolution

T0 = datetime(2026, 1, 15, tzinfo=timezone.utc)


def coordinate(dataset: ClusterDataset):
    coordinator = AgentCoordinator(use_llm=False, top_n=5)
    findings, report = coordinator.analyze_dataset(dataset)
    return coordinator, findings, report


def test_merge_intervals_unions_overlaps():
    merged = merge_intervals(
        [
            (T0, T0 + timedelta(hours=2)),
            (T0 + timedelta(hours=1), T0 + timedelta(hours=3)),
            (T0 + timedelta(hours=5), T0 + timedelta(hours=6)),
        ]
    )
    assert merged == [
        (T0, T0 + timedelta(hours=3)),
        (T0 + timedelta(hours=5), T0 + timedelta(hours=6)),
    ]


def test_ledger_credits_each_gpu_hour_once():
    ledger = GPUHourLedger()
    first = ResourceClaim(
        intervals=[GPUInterval(gpu_id="g0", start=T0, end=T0 + timedelta(hours=4))]
    )
    second = ResourceClaim(
        intervals=[
            GPUInterval(gpu_id="g0", start=T0 + timedelta(hours=2), end=T0 + timedelta(hours=6))
        ]
    )
    a = ledger.attribute("f1", first)
    b = ledger.attribute("f2", second)

    assert a.attributed_gpu_hours == pytest.approx(4.0)
    assert a.overlap_gpu_hours == pytest.approx(0.0)
    assert b.attributed_gpu_hours == pytest.approx(2.0)
    assert b.overlap_gpu_hours == pytest.approx(2.0)
    assert b.overlapping_finding_ids == ["f1"]
    assert b.value_ratio == pytest.approx(0.5)
    assert ledger.total_overlap_gpu_hours == pytest.approx(2.0)


def test_ledger_caps_queue_time_per_job():
    ledger = GPUHourLedger()
    claim = ResourceClaim(queue_job_ids=["job-a"], queue_seconds=3600.0)
    first = ledger.attribute("f1", claim)
    second = ledger.attribute("f2", claim)
    assert first.attributed_queue_seconds == pytest.approx(3600.0)
    assert second.attributed_queue_seconds == pytest.approx(0.0)
    assert second.value_ratio == pytest.approx(0.0)


def test_coordination_deduplicates_and_ranks(synthetic_dataset: ClusterDataset):
    coordinator, findings, report = coordinate(synthetic_dataset)

    assert report.total_findings == len(findings)
    assert report.agents and len(report.agents) == 4
    assert report.ranked_findings + report.suppressed_findings == report.total_findings
    # Deduplication can only ever remove value, never invent it.
    assert report.attributed_gpu_hours <= report.claimed_gpu_hours + 1e-6
    assert report.attributed_monthly_value <= report.claimed_monthly_value + 1e-6

    ranked = [f for f in findings if f.attribution.rank > 0]
    assert [f.attribution.rank for f in ranked] == list(range(1, len(ranked) + 1))
    values = [f.attribution.expected_monthly_value for f in ranked]
    assert values == sorted(values, reverse=True)


def test_no_gpu_hour_is_credited_twice(synthetic_dataset: ClusterDataset):
    _, findings, report = coordinate(synthetic_dataset)
    ranked = [f for f in findings if f.attribution.rank > 0]

    per_gpu: dict[str, list[tuple[datetime, datetime]]] = {}
    for finding in ranked:
        for interval in finding.claim.intervals:
            per_gpu.setdefault(interval.gpu_id, []).append((interval.start, interval.end))
    union_hours = sum(
        (end - start).total_seconds() / 3600.0
        for spans in per_gpu.values()
        for start, end in merge_intervals(spans)
    )
    credited = sum(f.attribution.attributed_gpu_hours for f in ranked)
    assert credited <= union_hours + 1e-6
    assert report.attributed_gpu_hours == pytest.approx(credited)


def test_conflicting_actions_on_one_job_are_resolved(synthetic_dataset: ClusterDataset):
    _, findings, report = coordinate(synthetic_dataset)
    ranked = [f for f in findings if f.attribution.rank > 0]

    # A ranked set must never contain two actions mutating the same job, nor two
    # actions promising to start the same waiting job earlier.
    mutated: set[str] = set()
    beneficiaries: set[str] = set()
    for finding in ranked:
        action = finding.alternative.proposed_action
        targets = set()
        if action.get("kind") in {"resize", "release_gpus"}:
            targets.add(finding.decision.job_id)
        for key in ("release_from_job_id", "move_job_id"):
            if action.get(key):
                targets.add(str(action[key]))
        assert not (targets & mutated)
        mutated |= targets

        claimed = set(finding.claim.queue_job_ids)
        assert not (claimed & beneficiaries)
        beneficiaries |= claimed

    superseded = [f for f in findings if f.attribution.resolution == Resolution.SUPERSEDED]
    assert len(superseded) == report.conflicts_resolved
    for finding in superseded:
        assert finding.attribution.superseded_by
        assert finding.attribution.notes


def test_top_actions_are_ranked_and_capped(synthetic_dataset: ClusterDataset):
    coordinator, findings, report = coordinate(synthetic_dataset)
    top = coordinator.top_actions(findings)
    assert 0 < len(top) <= coordinator.top_n
    assert [f.attribution.rank for f in top] == list(range(1, len(top) + 1))
    assert len(report.top_actions) == len(top)
    for finding in top:
        assert finding.attribution.resolution in {Resolution.UNIQUE, Resolution.DEDUPLICATED}
        assert finding.recommended_action
        assert finding.attribution.attributed_monthly_value > 0


@pytest.mark.asyncio
async def test_coordinator_persists_and_serves_ranked_actions(populated_session):
    from natilah.models.database import load_findings, load_ranked_findings

    coordinator = AgentCoordinator(use_llm=False, top_n=3)
    findings, report = await coordinator.run(populated_session)
    assert report.ranked_findings > 0

    stored = await load_findings(populated_session)
    assert len(stored) == len(findings)
    assert {f.agent_name for f in stored} <= {a.name for a in coordinator.agents}

    ranked = await load_ranked_findings(populated_session, limit=3)
    assert 0 < len(ranked) <= 3
    assert [f.attribution.rank for f in ranked] == list(range(1, len(ranked) + 1))
    assert all(f.status.value == "awaiting_approval" for f in ranked)


def test_two_runs_over_the_same_dataset_agree(synthetic_dataset: ClusterDataset):
    # Dollar figures are quoted to engineers; the same window must not produce a
    # different answer because a set happened to iterate in another order.
    def signature(findings):
        return sorted(
            (
                f.agent_name,
                f.decision.job_id,
                f.alternative.description,
                round(f.claim.gpu_hours, 6),
                round(f.value.estimated_monthly_value, 6),
                f.attribution.rank,
                round(f.attribution.attributed_monthly_value, 6),
            )
            for f in findings
        )

    _, first, report_a = coordinate(synthetic_dataset)
    _, second, report_b = coordinate(synthetic_dataset)
    assert signature(first) == signature(second)
    assert report_a.attributed_monthly_value == pytest.approx(report_b.attributed_monthly_value)
    assert report_a.conflicts_resolved == report_b.conflicts_resolved
