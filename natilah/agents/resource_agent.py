"""Base class for the non-scheduling domains.

`SpecializedAgent` is built around a scheduler decision: reconstruct the
cluster at instant T, ask what else the scheduler could have done with these
GPUs. Most waste does not have that shape. An orphaned volume was not a
decision, it is a standing condition. A commitment expiring unused is an
accounting fact. A capped GPU is a property of the hardware right now.

`ResourceAgent` keeps every guarantee that makes a finding cheap to trust —
multiple candidates, deterministic validation, rejects kept with reasons, an
explicit claim that pricing and deduplication both read, confidence scored
from stated factors — and drops only the parts that assume a scheduler
decision. Subclasses supply four things:

    detect            what the condition looks like in the data
    generate_candidates   what could be done about it
    validate_candidate    the hard checks that make it real
    recommended_action    the sentence an engineer acts on

Every agent declares one meter. That is the design rule from the vision doc:
a new agent earns its place by watching a cost nobody was watching, not by
having another opinion about GPU-hours.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.agents.base_agent import InfrastructureAgent
from natilah.engine.meters import MeterPricing
from natilah.engine.value_calculator import default_economic_config
from natilah.models.database import CostConfigModel, load_cluster_dataset
from natilah.models.domain import (
    AgentRunSummary,
    Alternative,
    CandidateRecord,
    ClusterDataset,
    ComparisonResult,
    ConfidenceAssessment,
    ConfidenceFactor,
    DecisionMetrics,
    EconomicConfig,
    Finding,
    MetricsDelta,
    ResourceClaim,
    SchedulerDecision,
    TimeRange,
    ValueEstimate,
)
from natilah.models.enums import (
    AgentObjective,
    CandidateOutcome,
    ConfidenceLevel,
    DecisionType,
    Meter,
    OpportunityType,
)
from natilah.safety.guards import Action, SafetyGuard

logger = logging.getLogger(__name__)

MIN_CLAIMED_QUANTITY = 1e-6


@dataclass
class ResourceObservation:
    """A standing condition worth investigating. Not a recommended action."""

    observation_id: str
    signal_type: OpportunityType
    resource_id: str
    timestamp: datetime
    severity: float
    description: str
    affected_job_ids: list[str] = field(default_factory=list)
    affected_gpu_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    # Confidence inputs the domain knows and the scorer cannot infer.
    data_completeness: float = 1.0
    signal_strength: float = 1.0
    recurrence: int = 0


@dataclass
class ResourceCandidate:
    """A drafted alternative before validation or pricing."""

    kind: str
    description: str
    proposed_action: dict
    rationale: str
    source: str
    claim: ResourceClaim
    tier: str | None = None
    traffic_kind: str | None = None
    gpu_rate: float | None = None
    # For cases where the saving is in the price, not the quantity: shifting a
    # deferrable job off-peak moves the same kWh at a cheaper rate.
    rate_override: float | None = None
    rate_explanation: str = ""


@dataclass
class _Evaluated:
    alternative: Alternative
    record: CandidateRecord
    claim: ResourceClaim | None = None
    value: ValueEstimate | None = None
    confidence: ConfidenceAssessment | None = None
    score: float = 0.0


class ResourceAgent(InfrastructureAgent):
    """One agent, one meter, the same output contract as every other agent."""

    name: str = "resource"
    objective: AgentObjective
    primary_meter: Meter = Meter.GPU_HOURS
    signal_types: tuple[OpportunityType, ...] = ()
    finding_title: str = "Resource finding"
    max_candidates: int = 6

    def __init__(
        self,
        economic_config: EconomicConfig | None = None,
        pricing: MeterPricing | None = None,
        **_ignored,
    ):
        super().__init__()
        self.domain = self.objective.value
        self.economic_config = economic_config or default_economic_config()
        self.pricing = pricing or MeterPricing(self.economic_config)
        self.summary = self._fresh_summary()

    def use_llm(self) -> bool:
        return False

    # ------------------------------------------------------------- subclasses

    @abstractmethod
    def detect(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        """Standing conditions in this domain. Signals, not fixes."""

    @abstractmethod
    def generate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        """Draft several credible alternatives. May return []."""

    @abstractmethod
    def recommended_action(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        """One sentence an engineer can act on, subject to human approval."""

    def validate_candidate(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> tuple[list[str], list[str]]:
        """Domain-specific hard checks. Returns (checked, violations)."""
        return [], []

    def claim_cap(self, dataset: ClusterDataset, observation: ResourceObservation) -> float:
        """Most this condition could possibly recover, in the primary meter."""
        return float("inf")

    # ------------------------------------------------------------------ entry

    async def analyze(
        self,
        session: AsyncSession,
        time_range: TimeRange | None = None,
    ) -> list[Finding]:
        self.safety.check_action(Action(name="analyze_cluster", is_read_only=True))
        dataset = await load_cluster_dataset(session)
        cost_row = await session.get(CostConfigModel, 1)
        if cost_row is not None:
            self.economic_config = default_economic_config(cost_row.cost_per_gpu_hour)
            self.pricing = MeterPricing(self.economic_config)
        return self.analyze_dataset(dataset, time_range=time_range)

    def analyze_dataset(
        self,
        dataset: ClusterDataset,
        reconstructor=None,
        history=None,
        time_range: TimeRange | None = None,
    ) -> list[Finding]:
        """Same signature the coordinator uses for every agent.

        `reconstructor` and `history` are scheduler-decision machinery and are
        accepted only so the coordinator can treat all agents alike.
        """
        self.summary = self._fresh_summary()
        try:
            observations = self.detect(dataset)
        except Exception:
            logger.exception("%s detection failed", self.name)
            return []
        if self.signal_types:
            observations = [o for o in observations if o.signal_type in self.signal_types]
        if time_range:
            observations = [
                o for o in observations if time_range.start <= o.timestamp <= time_range.end
            ]
        self.summary.observations = len(observations)

        analysis_hours = self.analysis_hours(dataset)
        findings: list[Finding] = []
        for observation in observations:
            try:
                finding = self.evaluate(dataset, observation, analysis_hours)
            except Exception:
                logger.exception("%s failed on %s", self.name, observation.observation_id)
                continue
            if finding is not None:
                findings.append(finding)

        findings.sort(key=lambda f: f.selection_score, reverse=True)
        self.summary.findings = len(findings)
        self.summary.claimed_gpu_hours = sum(f.claim.gpu_hours for f in findings)
        self.summary.claimed_monthly_value = sum(f.value.estimated_monthly_value for f in findings)
        return findings

    # ------------------------------------------------------------- evaluation

    def evaluate(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        analysis_hours: float,
    ) -> Finding | None:
        candidates = list(self.generate_candidates(dataset, observation))[: self.max_candidates]
        self.summary.candidates_generated += len(candidates)
        if not candidates:
            return None

        evaluated = [
            self.evaluate_candidate(dataset, observation, c, analysis_hours) for c in candidates
        ]
        feasible = [e for e in evaluated if e.record.outcome == CandidateOutcome.FEASIBLE]
        self.summary.candidates_rejected_infeasible += sum(
            1 for e in evaluated if e.record.outcome == CandidateOutcome.INFEASIBLE
        )
        self.summary.candidates_rejected_no_gain += sum(
            1 for e in evaluated if e.record.outcome == CandidateOutcome.NO_IMPROVEMENT
        )
        if not feasible:
            return None

        best = max(feasible, key=lambda e: e.score)
        best.record.outcome = CandidateOutcome.SELECTED
        chosen = candidates[evaluated.index(best)]
        return self.build_finding(
            dataset, observation, best, chosen, [e.record for e in evaluated], analysis_hours
        )

    def evaluate_candidate(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
        analysis_hours: float,
    ) -> _Evaluated:
        alternative = Alternative(
            alternative_id=str(uuid4()),
            description=candidate.description,
            proposed_action=candidate.proposed_action,
            generation_method=candidate.source,
            agent_name=self.name,
            agent_rationale=candidate.rationale,
        )
        record = CandidateRecord(
            alternative_id=alternative.alternative_id,
            description=alternative.description,
            generation_method=alternative.generation_method,
            outcome=CandidateOutcome.INFEASIBLE,
        )

        checked, violations = self.validate_candidate(dataset, observation, candidate)
        record.constraints_checked = checked
        record.violations = violations
        if violations:
            record.rejection_reason = "; ".join(violations[:4])
            return _Evaluated(alternative=alternative, record=record)

        claim = candidate.claim
        claim.primary_meter = self.primary_meter
        quantity = claim.primary_quantity
        cap = self.claim_cap(dataset, observation)
        if quantity > cap * 1.001:
            record.outcome = CandidateOutcome.NO_IMPROVEMENT
            record.rejection_reason = (
                f"Claim of {quantity:,.2f} {self.primary_meter.unit_label} exceeds the "
                f"{cap:,.2f} this condition could release."
            )
            return _Evaluated(alternative=alternative, record=record)
        if quantity <= MIN_CLAIMED_QUANTITY:
            record.outcome = CandidateOutcome.NO_IMPROVEMENT
            record.rejection_reason = (
                f"Alternative recovers no measurable {self.primary_meter.unit_label}."
            )
            return _Evaluated(alternative=alternative, record=record)

        alternative.constraints_satisfied = checked
        value = self.pricing.estimate(
            claim,
            analysis_hours=analysis_hours,
            economic_config=self.economic_config,
            tier=candidate.tier,
            kind=candidate.traffic_kind,
            gpu_rate=candidate.gpu_rate,
            rate_override=candidate.rate_override,
            rate_explanation=candidate.rate_explanation,
        )
        confidence = self.assess_confidence(observation, alternative, checked)

        record.outcome = CandidateOutcome.FEASIBLE
        record.gpu_hours_saved = claim.gpu_hours
        record.monthly_value = value.estimated_monthly_value
        record.confidence_score = confidence.score
        return _Evaluated(
            alternative=alternative,
            record=record,
            claim=claim,
            value=value,
            confidence=confidence,
            score=value.estimated_monthly_value * confidence.score,
        )

    # ------------------------------------------------------------- confidence

    def assess_confidence(
        self,
        observation: ResourceObservation,
        alternative: Alternative,
        constraints_checked: list[str],
    ) -> ConfidenceAssessment:
        """Same five-factor shape the GPU agents use, sourced per domain.

        Findings from different domains land in one ranked list, so they have
        to be scored on comparable terms.
        """
        completeness = max(0.0, min(1.0, observation.data_completeness))
        signal = max(0.0, min(1.0, observation.signal_strength))
        coverage = min(1.0, len(constraints_checked) / 4.0)
        feasibility = 0.85 if alternative.proposed_action else 0.2
        historical = min(1.0, 0.4 + 0.2 * observation.recurrence)

        factors = [
            ConfidenceFactor(
                name="data_completeness",
                weight=0.20,
                score=completeness,
                reason=(
                    "Domain telemetry covers the claimed window"
                    if completeness >= 0.8
                    else "Partial telemetry for the claimed resource"
                ),
            ),
            ConfidenceFactor(
                name="signal_strength",
                weight=0.25,
                score=signal,
                reason=observation.evidence.get("signal_reason", observation.description),
            ),
            ConfidenceFactor(
                name="constraint_coverage",
                weight=0.20,
                score=coverage,
                reason=f"{len(constraints_checked)} domain constraints evaluated",
            ),
            ConfidenceFactor(
                name="alternative_feasibility",
                weight=0.20,
                score=feasibility,
                reason="Alternative passed the domain's hard checks",
            ),
            ConfidenceFactor(
                name="historical_consistency",
                weight=0.15,
                score=historical,
                reason=(
                    f"Pattern seen on {observation.recurrence} similar resource(s)"
                    if observation.recurrence
                    else "Single occurrence in this window"
                ),
            ),
        ]
        score = sum(f.weight * f.score for f in factors)
        if score >= 0.75:
            level = ConfidenceLevel.HIGH
        elif score >= 0.50:
            level = ConfidenceLevel.MEDIUM
        else:
            level = ConfidenceLevel.LOW

        uncertainty: list[str] = []
        if completeness < 0.8:
            uncertainty.append("Incomplete telemetry for the claimed resource")
        if not observation.recurrence:
            uncertainty.append("Pattern has not been shown to recur")
        return ConfidenceAssessment(
            score=round(score, 4),
            level=level,
            factors=factors,
            assumptions=[
                "Observed state is representative of steady-state behaviour.",
                "No unobserved dependency requires the resource to stay as it is.",
                "The alternative is a feasible counterfactual, not a production change.",
            ],
            constraints_checked=constraints_checked,
            uncertainty_sources=uncertainty,
            explanation=(
                f"{alternative.agent_rationale} Confidence is {level.value} ({score:.2f}), "
                f"metered in {self.primary_meter.unit_label}."
            ),
        )

    # ---------------------------------------------------------------- finding

    def build_finding(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        best: _Evaluated,
        candidate: ResourceCandidate,
        records: list[CandidateRecord],
        analysis_hours: float,
    ) -> Finding:
        decision = SchedulerDecision(
            decision_id=f"{self.objective.value}:{observation.resource_id}",
            timestamp=observation.timestamp,
            decision_type=DecisionType.ALLOCATE,
            job_id=observation.affected_job_ids[0] if observation.affected_job_ids else "",
            chosen_action={
                "observed_state": observation.description,
                "resource_id": observation.resource_id,
                "meter": self.primary_meter.value,
            },
        )
        evidence = {
            "objective": self.objective.value,
            "agent": self.name,
            "meter": self.primary_meter.value,
            "resource_id": observation.resource_id,
            "observed_state": observation.description,
            "detector_evidence": observation.evidence,
            "analysis_hours": analysis_hours,
            "candidates_evaluated": len(records),
            "candidates_rejected": sum(
                1 for r in records if r.outcome != CandidateOutcome.SELECTED
            ),
            "claim_basis": best.claim.basis if best.claim else "",
        }
        return Finding(
            opportunity_id=str(uuid4()),
            opportunity_type=observation.signal_type,
            decision=decision,
            severity=observation.severity,
            title=self.finding_title,
            description=observation.description,
            detected_at=datetime.now(timezone.utc),
            affected_job_ids=observation.affected_job_ids,
            affected_gpu_ids=observation.affected_gpu_ids,
            alternative=best.alternative,
            comparison=self.empty_comparison(),
            value=best.value,
            confidence=best.confidence,
            agent_name=self.name,
            objective=self.objective,
            recommended_action=self.recommended_action(dataset, observation, candidate),
            claim=best.claim,
            candidates_considered=records,
            evidence=evidence,
            selection_score=best.score,
        )

    @staticmethod
    def empty_comparison() -> ComparisonResult:
        """Findings outside scheduling have no GPU metrics to compare.

        The delta is carried by the claim instead; this keeps the persisted
        shape identical rather than pretending a simulation happened.
        """
        blank = DecisionMetrics(
            gpu_hours=0.0,
            avg_gpu_utilization=0.0,
            avg_memory_utilization=0.0,
            idle_gpu_hours=0.0,
            fragmentation_score=0.0,
            queue_time_seconds=0.0,
            jobs_completable=0,
            throughput_jobs_per_hour=0.0,
        )
        return ComparisonResult(
            actual=blank,
            alternative=blank.model_copy(),
            delta=MetricsDelta(
                gpu_hours_saved=0.0,
                utilization_improvement=0.0,
                idle_hours_recovered=0.0,
                fragmentation_reduction=0.0,
                queue_time_reduction=0.0,
                additional_jobs_serviceable=0,
            ),
        )

    # ----------------------------------------------------------------- helpers

    def analysis_hours(self, dataset: ClusterDataset) -> float:
        window = dataset.window()
        if window is None:
            return 24.0
        return max((window[1] - window[0]).total_seconds() / 3600.0, 1.0)

    def gpu_rate(self, gpu_type: str | None) -> float:
        costs = self.economic_config.cost_per_gpu_hour
        if gpu_type and gpu_type in costs:
            return costs[gpu_type]
        from natilah.models.domain import resolve_gpu_type

        if gpu_type:
            resolved = resolve_gpu_type(gpu_type).name
            if resolved in costs:
                return costs[resolved]
        return costs.get("A100-80GB", 2.21)

    def _fresh_summary(self) -> AgentRunSummary:
        return AgentRunSummary(agent_name=self.name, objective=self.objective)
