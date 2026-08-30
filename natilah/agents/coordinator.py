"""Coordination layer over the specialized agents.

Each agent works alone on one objective, which is what makes them accurate and
what makes them collide. Three collisions matter:

1. The same GPU-hours described twice. The idle agent sees a job holding dead
   GPUs; the queue agent sees a waiting job those GPUs could have run. Both
   findings are true and the hours behind them are the same hours.
2. Contradictory actions on the same job. You cannot both shrink a job and
   relocate it, and you cannot start the same waiting job twice.
3. No shared notion of "biggest". Each agent ranks inside its own objective.

The coordinator resolves all three: conflicts first (a losing finding is
superseded, not silently dropped), then a deterministic GPU-hour ledger that
credits each finding only with the hours nobody above it already claimed, then
a single ranking by expected value across every objective.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.agents.fragmentation_agent import FragmentationPlacementAgent
from natilah.agents.idle_allocation_agent import IdleAllocationAgent
from natilah.agents.over_allocation_agent import OverAllocationAgent
from natilah.agents.queue_efficiency_agent import QueueEfficiencyAgent
from natilah.engine.claim import GPUHourLedger
from natilah.engine.history import HistoricalPatternIndex
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.engine.value_calculator import ValueCalculator, default_economic_config
from natilah.models.database import CostConfigModel, load_cluster_dataset, save_findings
from natilah.models.domain import (
    ClusterDataset,
    CoordinationReport,
    Finding,
    TimeRange,
)
from natilah.models.enums import Resolution
from natilah.safety.guards import Action, SafetyGuard

logger = logging.getLogger(__name__)

MIN_ATTRIBUTED_GPU_HOURS = 0.05


def default_agents(value_calculator: ValueCalculator | None = None, use_llm: bool | None = None):
    """One agent per optimization objective."""
    return [
        IdleAllocationAgent(value_calculator=value_calculator, use_llm=use_llm),
        OverAllocationAgent(value_calculator=value_calculator, use_llm=use_llm),
        QueueEfficiencyAgent(value_calculator=value_calculator, use_llm=use_llm),
        FragmentationPlacementAgent(value_calculator=value_calculator, use_llm=use_llm),
    ]


class AgentCoordinator:
    """Runs every specialized agent, then deduplicates, resolves, and ranks."""

    def __init__(self, agents=None, top_n: int = 10, use_llm: bool | None = None):
        self.safety = SafetyGuard()
        self.top_n = top_n
        self.use_llm = use_llm
        self.agents = agents if agents is not None else default_agents(use_llm=use_llm)

    # ------------------------------------------------------------------ entry

    async def run(
        self,
        session: AsyncSession,
        time_range: TimeRange | None = None,
        persist: bool = True,
    ) -> tuple[list[Finding], CoordinationReport]:
        self.safety.check_action(Action(name="analyze_cluster", is_read_only=True))
        dataset = await load_cluster_dataset(session)
        cost_row = await session.get(CostConfigModel, 1)
        if cost_row is not None:
            calculator = ValueCalculator(default_economic_config(cost_row.cost_per_gpu_hour))
            for agent in self.agents:
                agent.value_calculator = calculator

        findings, report = self.analyze_dataset(dataset, time_range=time_range)
        if persist:
            await save_findings(session, findings)
        return findings, report

    def analyze_dataset(
        self,
        dataset: ClusterDataset,
        time_range: TimeRange | None = None,
    ) -> tuple[list[Finding], CoordinationReport]:
        report = CoordinationReport(generated_at=datetime.now(timezone.utc))
        if not dataset.jobs:
            report.notes.append("No jobs in the ingested window.")
            return [], report

        reconstructor = ClusterStateReconstructor(dataset)
        history = HistoricalPatternIndex(dataset)

        all_findings: list[Finding] = []
        for agent in self.agents:
            try:
                found = agent.analyze_dataset(
                    dataset, reconstructor=reconstructor, history=history, time_range=time_range
                )
                all_findings.extend(found)
            except Exception as exc:
                logger.exception("Agent %s failed", agent.name)
                agent.summary.error = f"{type(exc).__name__}: {exc}"
            report.agents.append(agent.summary)

        findings = self.coordinate(all_findings, report)
        return findings, report

    # ----------------------------------------------------------- coordination

    def coordinate(self, findings: list[Finding], report: CoordinationReport) -> list[Finding]:
        report.total_findings = len(findings)
        report.claimed_gpu_hours = sum(f.claim.gpu_hours for f in findings)
        report.claimed_monthly_value = sum(f.value.estimated_monthly_value for f in findings)

        ordered = sorted(findings, key=self._expected_value, reverse=True)
        ledger = GPUHourLedger()
        claimed_targets: dict[str, str] = {}
        claimed_beneficiaries: dict[str, str] = {}
        ranked: list[Finding] = []
        suppressed: list[Finding] = []

        for finding in ordered:
            attribution = finding.attribution
            attribution.claimed_gpu_hours = finding.claim.gpu_hours
            attribution.claimed_queue_seconds = finding.claim.queue_seconds

            conflict = self._first_conflict(finding, claimed_targets, claimed_beneficiaries)
            if conflict is not None:
                winner_id, reason = conflict
                attribution.resolution = Resolution.SUPERSEDED
                attribution.superseded_by = winner_id
                attribution.conflicts_with = [winner_id]
                attribution.notes.append(reason)
                report.conflicts_resolved += 1
                suppressed.append(finding)
                continue

            credited = ledger.attribute(finding.opportunity_id, finding.claim)
            attribution.attributed_gpu_hours = credited.attributed_gpu_hours
            attribution.overlap_gpu_hours = credited.overlap_gpu_hours
            attribution.attributed_queue_seconds = credited.attributed_queue_seconds
            attribution.overlaps_with = credited.overlapping_finding_ids
            ratio = credited.value_ratio
            attribution.attributed_monthly_value = finding.value.estimated_monthly_value * ratio
            attribution.attributed_annual_value = finding.value.estimated_annual_value * ratio
            attribution.expected_monthly_value = (
                attribution.attributed_monthly_value * finding.confidence.score
            )

            if (
                credited.attributed_gpu_hours < MIN_ATTRIBUTED_GPU_HOURS
                and credited.attributed_queue_seconds <= 0
            ):
                attribution.resolution = Resolution.FULLY_DEDUPLICATED
                attribution.notes.append(
                    "Every GPU-hour in this claim was already credited to a higher-value finding."
                )
                suppressed.append(finding)
                continue

            if credited.overlap_gpu_hours > 0 or credited.overlap_queue_seconds > 0:
                attribution.resolution = Resolution.DEDUPLICATED
                attribution.notes.append(
                    f"{credited.overlap_gpu_hours:.2f} GPU-h already claimed elsewhere were removed."
                )
            else:
                attribution.resolution = Resolution.UNIQUE

            for job_id in self._mutation_targets(finding):
                claimed_targets.setdefault(job_id, finding.opportunity_id)
            for job_id in finding.claim.queue_job_ids:
                claimed_beneficiaries.setdefault(job_id, finding.opportunity_id)
            ranked.append(finding)

        ranked.sort(key=lambda f: f.attribution.expected_monthly_value, reverse=True)
        for index, finding in enumerate(ranked, start=1):
            finding.attribution.rank = index

        report.ranked_findings = len(ranked)
        report.suppressed_findings = len(suppressed)
        report.duplicate_gpu_hours_removed = ledger.total_overlap_gpu_hours
        report.duplicate_queue_seconds_removed = ledger.total_overlap_queue_seconds
        report.attributed_gpu_hours = sum(f.attribution.attributed_gpu_hours for f in ranked)
        report.attributed_monthly_value = sum(f.attribution.attributed_monthly_value for f in ranked)
        report.attributed_annual_value = sum(f.attribution.attributed_annual_value for f in ranked)
        report.top_actions = [
            f"#{f.attribution.rank} [{f.agent_name}] {f.recommended_action.split('.')[0]} "
            f"(${f.attribution.attributed_monthly_value:,.0f}/mo, confidence {f.confidence.score:.2f})"
            for f in ranked[: self.top_n]
        ]
        return ranked + suppressed

    def top_actions(self, findings: list[Finding], limit: int | None = None) -> list[Finding]:
        """The highest-value, independently validated actions for a cluster."""
        limit = limit or self.top_n
        eligible = [
            f
            for f in findings
            if f.attribution.resolution
            in {Resolution.UNIQUE, Resolution.DEDUPLICATED}
        ]
        eligible.sort(key=lambda f: f.attribution.rank or 10**6)
        return eligible[:limit]

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _expected_value(finding: Finding) -> float:
        return finding.value.estimated_monthly_value * max(finding.confidence.score, 0.0)

    @staticmethod
    def _mutation_targets(finding: Finding) -> set[str]:
        """Jobs whose allocation this finding would actually change."""
        action = finding.alternative.proposed_action or {}
        targets: set[str] = set()
        kind = action.get("kind")
        primary = finding.decision.job_id
        if kind in {"resize", "release_gpus"} and primary:
            targets.add(primary)
        if action.get("release_from_job_id"):
            targets.add(str(action["release_from_job_id"]))
        if action.get("move_job_id"):
            targets.add(str(action["move_job_id"]))
        if kind == "place" and primary and not action.get("start_job_id"):
            targets.add(primary)
        return targets

    def _first_conflict(
        self,
        finding: Finding,
        claimed_targets: dict[str, str],
        claimed_beneficiaries: dict[str, str],
    ) -> tuple[str, str] | None:
        for job_id in self._mutation_targets(finding):
            winner = claimed_targets.get(job_id)
            if winner:
                return winner, (
                    f"A higher-value finding already changes {job_id}; two conflicting actions "
                    "cannot both be applied."
                )
        for job_id in finding.claim.queue_job_ids:
            winner = claimed_beneficiaries.get(job_id)
            if winner:
                return winner, (
                    f"A higher-value finding already starts {job_id} earlier; its wait can only "
                    "be recovered once."
                )
        return None
