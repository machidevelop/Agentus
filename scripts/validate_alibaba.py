#!/usr/bin/env python3
"""Validate Natilah against real Alibaba GPU Trace data.

Runs the full counterfactual pipeline on trace data, benchmarks against
baseline policies, and generates a manual review report for top findings.

Usage:
    python scripts/validate_alibaba.py --trace-dir data/alibaba_trace_2023/
    python scripts/validate_alibaba.py --trace-dir data/alibaba_trace_2023/ --hours 24 --max-jobs 5000
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from natilah.engine.comparator import Comparator
from natilah.engine.confidence import ConfidenceScorer
from natilah.engine.counterfactual import CounterfactualEngine
from natilah.engine.opportunity_detector import DetectorRegistry
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.engine.value_calculator import ValueCalculator
from natilah.ingestion.alibaba_trace import OpenB2023Config, OpenB2023Connector, V2026Config, V2026Connector
from natilah.models.domain import (
    Alternative,
    ClusterDataset,
    ClusterStateSnapshot,
    Finding,
    Observation,
    UtilizationPoint,
    resolve_gpu_type,
)
from natilah.models.enums import ConfidenceLevel, OpportunityType

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("validate")


# ---------------------------------------------------------------------------
# Baseline policies — simple schedulers to benchmark Natilah findings against
# ---------------------------------------------------------------------------

@dataclass
class BaselineResult:
    name: str
    total_gpu_hours_wasted: float = 0.0
    total_queue_wait_seconds: float = 0.0
    fragmentation_score: float = 0.0
    jobs_delayed: int = 0
    jobs_with_idle_gpus: int = 0
    multi_node_placements: int = 0
    could_be_single_node: int = 0


def compute_observed_baseline(dataset: ClusterDataset, reconstructor: ClusterStateReconstructor) -> BaselineResult:
    """Measure the actual observed trace outcome as a baseline."""
    result = BaselineResult(name="observed")
    alloc_by_job = dataset.allocation_by_job()
    samples_by_job: dict[str, list[float]] = defaultdict(list)
    for s in dataset.samples:
        if s.job_id:
            samples_by_job[s.job_id].append(s.gpu_utilization_pct)

    for job in dataset.jobs:
        alloc = alloc_by_job.get(job.job_id)
        if not alloc:
            continue
        duration_h = 0.0
        if job.start_time and job.end_time:
            duration_h = (job.end_time - job.start_time).total_seconds() / 3600
        elif alloc.end_time:
            duration_h = (alloc.end_time - alloc.start_time).total_seconds() / 3600

        n_gpus = len(alloc.gpu_ids)
        util_samples = samples_by_job.get(job.job_id, [])
        avg_util = mean(util_samples) if util_samples else 50.0

        wasted_fraction = max(0.0, 1.0 - avg_util / 100.0)
        result.total_gpu_hours_wasted += n_gpus * duration_h * wasted_fraction

        if job.submit_time and job.start_time:
            wait = (job.start_time - job.submit_time).total_seconds()
            result.total_queue_wait_seconds += wait
            if wait > 600:
                result.jobs_delayed += 1

        if avg_util < 5.0 and duration_h > 0.25:
            result.jobs_with_idle_gpus += 1

        if len(alloc.node_ids) > 1:
            result.multi_node_placements += 1
            if job.start_time:
                state = reconstructor.reconstruct(alloc.start_time - timedelta(seconds=1))
                for cap in state.available_capacity.by_node.values():
                    if cap.idle_gpus >= n_gpus and (
                        not job.requested_gpu_type or cap.gpu_type == job.requested_gpu_type
                    ):
                        result.could_be_single_node += 1
                        break

    sample_times = sorted({a.start_time for a in dataset.allocations})
    sample_times = sample_times[::max(1, len(sample_times) // 20)]
    if sample_times:
        frags = []
        for ts in sample_times:
            snap = reconstructor.reconstruct(ts)
            total = snap.available_capacity.total_gpus or 1
            stranded = sum(
                cap.idle_gpus for cap in snap.available_capacity.by_node.values()
                if 0 < cap.idle_gpus < cap.total_gpus
            )
            frags.append(stranded / total)
        result.fragmentation_score = mean(frags)

    return result


def compute_fifo_baseline(dataset: ClusterDataset) -> BaselineResult:
    """FIFO policy: jobs start in submit order as GPUs become free.

    Simulates strict FIFO — no backfill, no priority, no type affinity.
    """
    result = BaselineResult(name="fifo_strict")

    total_gpus = sum(n.gpu_count for n in dataset.nodes)
    if total_gpus == 0:
        return result

    jobs = sorted(
        [j for j in dataset.jobs if j.submit_time],
        key=lambda j: j.submit_time,
    )

    gpu_free_at: list[float] = [0.0] * total_gpus
    alloc_by_job = dataset.allocation_by_job()
    samples_by_job: dict[str, list[float]] = defaultdict(list)
    for s in dataset.samples:
        if s.job_id:
            samples_by_job[s.job_id].append(s.gpu_utilization_pct)

    for job in jobs:
        if not job.submit_time:
            continue
        submit_ts = job.submit_time.timestamp()
        needed = max(job.requested_gpus, 1)
        if needed > total_gpus:
            continue

        gpu_free_at.sort()
        sim_start = max(submit_ts, gpu_free_at[needed - 1])
        sim_wait = sim_start - submit_ts

        alloc = alloc_by_job.get(job.job_id)
        actual_duration = 0.0
        if job.start_time and job.end_time:
            actual_duration = (job.end_time - job.start_time).total_seconds()
        elif alloc and alloc.end_time:
            actual_duration = (alloc.end_time - alloc.start_time).total_seconds()

        sim_end = sim_start + actual_duration
        for i in range(needed):
            gpu_free_at[i] = sim_end

        result.total_queue_wait_seconds += sim_wait
        if sim_wait > 600:
            result.jobs_delayed += 1

        util_samples = samples_by_job.get(job.job_id, [])
        avg_util = mean(util_samples) if util_samples else 50.0
        wasted = needed * (actual_duration / 3600) * max(0, 1 - avg_util / 100)
        result.total_gpu_hours_wasted += wasted

    return result


def compute_bestfit_baseline(dataset: ClusterDataset) -> BaselineResult:
    """Best-fit decreasing: pack jobs into the smallest node that fits.

    Simulates BFD to measure how much fragmentation it prevents vs observed.
    """
    result = BaselineResult(name="bestfit_decreasing")
    alloc_by_job = dataset.allocation_by_job()
    samples_by_job: dict[str, list[float]] = defaultdict(list)
    for s in dataset.samples:
        if s.job_id:
            samples_by_job[s.job_id].append(s.gpu_utilization_pct)

    node_free_gpus: dict[str, int] = {n.node_id: n.gpu_count for n in dataset.nodes}
    node_gpu_type: dict[str, str] = {n.node_id: n.gpu_type.name for n in dataset.nodes}
    node_free_at: dict[str, list[float]] = {
        n.node_id: [0.0] * n.gpu_count for n in dataset.nodes
    }

    jobs = sorted(
        [j for j in dataset.jobs if j.submit_time and j.start_time],
        key=lambda j: j.start_time,
    )

    for job in jobs:
        needed = max(job.requested_gpus, 1)
        submit_ts = job.submit_time.timestamp()
        start_ts = job.start_time.timestamp()

        alloc = alloc_by_job.get(job.job_id)
        duration = 0.0
        if job.end_time:
            duration = (job.end_time - job.start_time).total_seconds()
        elif alloc and alloc.end_time:
            duration = (alloc.end_time - alloc.start_time).total_seconds()

        best_node = None
        best_spare = float("inf")
        for nid, free_times in node_free_at.items():
            if job.requested_gpu_type and resolve_gpu_type(node_gpu_type.get(nid, "")).name != resolve_gpu_type(job.requested_gpu_type).name:
                continue
            available = sum(1 for t in free_times if t <= start_ts)
            if available >= needed:
                spare = available - needed
                if spare < best_spare:
                    best_spare = spare
                    best_node = nid

        if best_node:
            times = node_free_at[best_node]
            assigned = 0
            end_ts = start_ts + duration
            for i in range(len(times)):
                if times[i] <= start_ts and assigned < needed:
                    times[i] = end_ts
                    assigned += 1
        else:
            result.multi_node_placements += 1

        wait = start_ts - submit_ts
        result.total_queue_wait_seconds += wait
        if wait > 600:
            result.jobs_delayed += 1

        util_samples = samples_by_job.get(job.job_id, [])
        avg_util = mean(util_samples) if util_samples else 50.0
        wasted = needed * (duration / 3600) * max(0, 1 - avg_util / 100)
        result.total_gpu_hours_wasted += wasted

    return result


# ---------------------------------------------------------------------------
# Natilah pipeline runner (in-memory, no DB)
# ---------------------------------------------------------------------------

def run_natilah_pipeline(dataset: ClusterDataset) -> list[Finding]:
    """Run the full Natilah counterfactual analysis pipeline in-memory."""
    from natilah.agents.tools import (
        inspect_utilization,
        list_idle_capacity,
        probe_alternate_placement,
        probe_headroom_size,
        probe_release_idle_gpus,
        probe_unblocked_queue,
        ToolCandidate,
    )

    detectors = DetectorRegistry()
    counterfactual = CounterfactualEngine()
    comparator = Comparator()
    value_calc = ValueCalculator()
    confidence = ConfidenceScorer()

    reconstructor = ClusterStateReconstructor(dataset)
    observations = detectors.detect_all(dataset, reconstructor)
    logger.info("Detected %d raw observations", len(observations))

    type_counts: dict[OpportunityType, int] = {}
    for obs in observations:
        type_counts[obs.signal_type] = type_counts.get(obs.signal_type, 0) + 1

    findings: list[Finding] = []
    for obs in observations:
        state = reconstructor.reconstruct(obs.timestamp)
        alternatives = _propose_alternatives(obs, dataset, state, reconstructor)
        job = dataset.job_by_id().get(obs.decision.job_id) or dataset.job_by_id().get(
            obs.affected_job_ids[0] if obs.affected_job_ids else ""
        )
        if job is None:
            continue

        scored: list[Finding] = []
        for alt in alternatives:
            feasibility = counterfactual.validate(alt, job, state, dataset, exclude_job_id=job.job_id)
            if not feasibility.feasible:
                continue
            alt.constraints_satisfied = feasibility.constraints_checked
            comparison = comparator.compare(obs, alt, dataset, reconstructor, state)
            if (
                comparison.delta.gpu_hours_saved <= 0
                and comparison.delta.queue_time_reduction <= 0
                and comparison.delta.idle_hours_recovered <= 0
                and comparison.delta.fragmentation_reduction <= 0
            ):
                continue
            value = value_calc.estimate(comparison, obs, dataset)
            conf = confidence.assess(
                obs, alt, dataset,
                feasibility.constraints_checked,
                similar_count=max(0, type_counts.get(obs.signal_type, 1) - 1),
            )
            title = {
                OpportunityType.OVER_ALLOCATION: "Over-allocated GPU job",
                OpportunityType.POOR_PLACEMENT: "Fragmented multi-node placement",
                OpportunityType.FRAGMENTATION: "Stranded GPU capacity",
                OpportunityType.IDLE_ALLOCATION: "Idle GPU allocation",
                OpportunityType.QUEUE_INEFFICIENCY: "Queue wait with unused capacity",
            }.get(obs.signal_type, obs.signal_type.value.replace("_", " ").title())

            samples = [s for s in dataset.samples if s.job_id == obs.decision.job_id]
            by_ts: dict[datetime, list[float]] = {}
            for s in samples:
                by_ts.setdefault(s.timestamp, []).append(s.gpu_utilization_pct)
            series: list[UtilizationPoint] = []
            for ts, vals in sorted(by_ts.items())[:48]:
                series.append(UtilizationPoint(
                    timestamp=ts, actual_pct=sum(vals) / len(vals),
                ))

            scored.append(Finding(
                opportunity_id=str(uuid4()),
                opportunity_type=obs.signal_type,
                decision=obs.decision,
                severity=obs.severity,
                title=title,
                description=obs.description,
                detected_at=datetime.now(timezone.utc),
                affected_job_ids=obs.affected_job_ids,
                affected_gpu_ids=obs.affected_gpu_ids,
                alternative=alt,
                comparison=comparison,
                value=value,
                confidence=conf,
                utilization_series=series,
            ))

        if scored:
            scored.sort(key=lambda f: f.value.estimated_monthly_value, reverse=True)
            findings.append(scored[0])

    findings.sort(key=lambda f: f.value.estimated_monthly_value, reverse=True)
    return findings


def _propose_alternatives(
    obs: Observation,
    dataset: ClusterDataset,
    state: ClusterStateSnapshot,
    reconstructor: ClusterStateReconstructor,
) -> list[Alternative]:
    from natilah.agents.tools import (
        inspect_utilization,
        list_idle_capacity,
        probe_alternate_placement,
        probe_headroom_size,
        probe_release_idle_gpus,
        probe_unblocked_queue,
        ToolCandidate,
    )

    tools_invoked: list[str] = []
    candidates: list[ToolCandidate] = []
    job_id = obs.decision.job_id
    if obs.affected_job_ids and job_id not in dataset.job_by_id():
        job_id = obs.affected_job_ids[0]
    job = dataset.job_by_id().get(job_id)
    alloc = dataset.allocation_by_job().get(job_id)

    report = inspect_utilization(dataset, job_id)
    tools_invoked.append("inspect_utilization")
    idle_caps = list_idle_capacity(
        state, gpu_type=job.requested_gpu_type if job else None, min_gpus=1,
    )
    tools_invoked.append("list_idle_capacity")

    if report is not None:
        sized = probe_headroom_size(report)
        tools_invoked.append("probe_headroom_size")
        if sized is not None and alloc is not None:
            sized.proposed_action["gpu_ids"] = alloc.gpu_ids[:sized.proposed_action["gpu_count"]]
            sized.proposed_action["node_ids"] = list(
                {gid.rsplit("-gpu-", 1)[0] for gid in sized.proposed_action["gpu_ids"]}
            )
            candidates.append(sized)
        released = probe_release_idle_gpus(report, alloc.gpu_ids if alloc else [])
        tools_invoked.append("probe_release_idle_gpus")
        if released is not None:
            candidates.append(released)

    if job is not None:
        current_nodes = list(alloc.node_ids) if alloc else []
        needed = len(alloc.gpu_ids) if alloc else job.requested_gpus
        if needed >= 2:
            placement = probe_alternate_placement(job, state, current_nodes, needed)
            tools_invoked.append("probe_alternate_placement")
            candidates.extend(placement)

        blocking = list(obs.evidence.get("blocking_jobs") or [])
        if obs.evidence.get("wait_seconds") or blocking or state.pending_jobs:
            queued = probe_unblocked_queue(job, state, blocking)
            tools_invoked.append("probe_unblocked_queue")
            if queued is not None:
                candidates.append(queued)

    alternatives: list[Alternative] = []
    for c in candidates:
        alternatives.append(Alternative(
            alternative_id=str(uuid4()),
            description=c.description,
            proposed_action=c.proposed_action,
            generation_method=f"agent:gpu_allocation+{c.tool_name}",
            agent_name="gpu_allocation",
            agent_rationale=c.rationale,
            tools_invoked=tools_invoked,
        ))
    return alternatives


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------

UTIL_TYPES = {
    OpportunityType.IDLE_ALLOCATION.value,
    OpportunityType.OVER_ALLOCATION.value,
    OpportunityType.FRAGMENTATION.value,
    OpportunityType.POOR_PLACEMENT.value,
}
QUEUE_TYPES = {OpportunityType.QUEUE_INEFFICIENCY.value}


@dataclass
class AggregateMetrics:
    total_findings: int = 0
    findings_by_type: dict[str, int] = field(default_factory=dict)
    findings_by_confidence: dict[str, int] = field(default_factory=dict)
    avg_confidence_score: float = 0.0
    median_confidence_score: float = 0.0
    high_confidence_count: int = 0
    trace_total_gpu_hours: float = 0.0

    # Utilization bucket: idle/over-alloc/fragmentation/placement
    util_findings: int = 0
    util_raw_gpu_hours: float = 0.0
    util_dedup_gpu_hours: float = 0.0
    util_unique_slots: int = 0
    util_monthly_value: float = 0.0
    util_annual_value: float = 0.0
    util_equiv_gpus: float = 0.0
    util_wasted_gpu_hours: float = 0.0
    util_recovery_pct: float = 0.0

    # Queue bucket: queue inefficiency
    queue_findings: int = 0
    queue_raw_wait_hours: float = 0.0
    queue_dedup_wait_hours: float = 0.0
    queue_monthly_value: float = 0.0
    queue_annual_value: float = 0.0
    queue_total_wait_hours: float = 0.0
    queue_recovery_pct: float = 0.0

    # Combined
    total_monthly_value: float = 0.0
    total_annual_value: float = 0.0


def _finding_gpu_hour_slots(
    f: Finding, alloc_by_job: dict[str, Any],
) -> set[tuple[str, int]]:
    """Return set of (gpu_id, hour_bucket) tuples a finding claims to recover.

    Hour bucket = int(epoch_seconds / 3600) so each slot is one GPU for one hour.
    """
    job_id = f.decision.job_id
    alloc = alloc_by_job.get(job_id)
    if not alloc:
        return set()

    start = alloc.start_time
    end = alloc.end_time or start
    if not start:
        return set()

    start_epoch = int(start.timestamp())
    end_epoch = int(end.timestamp())
    start_bucket = start_epoch // 3600
    end_bucket = end_epoch // 3600

    gpu_ids = f.affected_gpu_ids or (alloc.gpu_ids if alloc else [])
    if not gpu_ids:
        return set()

    slots: set[tuple[str, int]] = set()
    for gid in gpu_ids:
        for bucket in range(start_bucket, end_bucket + 1):
            slots.add((gid, bucket))
    return slots


def compute_aggregate_metrics(
    findings: list[Finding], dataset: ClusterDataset,
) -> AggregateMetrics:
    m = AggregateMetrics()
    m.total_findings = len(findings)
    alloc_by_job = dataset.allocation_by_job()

    util_findings = [f for f in findings if f.opportunity_type.value in UTIL_TYPES]
    queue_findings = [f for f in findings if f.opportunity_type.value in QUEUE_TYPES]
    m.util_findings = len(util_findings)
    m.queue_findings = len(queue_findings)

    for f in findings:
        m.findings_by_type[f.opportunity_type.value] = m.findings_by_type.get(f.opportunity_type.value, 0) + 1
        m.findings_by_confidence[f.confidence.level.value] = m.findings_by_confidence.get(f.confidence.level.value, 0) + 1
        if f.confidence.level == ConfidenceLevel.HIGH:
            m.high_confidence_count += 1

    scores = [f.confidence.score for f in findings]
    if scores:
        m.avg_confidence_score = mean(scores)
        m.median_confidence_score = median(scores)

    # ---- UTILIZATION BUCKET: dedup via (gpu_id, hour) slots ----
    # Build per-job average utilization for waste-fraction capping
    samples_by_job: dict[str, list[float]] = defaultdict(list)
    for s in dataset.samples:
        if s.job_id:
            samples_by_job[s.job_id].append(s.gpu_utilization_pct)

    claimed_slots: set[tuple[str, int]] = set()
    for f in sorted(util_findings, key=lambda f: f.value.estimated_monthly_value, reverse=True):
        raw_h = f.comparison.delta.gpu_hours_saved
        m.util_raw_gpu_hours += raw_h

        jid = f.decision.job_id
        job_util_samples = samples_by_job.get(jid, [])
        avg_util = mean(job_util_samples) if job_util_samples else 50.0
        waste_frac = max(0.0, 1.0 - avg_util / 100.0)
        capped_h = raw_h * waste_frac

        slots = _finding_gpu_hour_slots(f, alloc_by_job)
        new_slots = slots - claimed_slots
        ratio = len(new_slots) / len(slots) if slots else 0.0
        claimed_slots |= new_slots

        m.util_dedup_gpu_hours += capped_h * ratio
        m.util_monthly_value += f.value.estimated_monthly_value * ratio
        m.util_annual_value += f.value.estimated_annual_value * ratio
        m.util_equiv_gpus += f.value.equivalent_gpus_recovered * ratio
    m.util_unique_slots = len(claimed_slots)

    # ---- QUEUE BUCKET: dedup by job_id ----
    seen_queue_jobs: set[str] = set()
    for f in sorted(queue_findings, key=lambda f: f.value.estimated_monthly_value, reverse=True):
        wait_h = f.comparison.delta.queue_time_reduction / 3600
        m.queue_raw_wait_hours += wait_h
        jid = f.decision.job_id
        if jid in seen_queue_jobs:
            continue
        seen_queue_jobs.add(jid)
        m.queue_dedup_wait_hours += wait_h
        m.queue_monthly_value += f.value.estimated_monthly_value
        m.queue_annual_value += f.value.estimated_annual_value

    # ---- Denominators (reuses samples_by_job built above) ----
    for job in dataset.jobs:
        alloc = alloc_by_job.get(job.job_id)
        if not alloc:
            continue
        dur_h = 0.0
        if job.start_time and job.end_time:
            dur_h = (job.end_time - job.start_time).total_seconds() / 3600
        elif alloc.end_time:
            dur_h = (alloc.end_time - alloc.start_time).total_seconds() / 3600
        n_gpus = len(alloc.gpu_ids)
        m.trace_total_gpu_hours += n_gpus * dur_h
        util_samples = samples_by_job.get(job.job_id, [])
        avg_util = mean(util_samples) if util_samples else 50.0
        wasted_frac = max(0.0, 1.0 - avg_util / 100.0)
        m.util_wasted_gpu_hours += n_gpus * dur_h * wasted_frac
        if job.submit_time and job.start_time:
            wait_h = (job.start_time - job.submit_time).total_seconds() / 3600
            if wait_h > 0:
                m.queue_total_wait_hours += wait_h

    if m.util_wasted_gpu_hours > 0:
        m.util_recovery_pct = (m.util_dedup_gpu_hours / m.util_wasted_gpu_hours) * 100
    if m.queue_total_wait_hours > 0:
        m.queue_recovery_pct = (m.queue_dedup_wait_hours / m.queue_total_wait_hours) * 100

    m.total_monthly_value = m.util_monthly_value + m.queue_monthly_value
    m.total_annual_value = m.util_annual_value + m.queue_annual_value

    return m


# ---------------------------------------------------------------------------
# Manual review report
# ---------------------------------------------------------------------------

@dataclass
class ReviewItem:
    rank: int
    finding: Finding
    feasibility_verdict: str = ""
    feasibility_notes: str = ""
    constraint_summary: str = ""


def generate_manual_review(findings: list[Finding], dataset: ClusterDataset, top_n: int = 20) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    alloc_by_job = dataset.allocation_by_job()
    jobs_by_id = dataset.job_by_id()

    for i, f in enumerate(findings[:top_n]):
        job = jobs_by_id.get(f.decision.job_id)
        alloc = alloc_by_job.get(f.decision.job_id)

        constraint_checks = f.confidence.constraints_checked
        constraint_summary = ", ".join(constraint_checks) if constraint_checks else "none"

        action = f.alternative.proposed_action
        notes_parts: list[str] = []

        if action.get("kind") == "resize" or action.get("gpu_count"):
            orig = action.get("original_gpu_count", "?")
            new = action.get("gpu_count", "?")
            notes_parts.append(f"Resize: {orig} -> {new} GPUs")
            if job and job.start_time and job.end_time:
                dur = (job.end_time - job.start_time).total_seconds() / 3600
                notes_parts.append(f"Job duration: {dur:.1f}h")

        if action.get("kind") == "place":
            nodes = action.get("node_ids", [])
            notes_parts.append(f"Repack to single node: {', '.join(nodes)}")
            if alloc:
                notes_parts.append(f"Was on: {', '.join(alloc.node_ids)}")

        if action.get("kind") == "reorder":
            wait_s = action.get("queue_time_reduction_seconds", 0)
            notes_parts.append(f"Queue reduction: {wait_s/60:.0f} min")
            if action.get("release_from_job_id"):
                notes_parts.append(f"Blocked by: {action['release_from_job_id']}")

        if action.get("kind") == "release_gpus":
            released = action.get("release_gpu_ids", [])
            notes_parts.append(f"Release {len(released)} idle GPUs")

        verdict = "REVIEW"
        if f.confidence.level == ConfidenceLevel.HIGH and not f.confidence.uncertainty_sources:
            verdict = "LIKELY_VALID"
        elif f.confidence.level == ConfidenceLevel.LOW:
            verdict = "NEEDS_SCRUTINY"

        items.append(ReviewItem(
            rank=i + 1,
            finding=f,
            feasibility_verdict=verdict,
            feasibility_notes=" | ".join(notes_parts),
            constraint_summary=constraint_summary,
        ))
    return items


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------

def print_report(
    metrics: AggregateMetrics,
    observed: BaselineResult,
    fifo: BaselineResult,
    bestfit: BaselineResult,
    review_items: list[ReviewItem],
    dataset: ClusterDataset,
    elapsed_seconds: float,
) -> None:
    print("\n" + "=" * 100)
    print("  NATILAH VALIDATION REPORT — Alibaba GPU Trace")
    print("=" * 100)

    print(f"\n--- Dataset Summary ---")
    print(f"  Nodes:        {len(dataset.nodes)}")
    print(f"  GPUs:         {len(dataset.gpus)}")
    print(f"  Jobs:         {len(dataset.jobs)}")
    print(f"  Allocations:  {len(dataset.allocations)}")
    print(f"  Samples:      {len(dataset.samples)}")
    print(f"  Total GPU-h:  {metrics.trace_total_gpu_hours:,.1f}")
    print(f"  Analysis time: {elapsed_seconds:.1f}s")

    print(f"\n--- Natilah Findings ---")
    print(f"  Total findings:        {metrics.total_findings}")
    for t, c in sorted(metrics.findings_by_type.items()):
        print(f"    {t:<24} {c}")
    print(f"  High confidence:       {metrics.high_confidence_count}")
    print(f"  Avg confidence:        {metrics.avg_confidence_score:.3f}")
    print(f"  Median confidence:     {metrics.median_confidence_score:.3f}")

    util_dedup_pct = (metrics.util_dedup_gpu_hours / metrics.util_raw_gpu_hours * 100) if metrics.util_raw_gpu_hours > 0 else 0

    print(f"\n--- Utilization Waste Recovery (deduplicated) ---")
    print(f"  Findings:              {metrics.util_findings}  (idle_alloc + over_alloc + fragmentation + placement)")
    print(f"  Wasted GPU-hours:      {metrics.util_wasted_gpu_hours:,.1f}  (denominator: sum of (1 - avg_util) * gpu * hours)")
    print(f"  Raw GPU-h claimed:     {metrics.util_raw_gpu_hours:,.1f}")
    print(f"  Dedup GPU-h recovered: {metrics.util_dedup_gpu_hours:,.1f}  ({util_dedup_pct:.0f}% of raw)")
    print(f"  Unique GPU-hour slots: {metrics.util_unique_slots:,}")
    print(f"  Equivalent GPUs:       {metrics.util_equiv_gpus:,.1f}")
    print(f"  >>> RECOVERY:          {metrics.util_recovery_pct:.1f}%  of utilization waste")
    print(f"  Monthly value:         ${metrics.util_monthly_value:,.0f}")

    print(f"\n--- Queue Waste Recovery (deduplicated by job) ---")
    print(f"  Findings:              {metrics.queue_findings}")
    print(f"  Total wait observed:   {metrics.queue_total_wait_hours:,.1f} hours  (denominator)")
    print(f"  Raw wait-h claimed:    {metrics.queue_raw_wait_hours:,.1f}")
    print(f"  Dedup wait-h recovered:{metrics.queue_dedup_wait_hours:,.1f}")
    print(f"  >>> RECOVERY:          {metrics.queue_recovery_pct:.1f}%  of queue wait time")
    print(f"  Monthly value:         ${metrics.queue_monthly_value:,.0f}")

    print(f"\n--- Combined ---")
    print(f"  Total monthly value:   ${metrics.total_monthly_value:,.0f}")
    print(f"  Total annual value:    ${metrics.total_annual_value:,.0f}")

    target_met = metrics.util_recovery_pct >= 20.0
    strong = metrics.util_recovery_pct >= 30.0
    print(f"\n  UTIL TARGET (>20%):    {'PASS' if target_met else 'BELOW'} ({metrics.util_recovery_pct:.1f}%)")
    if strong:
        print(f"  STRONG (>30%):         PASS ({metrics.util_recovery_pct:.1f}%)")

    if dataset.jobs:
        jobs_sampled = len(dataset.jobs)
        monthly_per_job = metrics.total_monthly_value / max(jobs_sampled, 1)
        print(f"\n  --- Fleet Extrapolation ---")
        print(f"  Sample:    {jobs_sampled:,} jobs -> ${metrics.total_monthly_value:,.0f}/month")
        for fleet_size in [10_000, 100_000, 1_000_000]:
            ext = monthly_per_job * fleet_size
            print(f"  {fleet_size:>10,} jobs -> ${ext:,.0f}/month (${ext * 12:,.0f}/year)")

    print(f"\n--- Baseline Comparison ---")
    print(f"  {'Metric':<32} {'Observed':>14} {'FIFO':>14} {'BestFit':>14}")
    print(f"  {'-'*32} {'-'*14} {'-'*14} {'-'*14}")
    print(f"  {'GPU-hours wasted':<32} {observed.total_gpu_hours_wasted:>14,.1f} {fifo.total_gpu_hours_wasted:>14,.1f} {bestfit.total_gpu_hours_wasted:>14,.1f}")
    print(f"  {'Queue wait (hours)':<32} {observed.total_queue_wait_seconds/3600:>14,.1f} {fifo.total_queue_wait_seconds/3600:>14,.1f} {bestfit.total_queue_wait_seconds/3600:>14,.1f}")
    print(f"  {'Jobs delayed >10min':<32} {observed.jobs_delayed:>14,} {fifo.jobs_delayed:>14,} {bestfit.jobs_delayed:>14,}")
    print(f"  {'Multi-node placements':<32} {observed.multi_node_placements:>14,} {'n/a':>14} {bestfit.multi_node_placements:>14,}")
    print(f"  {'Could be single-node':<32} {observed.could_be_single_node:>14,} {'n/a':>14} {'n/a':>14}")
    print(f"  {'Idle GPU jobs':<32} {observed.jobs_with_idle_gpus:>14,} {'n/a':>14} {'n/a':>14}")
    print(f"  {'Fragmentation score':<32} {observed.fragmentation_score:>14.4f} {'n/a':>14} {'n/a':>14}")

    if observed.total_gpu_hours_wasted > 0:
        pct_of_waste = (metrics.util_dedup_gpu_hours / observed.total_gpu_hours_wasted) * 100
        print(f"\n  Natilah recovers {pct_of_waste:.1f}% of baseline-measured GPU waste")
    if fifo.total_queue_wait_seconds > 0:
        queue_improvement = (
            (fifo.total_queue_wait_seconds - observed.total_queue_wait_seconds)
            / fifo.total_queue_wait_seconds * 100
        )
        print(f"  Observed scheduler is {abs(queue_improvement):.1f}% {'better' if queue_improvement > 0 else 'worse'} than FIFO on queue time")

    print(f"\n--- Top {len(review_items)} Findings for Manual Review ---")
    print(f"  {'#':>3} {'Type':<24} {'Confidence':>10} {'GPU-h Saved':>12} {'Monthly$':>12} {'Verdict':<14} {'Notes'}")
    print(f"  {'-'*3} {'-'*24} {'-'*10} {'-'*12} {'-'*12} {'-'*14} {'-'*40}")
    for item in review_items:
        f = item.finding
        conf = f"{f.confidence.level.value}({f.confidence.score:.2f})"
        gpu_h = f.comparison.delta.gpu_hours_saved + f.comparison.delta.idle_hours_recovered
        print(
            f"  {item.rank:>3} {f.opportunity_type.value:<24} {conf:>10} "
            f"{gpu_h:>12,.1f} {f.value.estimated_monthly_value:>12,.2f} "
            f"{item.feasibility_verdict:<14} {item.feasibility_notes[:50]}"
        )

    confident_valid = sum(1 for r in review_items if r.feasibility_verdict == "LIKELY_VALID")
    needs_review = sum(1 for r in review_items if r.feasibility_verdict == "REVIEW")
    needs_scrutiny = sum(1 for r in review_items if r.feasibility_verdict == "NEEDS_SCRUTINY")
    print(f"\n  Pre-screen: {confident_valid} likely valid, {needs_review} need review, {needs_scrutiny} need scrutiny")
    if review_items:
        pass_rate = (confident_valid + needs_review * 0.5) / len(review_items) * 100
        print(f"  Estimated manual pass rate: {pass_rate:.0f}%")

    print("\n" + "=" * 100)


def export_review_json(
    review_items: list[ReviewItem],
    metrics: AggregateMetrics,
    output_path: Path,
) -> None:
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_findings": metrics.total_findings,
            "util_recovery_pct": round(metrics.util_recovery_pct, 2),
            "util_dedup_gpu_hours": round(metrics.util_dedup_gpu_hours, 1),
            "util_wasted_gpu_hours": round(metrics.util_wasted_gpu_hours, 1),
            "util_monthly_value": round(metrics.util_monthly_value, 2),
            "queue_recovery_pct": round(metrics.queue_recovery_pct, 2),
            "queue_dedup_wait_hours": round(metrics.queue_dedup_wait_hours, 1),
            "queue_monthly_value": round(metrics.queue_monthly_value, 2),
            "total_monthly_value": round(metrics.total_monthly_value, 2),
            "avg_confidence": round(metrics.avg_confidence_score, 3),
            "high_confidence_count": metrics.high_confidence_count,
            "findings_by_type": metrics.findings_by_type,
        },
        "top_findings": [],
    }
    for item in review_items:
        f = item.finding
        data["top_findings"].append({
            "rank": item.rank,
            "opportunity_id": f.opportunity_id,
            "type": f.opportunity_type.value,
            "title": f.title,
            "description": f.description,
            "severity": round(f.severity, 3),
            "job_id": f.decision.job_id,
            "affected_jobs": f.affected_job_ids,
            "affected_gpus": f.affected_gpu_ids[:8],
            "alternative": {
                "description": f.alternative.description,
                "proposed_action": f.alternative.proposed_action,
                "rationale": f.alternative.agent_rationale,
                "generation_method": f.alternative.generation_method,
                "tools_invoked": f.alternative.tools_invoked,
            },
            "metrics": {
                "gpu_hours_saved": round(f.comparison.delta.gpu_hours_saved, 2),
                "idle_hours_recovered": round(f.comparison.delta.idle_hours_recovered, 2),
                "utilization_improvement": round(f.comparison.delta.utilization_improvement, 2),
                "queue_time_reduction_seconds": round(f.comparison.delta.queue_time_reduction, 1),
                "fragmentation_reduction": round(f.comparison.delta.fragmentation_reduction, 4),
            },
            "value": {
                "gpu_hours_recovered": round(f.value.gpu_hours_recovered, 2),
                "compute_cost_avoided": round(f.value.compute_cost_avoided, 2),
                "equivalent_gpus": round(f.value.equivalent_gpus_recovered, 3),
                "monthly_value": round(f.value.estimated_monthly_value, 2),
                "annual_value": round(f.value.estimated_annual_value, 2),
                "gpu_type": f.value.gpu_type,
                "assumptions": f.value.assumptions,
            },
            "confidence": {
                "score": round(f.confidence.score, 3),
                "level": f.confidence.level.value,
                "constraints_checked": f.confidence.constraints_checked,
                "uncertainty_sources": f.confidence.uncertainty_sources,
                "explanation": f.confidence.explanation,
            },
            "review": {
                "verdict": item.feasibility_verdict,
                "notes": item.feasibility_notes,
                "constraints_summary": item.constraint_summary,
                "checklist": [
                    "[ ] Proposed Y was physically feasible at decision time",
                    "[ ] GPU type/count/topology constraints satisfied",
                    "[ ] No hidden affinity or locality constraint violated",
                    "[ ] Utilization data supports the waste claim",
                    "[ ] Value estimate is conservative (not inflated)",
                    "[ ] Alternative is operationally realistic",
                ],
            },
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\nManual review JSON exported to: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Natilah against Alibaba GPU Trace data",
    )
    parser.add_argument("--trace-dir", type=str, required=True, help="Path to trace CSV directory")
    parser.add_argument("--format", type=str, default="auto", choices=["auto", "openb2023", "v2026"],
                        help="Trace format (default: auto-detect)")
    parser.add_argument("--hours", type=float, default=None, help="Time window in hours (default: full trace)")
    parser.add_argument("--start-offset", type=float, default=0, help="Hours to skip from trace start")
    parser.add_argument("--max-jobs", type=int, default=None, help="Limit number of jobs to process")
    parser.add_argument("--gpu-type", type=str, default=None, help="Filter to specific GPU type (e.g., T4, V100)")
    parser.add_argument("--top-n", type=int, default=20, help="Number of top findings for manual review")
    parser.add_argument("--output", type=str, default="data/validation_report.json", help="Output JSON path")
    parser.add_argument("--pod-file", type=str, default="openb_pod_list_default.csv",
                        help="Pod CSV file name (OpenB 2023)")
    parser.add_argument("--days", type=str, default="0-2", help="Day range for v2026 (e.g., 0-7)")
    args = parser.parse_args()

    trace_dir = Path(args.trace_dir)
    if not trace_dir.exists():
        print(f"ERROR: Trace directory not found: {trace_dir}")
        print(f"Run: python scripts/download_alibaba_trace.py --output-dir {trace_dir}")
        sys.exit(1)

    fmt = args.format
    if fmt == "auto":
        if (trace_dir / "openb_pod_list_default.csv").exists() or (trace_dir / args.pod_file).exists():
            fmt = "openb2023"
        elif (trace_dir / "asi_opensource_pod_hourly").exists() or \
             (trace_dir / "asi_opensource_job_execution_summary").exists():
            fmt = "v2026"
        else:
            print("ERROR: Cannot auto-detect trace format. Use --format openb2023 or --format v2026")
            sys.exit(1)

    print("=" * 60)
    print(f"  Natilah Validation — Alibaba GPU Trace ({fmt})")
    print("=" * 60)
    print(f"  Trace dir:    {trace_dir.resolve()}")
    print(f"  Time window:  {args.hours or 'full'}h (offset: {args.start_offset}h)")
    print(f"  Max jobs:     {args.max_jobs or 'unlimited'}")
    print(f"  GPU filter:   {args.gpu_type or 'all'}")
    print()

    t0 = time.time()

    print("[1/5] Loading trace data ...")
    if fmt == "openb2023":
        config = OpenB2023Config(
            trace_dir=str(trace_dir),
            pod_file=args.pod_file,
            time_window_hours=args.hours,
            max_jobs=args.max_jobs,
            start_offset_hours=args.start_offset,
            gpu_type_filter=args.gpu_type,
        )
        connector = OpenB2023Connector(config)
    else:
        day_parts = args.days.split("-")
        day_range = (int(day_parts[0]), int(day_parts[-1]))
        config_v2026 = V2026Config(
            data_dir=str(trace_dir),
            day_range=day_range,
            gpu_type_filter=args.gpu_type,
            max_jobs=args.max_jobs,
        )
        connector = V2026Connector(config_v2026)

    dataset = connector.load()
    t_load = time.time() - t0
    print(f"  Loaded in {t_load:.1f}s: {len(dataset.nodes)} nodes, {len(dataset.gpus)} GPUs, "
          f"{len(dataset.jobs)} jobs, {len(dataset.allocations)} allocations, {len(dataset.samples)} samples")

    if not dataset.jobs:
        print("ERROR: No jobs loaded. Check trace directory and file format.")
        sys.exit(1)

    print("\n[2/5] Running Natilah counterfactual pipeline ...")
    t1 = time.time()
    findings = run_natilah_pipeline(dataset)
    t_natilah = time.time() - t1
    print(f"  Pipeline complete in {t_natilah:.1f}s: {len(findings)} findings")

    print("\n[3/5] Computing baselines ...")
    t2 = time.time()
    reconstructor = ClusterStateReconstructor(dataset)
    observed = compute_observed_baseline(dataset, reconstructor)
    fifo = compute_fifo_baseline(dataset)
    bestfit = compute_bestfit_baseline(dataset)
    t_baseline = time.time() - t2
    print(f"  Baselines computed in {t_baseline:.1f}s")

    print("\n[4/5] Aggregating metrics ...")
    metrics = compute_aggregate_metrics(findings, dataset)

    print("\n[5/5] Generating manual review ...")
    review_items = generate_manual_review(findings, dataset, top_n=args.top_n)

    elapsed = time.time() - t0
    print_report(metrics, observed, fifo, bestfit, review_items, dataset, elapsed)
    export_review_json(review_items, metrics, Path(args.output))

    print(f"\nTotal elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
