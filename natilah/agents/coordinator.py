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

from natilah.agents.claim_recovery_agent import ClaimRecoveryAgent
from natilah.agents.commitment_agent import CommitmentCoverageAgent
from natilah.agents.fragmentation_agent import FragmentationPlacementAgent
from natilah.agents.idle_allocation_agent import IdleAllocationAgent
from natilah.agents.inference_agent import InferenceEfficiencyAgent
from natilah.agents.network_agent import NetworkEfficiencyAgent
from natilah.agents.over_allocation_agent import OverAllocationAgent
from natilah.agents.power_agent import PowerEfficiencyAgent
from natilah.agents.queue_efficiency_agent import QueueEfficiencyAgent
from natilah.agents.recurring_spend_agent import RecurringSpendAgent
from natilah.agents.storage_agent import StorageEfficiencyAgent
from natilah.agents.training_agent import TrainingEfficiencyAgent
from natilah.engine.calibration import ConfidenceCalibrator
from natilah.engine.claim import GPUHourLedger
from natilah.engine.history import HistoricalPatternIndex
from natilah.engine.selection import select_compatible
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
MIN_ATTRIBUTED_QUANTITY = 1e-6


def default_agents(value_calculator: ValueCalculator | None = None, use_llm: bool | None = None):
    """One agent per optimization objective — scheduling agents plus Phase 3 domain agents."""
    return [
        # Scheduling agents (GPU-hours meter)
        IdleAllocationAgent(value_calculator=value_calculator, use_llm=use_llm),
        OverAllocationAgent(value_calculator=value_calculator, use_llm=use_llm),
        QueueEfficiencyAgent(value_calculator=value_calculator, use_llm=use_llm),
        FragmentationPlacementAgent(value_calculator=value_calculator, use_llm=use_llm),
        # Phase 3: each domain has its own meter
        StorageEfficiencyAgent(),
        NetworkEfficiencyAgent(),
        CommitmentCoverageAgent(),
        PowerEfficiencyAgent(),
        TrainingEfficiencyAgent(),
        InferenceEfficiencyAgent(),
    ]


def default_household_agents():
    """The consumer fleet. One agent per meter, exactly as on the cluster side.

    Claim recovery is metered in one-time dollars and recurring spend in
    dollars per month. They never touch each other's meter, so the ledger can
    hold both without one cancelling the other.
    """
    return [
        ClaimRecoveryAgent(),
        RecurringSpendAgent(),
    ]


