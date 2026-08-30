"""Agent abstractions. Agents observe, propose counterfactuals, and never execute.

`SpecializedAgent` is the shared machinery behind every objective-specific
agent. Each subclass owns exactly one optimization objective and supplies
three things: which signals it reacts to, how it drafts candidate alternatives,
and which GPU-hours it claims. Everything else — validation, simulation,
valuation, confidence, and the structured output contract — is identical
across agents so the coordination layer can compare them on equal terms.

Pipeline per observed decision X:

    reconstruct state  ->  investigate with read-only tools
    ->  generate multiple candidate Y (tools + optional LLM)
    ->  validate each Y deterministically against that state
    ->  simulate each surviving Y
    ->  price each Y from its explicit resource claim
    ->  score confidence
    ->  select the highest-value feasible Y, keep the rejects as evidence
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.agents.llm import llm_available, plan_investigation, propose_alternatives
from natilah.agents.toolbox import AgentContext, run_tool, tool_catalog
from natilah.agents.tools import inspect_utilization
from natilah.config import settings
from natilah.engine.comparator import Comparator
from natilah.engine.confidence import ConfidenceScorer
from natilah.engine.counterfactual import CounterfactualValidator
from natilah.engine.history import HistoricalPatternIndex
from natilah.engine.opportunity_detector import SignalDetector
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.engine.value_calculator import ValueCalculator, default_economic_config
from natilah.models.database import CostConfigModel, load_cluster_dataset
from natilah.models.domain import (
    AgentRunSummary,
    Alternative,
    CandidateRecord,
    ClusterDataset,
    ComparisonResult,
    Finding,
    Observation,
    ResourceClaim,
    TimeRange,
    UtilizationPoint,
    ValueEstimate,
)
from natilah.models.enums import AgentObjective, CandidateOutcome, OpportunityType
from natilah.safety.guards import Action, SafetyGuard

logger = logging.getLogger(__name__)

MIN_CLAIMED_GPU_HOURS = 0.01


class InfrastructureAgent(ABC):
    """Base class for Natilah intelligence agents.

    Workflow:
    1. Observe the decision the existing infrastructure actually made (X)
    2. Reconstruct cluster context around that decision
    3. Identify credible alternative decisions (Y) — the agent's job
    4. Validate that Y was operationally feasible at that moment
    5. Compare X vs Y and calculate the economic difference

    Agents do not schedule, pack, or apply changes. Algorithms such as
    bin-packing may be invoked as tools; they do not define the agent.
    """

    name: str
    domain: str

    def __init__(self):
        self.safety = SafetyGuard()

    @abstractmethod
    async def analyze(self, session: AsyncSession, time_range: TimeRange | None = None) -> list[Finding]:
        ...


@dataclass
class CandidateProposal:
    """A drafted alternative Y before any validation or pricing."""

    kind: str
    description: str
    proposed_action: dict
    rationale: str
    source: str
    tools_invoked: list[str] = field(default_factory=list)


@dataclass
class EvaluatedCandidate:
    alternative: Alternative
    record: CandidateRecord
    comparison: ComparisonResult | None = None
    value: ValueEstimate | None = None
    confidence: object | None = None
    claim: ResourceClaim | None = None
    score: float = 0.0


class SpecializedAgent(InfrastructureAgent):
    """One agent, one optimization objective, one structured output contract."""

    name: str = "specialized"
    objective: AgentObjective
    signal_types: tuple[OpportunityType, ...] = ()
    finding_title: str = "Infrastructure finding"
    max_candidates: int = 8
    max_llm_tool_calls: int = 4

    def __init__(
        self,
        value_calculator: ValueCalculator | None = None,
        use_llm: bool | None = None,
    ):
        super().__init__()
        self.domain = self.objective.value
        self.detectors: list[SignalDetector] = self.build_detectors()
        self.validator = CounterfactualValidator()
        self.comparator = Comparator()
        self.value_calculator = value_calculator or ValueCalculator()
        self.confidence = ConfidenceScorer()
        self._use_llm = use_llm
        self.summary = self._fresh_summary()

    # ------------------------------------------------------------- subclasses

    @abstractmethod
    def build_detectors(self) -> list[SignalDetector]:
        """Signal detectors this agent listens to. One objective, focused signals."""

    @abstractmethod
    def generate_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        """Draft multiple credible alternatives Y from real state. May return []."""

    @abstractmethod
    def build_claim(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> ResourceClaim:
        """Exactly which GPU-hours and queue-seconds this Y would recover."""

    @abstractmethod
    def recommended_action(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> str:
        """One sentence an engineer can act on, subject to human approval."""

    def claim_cap_gpu_hours(self, ctx: AgentContext) -> float:
        """Upper bound on what this observation could possibly recover.

        Guards against a candidate — especially an LLM-drafted one — claiming
        more than the decision ever consumed.
        """
        window = ctx.hold_window()
        if window is None or not ctx.allocated_gpu_ids:
            return float("inf")
        hours = (window[1] - window[0]).total_seconds() / 3600.0
        return hours * len(ctx.allocated_gpu_ids)

    def investigation_plan(self, ctx: AgentContext) -> list[tuple[str, dict]]:
        """Deterministic tool calls every observation of this objective gets."""
        return [
            ("inspect_utilization", {}),
            ("inspect_job_constraints", {}),
            ("list_idle_capacity", {"min_gpus": 1}),
            ("inspect_history", {}),
        ]

    def extra_validation(self, ctx: AgentContext, alternative: Alternative) -> tuple[list[str], list[str]]:
        """Objective-specific hard checks. Returns (checked, violations)."""
        return [], []

    def state_timestamp(self, observation: Observation) -> datetime:
        """When to reconstruct cluster state for this observation."""
        return observation.timestamp

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
            self.value_calculator = ValueCalculator(default_economic_config(cost_row.cost_per_gpu_hour))
        return self.analyze_dataset(dataset, time_range=time_range)

    def analyze_dataset(
        self,
        dataset: ClusterDataset,
        reconstructor: ClusterStateReconstructor | None = None,
        history: HistoricalPatternIndex | None = None,
        time_range: TimeRange | None = None,
    ) -> list[Finding]:
        self.summary = self._fresh_summary()
        if not dataset.jobs:
            return []
        reconstructor = reconstructor or ClusterStateReconstructor(dataset)
        history = history or HistoricalPatternIndex(dataset)

        observations = self.detect(dataset, reconstructor)
        if time_range:
            observations = [
                obs for obs in observations if time_range.start <= obs.timestamp <= time_range.end
            ]
        self.summary.observations = len(observations)
        history.register_observations(observations)

        findings: list[Finding] = []
        for observation in observations:
            try:
                finding = self.evaluate(observation, dataset, reconstructor, history)
            except Exception:
                logger.exception("%s failed on observation %s", self.name, observation.observation_id)
                continue
            if finding is not None:
                findings.append(finding)

        findings.sort(key=lambda f: f.selection_score, reverse=True)
        self.summary.findings = len(findings)
        self.summary.claimed_gpu_hours = sum(f.claim.gpu_hours for f in findings)
        self.summary.claimed_monthly_value = sum(f.value.estimated_monthly_value for f in findings)
        return findings

    def detect(
        self,
        dataset: ClusterDataset,
        reconstructor: ClusterStateReconstructor,
    ) -> list[Observation]:
        observations: list[Observation] = []
        for detector in self.detectors:
            observations.extend(detector.detect(dataset, reconstructor))
        if self.signal_types:
            observations = [obs for obs in observations if obs.signal_type in self.signal_types]
        return observations

    # ------------------------------------------------------------- evaluation

    def evaluate(
        self,
        observation: Observation,
        dataset: ClusterDataset,
        reconstructor: ClusterStateReconstructor,
        history: HistoricalPatternIndex,
    ) -> Finding | None:
        ctx = self.build_context(observation, dataset, reconstructor, history)
        if ctx is None:
            return None

        evidence = self.collect_evidence(ctx)
        proposals = list(self.generate_candidates(ctx, evidence))
        proposals.extend(self.llm_candidates(ctx, evidence))
        proposals = proposals[: self.max_candidates]
        self.summary.candidates_generated += len(proposals)
        if not proposals:
            return None

        evaluated = [self.evaluate_candidate(ctx, proposal, history) for proposal in proposals]
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
        evidence["candidates_evaluated"] = len(evaluated)
        evidence["candidates_rejected"] = len(evaluated) - len(feasible)
        return self.build_finding(ctx, best, [e.record for e in evaluated], evidence)

    def build_context(
        self,
        observation: Observation,
        dataset: ClusterDataset,
        reconstructor: ClusterStateReconstructor,
        history: HistoricalPatternIndex,
    ) -> AgentContext | None:
        jobs = dataset.job_by_id()
        job_id = observation.decision.job_id
        if job_id not in jobs and observation.affected_job_ids:
            job_id = observation.affected_job_ids[0]
        job = jobs.get(job_id)
        if job is None:
            return None
        state = reconstructor.reconstruct(self.state_timestamp(observation))
        return AgentContext(
            dataset=dataset,
            reconstructor=reconstructor,
            history=history,
            observation=observation,
            state=state,
            job=job,
            allocation=dataset.allocation_by_job().get(job_id),
            utilization=inspect_utilization(dataset, job_id),
            tools_invoked=[],
        )

    # -------------------------------------------------------------- evidence

    def collect_evidence(self, ctx: AgentContext) -> dict:
        evidence: dict = {
            "objective": self.objective.value,
            "agent": self.name,
            "observed_decision": {
                "decision_id": ctx.observation.decision.decision_id,
                "decision_type": ctx.observation.decision.decision_type.value,
                "timestamp": ctx.observation.timestamp.isoformat(),
                "job_id": ctx.job.job_id if ctx.job else None,
                "allocated_gpus": len(ctx.allocated_gpu_ids),
                "nodes": list(ctx.allocation.node_ids) if ctx.allocation else [],
                "description": ctx.observation.description,
            },
            "detector_evidence": ctx.observation.evidence,
            "tools": {},
        }
        for name, args in self.investigation_plan(ctx):
            evidence["tools"][name] = run_tool(name, ctx, args)
        return evidence

    def use_llm(self) -> bool:
        if self._use_llm is not None:
            return self._use_llm and llm_available()
        mode = (settings.agent_mode or "hybrid").lower()
        return mode in {"llm", "hybrid"} and llm_available()

    def llm_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        """LLM investigates the evidence, may request more tools, then drafts Y."""
        if not self.use_llm():
            return []
        self.summary.llm_used = True
        requested = plan_investigation(
            self.objective.value, evidence, tool_catalog(), self.max_llm_tool_calls
        )
        if requested:
            follow_up = {}
            for call in requested:
                follow_up[call["tool"]] = run_tool(call["tool"], ctx, call.get("args") or {})
            evidence["llm_investigation"] = {
                "requested_tools": [c["tool"] for c in requested],
                "results": follow_up,
            }
        proposals: list[CandidateProposal] = []
        for raw in propose_alternatives(self.objective.value, evidence):
            action = raw.get("proposed_action")
            if not isinstance(action, dict):
                continue
            proposals.append(
                CandidateProposal(
                    kind=str(action.get("kind") or "unspecified"),
                    description=str(raw.get("description") or "LLM-proposed alternative"),
                    proposed_action=action,
                    rationale=str(raw.get("rationale") or ""),
                    source=f"llm:{settings.xai_model}",
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )
        return proposals

    # ------------------------------------------------------- candidate ladder

    def evaluate_candidate(
        self,
        ctx: AgentContext,
        proposal: CandidateProposal,
        history: HistoricalPatternIndex,
    ) -> EvaluatedCandidate:
        alternative = Alternative(
            alternative_id=str(uuid4()),
            description=proposal.description,
            proposed_action=proposal.proposed_action,
            generation_method=proposal.source,
            agent_name=self.name,
            agent_rationale=proposal.rationale,
            tools_invoked=list(proposal.tools_invoked or ctx.tools_invoked or []),
        )
        record = CandidateRecord(
            alternative_id=alternative.alternative_id,
            description=alternative.description,
            generation_method=alternative.generation_method,
            outcome=CandidateOutcome.INFEASIBLE,
            tools_invoked=alternative.tools_invoked,
        )

        feasibility = self.validator.validate(
            alternative,
            ctx.job,
            ctx.state,
            ctx.dataset,
            exclude_job_id=ctx.job.job_id if ctx.job else None,
        )
        extra_checked, extra_violations = self.extra_validation(ctx, alternative)
        checked = feasibility.constraints_checked + extra_checked
        violations = feasibility.violations + extra_violations
        record.constraints_checked = checked
        record.violations = violations
        if violations:
            record.rejection_reason = "; ".join(violations[:4])
            return EvaluatedCandidate(alternative=alternative, record=record)

        alternative.constraints_satisfied = checked
        comparison = self.comparator.compare(
            ctx.observation, alternative, ctx.dataset, ctx.reconstructor, ctx.state
        )
        claim = self.build_claim(ctx, alternative, comparison)
        cap = self.claim_cap_gpu_hours(ctx)
        if claim.gpu_hours > cap * 1.001:
            record.outcome = CandidateOutcome.NO_IMPROVEMENT
            record.rejection_reason = (
                f"Claim of {claim.gpu_hours:.2f} GPU-h exceeds the {cap:.2f} GPU-h the "
                "observed decision could have released."
            )
            return EvaluatedCandidate(alternative=alternative, record=record, comparison=comparison)
        if claim.gpu_hours < MIN_CLAIMED_GPU_HOURS and claim.queue_seconds <= 0:
            record.outcome = CandidateOutcome.NO_IMPROVEMENT
            record.rejection_reason = "Alternative recovers no measurable GPU-hours or queue time."
            return EvaluatedCandidate(alternative=alternative, record=record, comparison=comparison)

        value = self.value_calculator.estimate(
            comparison,
            ctx.observation,
            ctx.dataset,
            gpu_hours_override=claim.gpu_hours,
            extra_assumptions=[f"Resource claim basis: {claim.basis}"] if claim.basis else None,
        )
        similar = history.recurrence(ctx.job.job_id if ctx.job else "", ctx.observation.signal_type)
        confidence = self.confidence.assess(
            ctx.observation, alternative, ctx.dataset, checked, similar_count=similar
        )

        record.outcome = CandidateOutcome.FEASIBLE
        record.gpu_hours_saved = claim.gpu_hours
        record.queue_time_reduction_seconds = claim.queue_seconds
        record.monthly_value = value.estimated_monthly_value
        record.confidence_score = confidence.score
        return EvaluatedCandidate(
            alternative=alternative,
            record=record,
            comparison=comparison,
            value=value,
            confidence=confidence,
            claim=claim,
            score=value.estimated_monthly_value * confidence.score,
        )

    # ---------------------------------------------------------------- finding

    def build_finding(
        self,
        ctx: AgentContext,
        best: EvaluatedCandidate,
        records: list[CandidateRecord],
        evidence: dict,
    ) -> Finding:
        observation = ctx.observation
        return Finding(
            opportunity_id=str(uuid4()),
            opportunity_type=observation.signal_type,
            decision=observation.decision,
            severity=observation.severity,
            title=self.finding_title,
            description=observation.description,
            detected_at=datetime.now(timezone.utc),
            affected_job_ids=observation.affected_job_ids,
            affected_gpu_ids=observation.affected_gpu_ids,
            alternative=best.alternative,
            comparison=best.comparison,
            value=best.value,
            confidence=best.confidence,
            utilization_series=self.utilization_series(ctx, best.alternative),
            agent_name=self.name,
            objective=self.objective,
            recommended_action=self.recommended_action(ctx, best.alternative, best.comparison),
            claim=best.claim,
            candidates_considered=records,
            evidence=evidence,
            selection_score=best.score,
        )

    def utilization_series(self, ctx: AgentContext, alternative: Alternative) -> list[UtilizationPoint]:
        job_id = ctx.job.job_id if ctx.job else ""
        samples = ctx.dataset.samples_for_job(job_id)
        if not samples:
            return []
        by_ts: dict[datetime, list[float]] = {}
        for sample in samples:
            by_ts.setdefault(sample.timestamp, []).append(sample.gpu_utilization_pct)
        action = alternative.proposed_action or {}
        original = float(action.get("original_gpu_count") or 0) or None
        proposed = float(action.get("gpu_count") or 0) or None
        points: list[UtilizationPoint] = []
        for ts, vals in sorted(by_ts.items())[:48]:
            actual = sum(vals) / len(vals)
            alt_pct = actual
            if original and proposed and proposed < original:
                alt_pct = min(100.0, actual * (original / proposed))
            points.append(UtilizationPoint(timestamp=ts, actual_pct=actual, alternative_pct=alt_pct))
        return points

    def _fresh_summary(self) -> AgentRunSummary:
        return AgentRunSummary(agent_name=self.name, objective=self.objective)