class AgentCoordinator:
    """Runs every specialized agent, then deduplicates, resolves, and ranks."""

    def __init__(
        self,
        agents=None,
        top_n: int = 10,
        use_llm: bool | None = None,
        calibrator: ConfidenceCalibrator | None = None,
    ):
        self.safety = SafetyGuard()
        self.top_n = top_n
        self.use_llm = use_llm
        self.agents = agents if agents is not None else default_agents(use_llm=use_llm)
        # Optional. Without one, confidence stays the agent's own heuristic and
        # nothing pretends it has been validated against outcomes.
        self.calibrator = calibrator

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

        # Household datasets carry no scheduler decisions, so the reconstructor
        # and the history index have nothing to build from. Every agent already
        # accepts them as optional; the consumer agents simply ignore them.
        is_cluster = hasattr(dataset, "jobs")
        if is_cluster:
            if not dataset.jobs:
                report.notes.append("No jobs in the ingested window.")
                return [], report
            reconstructor = ClusterStateReconstructor(dataset)
            history = HistoricalPatternIndex(dataset)
        else:
            if not getattr(dataset, "has_domain_data", False):
                report.notes.append("No claims or recurring charges in the ingested window.")
                return [], report
            reconstructor = None
            history = None

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

    def apply_calibration(self, findings: list[Finding]) -> int:
        """Replace heuristic confidence with the calibrated probability.

        Ranking is expected value, so an uncalibrated confidence quietly
        distorts every comparison across the fleet. The raw score is kept
        beside the calibrated one rather than overwritten.
        """
        if self.calibrator is None or not self.calibrator.is_fitted():
            return 0
        changed = 0
        for finding in findings:
            assessment = finding.confidence
            if assessment is None or assessment.calibrated:
                continue
            raw = assessment.score
            calibrated = self.calibrator.calibrate(raw, finding.agent_name or "")
            assessment.raw_score = raw
            assessment.score = calibrated
            assessment.calibrated = True
            assessment.explanation = (
                f"{assessment.explanation} Calibrated from {raw:.2f} to {calibrated:.2f} "
                "against recorded reviewer outcomes."
            )
            changed += 1
        return changed

    def coordinate(self, findings: list[Finding], report: CoordinationReport) -> list[Finding]:
        report.total_findings = len(findings)
        calibrated = self.apply_calibration(findings)
        if calibrated:
            report.notes.append(
                f"Confidence calibrated against recorded outcomes for {calibrated} finding(s)."
            )
        report.claimed_gpu_hours = sum(f.claim.gpu_hours for f in findings)
        report.claimed_monthly_value = sum(f.value.estimated_monthly_value for f in findings)

        ordered = sorted(findings, key=self._expected_value, reverse=True)

        # Conflicts are resolved globally rather than greedily. Two findings
        # that each block one big finding can be worth more together than the
        # big one is alone, and the greedy walk could never see that.
        by_id = {f.opportunity_id: f for f in ordered}
        weights = {f.opportunity_id: max(0.0, self._expected_value(f)) for f in ordered}
        selection = select_compatible(weights, self._conflict_pairs(ordered))
        report.selection_gain_monthly_value = round(selection.improvement_over_greedy, 4)
        if selection.improvement_over_greedy > 1e-6:
            report.notes.append(
                f"Global conflict selection kept ${selection.improvement_over_greedy:,.2f}/mo of "
                "expected value that the greedy rule would have dropped."
            )

        ledger = GPUHourLedger()
        ranked: list[Finding] = []
        suppressed: list[Finding] = []

        for finding in ordered:
            attribution = finding.attribution
            attribution.claimed_gpu_hours = finding.claim.gpu_hours
            attribution.claimed_queue_seconds = finding.claim.queue_seconds

            if finding.opportunity_id in selection.dropped:
                winners = selection.displaced_by.get(finding.opportunity_id, [])
                attribution.resolution = Resolution.SUPERSEDED
                attribution.superseded_by = winners[0] if winners else None
                attribution.conflicts_with = list(winners)
                attribution.notes.append(self._conflict_reason(finding, winners, by_id))
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
            for meter, bucket in credited.per_meter.items():
                key = meter.value
                report.claimed_by_meter[key] = report.claimed_by_meter.get(key, 0.0) + bucket.claimed
                attribution.claimed_by_meter[key] = bucket.claimed
                attribution.attributed_by_meter[key] = bucket.attributed

            if self._fully_absorbed(finding, credited):
                attribution.resolution = Resolution.FULLY_DEDUPLICATED
                attribution.notes.append(
                    f"Every {finding.claim.primary_meter.unit_label} in this claim was already "
                    "credited to a higher-value finding."
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

            ranked.append(finding)
            meter_key = finding.claim.primary_meter.value
            report.findings_by_meter[meter_key] = report.findings_by_meter.get(meter_key, 0) + 1
            for meter, bucket in credited.per_meter.items():
                report.attributed_by_meter[meter.value] = (
                    report.attributed_by_meter.get(meter.value, 0.0) + bucket.attributed
                )

        ranked.sort(key=lambda f: f.attribution.expected_monthly_value, reverse=True)
        for index, finding in enumerate(ranked, start=1):
            finding.attribution.rank = index

        report.ranked_findings = len(ranked)
        report.suppressed_findings = len(suppressed)
        report.duplicate_gpu_hours_removed = ledger.total_overlap_gpu_hours
        report.duplicate_queue_seconds_removed = ledger.total_overlap_queue_seconds
        report.duplicates_removed_by_meter = {
            meter.value: amount for meter, amount in ledger.overlap_by_meter.items()
        }
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
    def _fully_absorbed(finding: Finding, credited) -> bool:
        """True when nothing in this claim survived a higher-value finding.

        GPU and queue claims keep the original rule, because the four
        scheduling agents were tuned against it. Other meters are judged on
        their own primary meter — a storage finding has no GPU-hours to lose.
        """
        claim = finding.claim
        if claim.intervals or claim.queue_seconds > 0:
            return (
                credited.attributed_gpu_hours < MIN_ATTRIBUTED_GPU_HOURS
                and credited.attributed_queue_seconds <= 0
            )
        bucket = credited.per_meter.get(claim.primary_meter)
        return bucket is None or bucket.attributed <= MIN_ATTRIBUTED_QUANTITY

    @staticmethod
    def _resource_targets(finding: Finding) -> set[str]:
        """Non-job resources a finding would change: a volume, endpoint, or commitment.

        Two findings cannot both delete the same snapshot or resize the same
        endpoint, so the same conflict rule that protects a job protects these.
        """
        action = finding.alternative.proposed_action or {}
        targets: set[str] = set()
        for key in ("resource_id", "volume_id", "endpoint_id", "commitment_id", "artifact_id"):
            value = action.get(key)
            if value:
                targets.add(f"{key}:{value}")
        resource_id = (finding.evidence or {}).get("resource_id")
        if resource_id and finding.objective is not None:
            targets.add(f"{finding.objective.value}:{resource_id}")
        return targets

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

    def _exclusive_keys(self, finding: Finding) -> set[str]:
        """Everything this finding would take exclusive control of.

        Two findings conflict exactly when these sets intersect: the same job
        resized twice, the same volume deleted twice, the same waiting job
        started by two different releases.
        """
        keys = set(self._mutation_targets(finding))
        keys |= self._resource_targets(finding)
        keys |= {f"queue_beneficiary:{jid}" for jid in finding.claim.queue_job_ids}
        return keys

    def _conflict_pairs(self, findings: list[Finding]) -> set[tuple[str, str]]:
        """Unordered pairs that cannot both be applied.

        Built by inverting the key sets, so this stays linear in the number of
        findings rather than quadratic. Only findings that actually touch the
        same resource ever meet.
        """
        by_key: dict[str, list[str]] = {}
        for finding in findings:
            for key in self._exclusive_keys(finding):
                by_key.setdefault(key, []).append(finding.opportunity_id)

        pairs: set[tuple[str, str]] = set()
        for holders in by_key.values():
            if len(holders) < 2:
                continue
            unique = sorted(set(holders))
            for i, a in enumerate(unique):
                for b in unique[i + 1 :]:
                    pairs.add((a, b))
        return pairs

    def _conflict_reason(
        self,
        finding: Finding,
        winners: list[str],
        by_id: dict[str, Finding],
    ) -> str:
        """Why this finding was dropped, in terms a reviewer can check."""
        if not winners:
            return (
                "Dropped by global conflict selection: it cannot be applied alongside the "
                "higher-value set that was kept."
            )
        contested = sorted(self._exclusive_keys(finding) & self._exclusive_keys(by_id[winners[0]]))
        what = contested[0].split(":", 1)[-1] if contested else "the same resource"
        others = (
            f" and {len(winners) - 1} other selected finding(s)" if len(winners) > 1 else ""
        )
        return (
            f"Both this and finding {winners[0]}{others} would change {what}, and only one "
            "can be applied. The selected set is worth more in total."
        )

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
        for resource in self._resource_targets(finding):
            winner = claimed_targets.get(resource)
            if winner:
                return winner, (
                    f"A higher-value finding already changes {resource.split(':', 1)[-1]}; two "
                    "conflicting actions cannot both be applied."
                )
        for job_id in finding.claim.queue_job_ids:
            winner = claimed_beneficiaries.get(job_id)
            if winner:
                return winner, (
                    f"A higher-value finding already starts {job_id} earlier; its wait can only "
                    "be recovered once."
                )
        return None
