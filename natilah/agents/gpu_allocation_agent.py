"""V1 GPU allocation agent.

Observes what the existing scheduler did, reconstructs context, and uses
tools (and optionally Grok) to identify feasible counterfactual decisions.
It does not replace the scheduler and does not treat any algorithm as policy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.agents.base_agent import InfrastructureAgent
from natilah.agents.llm import llm_available, propose_with_grok
from natilah.agents.tools import (
    ToolCandidate,
    inspect_utilization,
    list_idle_capacity,
    probe_alternate_placement,
    probe_headroom_size,
    probe_release_idle_gpus,
    probe_unblocked_queue,
)
from natilah.config import settings
from natilah.engine.comparator import Comparator
from natilah.engine.confidence import ConfidenceScorer
from natilah.engine.counterfactual import CounterfactualEngine
from natilah.engine.opportunity_detector import DetectorRegistry
from natilah.engine.state_reconstructor import ClusterStateReconstructor
from natilah.engine.value_calculator import ValueCalculator, default_economic_config
from natilah.models.database import (
    CostConfigModel,
    load_cluster_dataset,
    save_findings,
)
from natilah.models.domain import (
    Alternative,
    ClusterDataset,
    ClusterStateSnapshot,
    Finding,
    Observation,
    TimeRange,
    UtilizationPoint,
)
from natilah.models.enums import OpportunityType
from natilah.safety.guards import Action


class GPUAllocationAgent(InfrastructureAgent):
    name = "gpu_allocation"
    domain = "gpu_allocation"

    def __init__(self, economic: ValueCalculator | None = None):
        super().__init__()
        self.detectors = DetectorRegistry()
        self.counterfactual = CounterfactualEngine()
        self.comparator = Comparator()
        self.value_calculator = economic or ValueCalculator()
        self.confidence = ConfidenceScorer()

    async def analyze(self, session: AsyncSession, time_range: TimeRange | None = None) -> list[Finding]:
        self.safety.check_action(Action(name="analyze_cluster", is_read_only=True))
        dataset = await load_cluster_dataset(session)
        if not dataset.jobs:
            return []
        if time_range:
            dataset.jobs = [j for j in dataset.jobs if time_range.start <= j.submit_time <= time_range.end]

        cost_row = await session.get(CostConfigModel, 1)
        if cost_row is not None:
            self.value_calculator = ValueCalculator(
                default_economic_config(cost_row.cost_per_gpu_hour)
            )

        reconstructor = ClusterStateReconstructor(dataset)
        observations = self.detectors.detect_all(dataset, reconstructor)
        findings: list[Finding] = []
        type_counts: dict[OpportunityType, int] = {}
        for obs in observations:
            type_counts[obs.signal_type] = type_counts.get(obs.signal_type, 0) + 1

        for obs in observations:
            state = reconstructor.reconstruct(obs.timestamp)
            alternatives = self.propose_alternatives(obs, dataset, state, reconstructor)
            job = dataset.job_by_id().get(obs.decision.job_id) or dataset.job_by_id().get(
                obs.affected_job_ids[0] if obs.affected_job_ids else ""
            )
            if job is None:
                continue
            scored: list[Finding] = []
            for alt in alternatives:
                feasibility = self.counterfactual.validate(
                    alt, job, state, dataset, exclude_job_id=job.job_id
                )
                if not feasibility.feasible:
                    continue
                alt.constraints_satisfied = feasibility.constraints_checked
                comparison = self.comparator.compare(obs, alt, dataset, reconstructor, state)
                if (
                    comparison.delta.gpu_hours_saved <= 0
                    and comparison.delta.queue_time_reduction <= 0
                    and comparison.delta.idle_hours_recovered <= 0
                    and comparison.delta.fragmentation_reduction <= 0
                ):
                    continue
                value = self.value_calculator.estimate(comparison, obs, dataset)
                conf = self.confidence.assess(
                    obs,
                    alt,
                    dataset,
                    feasibility.constraints_checked,
                    similar_count=max(0, type_counts.get(obs.signal_type, 1) - 1),
                )
                scored.append(
                    self._to_finding(obs, alt, comparison, value, conf, dataset)
                )
            if scored:
                scored.sort(key=lambda f: f.value.estimated_monthly_value, reverse=True)
                findings.append(scored[0])

        findings.sort(key=lambda f: f.value.estimated_monthly_value, reverse=True)
        await save_findings(session, findings)
        return findings

    def propose_alternatives(
        self,
        observation: Observation,
        dataset: ClusterDataset,
        state: ClusterStateSnapshot,
        reconstructor: ClusterStateReconstructor,
    ) -> list[Alternative]:
        evidence, tool_candidates, tools_invoked = self._collect_evidence(observation, dataset, state)
        alternatives: list[Alternative] = []

        mode = (settings.agent_mode or "hybrid").lower()
        use_llm = mode in {"llm", "hybrid"} and llm_available()
        if use_llm:
            for raw in propose_with_grok(evidence):
                alternatives.append(
                    Alternative(
                        alternative_id=str(uuid4()),
                        description=str(raw.get("description") or "Agent-proposed alternative"),
                        proposed_action=raw.get("proposed_action") or {},
                        generation_method="agent:grok",
                        agent_name=self.name,
                        agent_rationale=str(raw.get("rationale") or ""),
                        tools_invoked=list(raw.get("tools_requested") or tools_invoked),
                    )
                )
            if mode == "llm":
                return alternatives

        for candidate in tool_candidates:
            alternatives.append(self._candidate_to_alternative(candidate, tools_invoked))
        return alternatives

    def _collect_evidence(
        self,
        observation: Observation,
        dataset: ClusterDataset,
        state: ClusterStateSnapshot,
    ) -> tuple[dict, list[ToolCandidate], list[str]]:
        tools_invoked: list[str] = []
        candidates: list[ToolCandidate] = []
        job_id = observation.decision.job_id
        if observation.affected_job_ids and job_id not in dataset.job_by_id():
            job_id = observation.affected_job_ids[0]
        job = dataset.job_by_id().get(job_id)
        alloc = dataset.allocation_by_job().get(job_id)

        report = inspect_utilization(dataset, job_id)
        tools_invoked.append("inspect_utilization")
        idle_caps = list_idle_capacity(
            state,
            gpu_type=job.requested_gpu_type if job else None,
            min_gpus=1,
        )
        tools_invoked.append("list_idle_capacity")

        if report is not None:
            sized = probe_headroom_size(report)
            tools_invoked.append("probe_headroom_size")
            if sized is not None and alloc is not None:
                sized.proposed_action["gpu_ids"] = alloc.gpu_ids[: sized.proposed_action["gpu_count"]]
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
            # Placement tools are available whenever another node could hold the job,
            # not because a detector labeled the event "poor placement".
            if needed >= 2:
                placement = probe_alternate_placement(job, state, current_nodes, needed)
                tools_invoked.append("probe_alternate_placement")
                candidates.extend(placement)

            blocking = list(observation.evidence.get("blocking_jobs") or [])
            if observation.evidence.get("wait_seconds") or blocking or state.pending_jobs:
                waiting = job
                victim_id = None
                if observation.signal_type == OpportunityType.QUEUE_INEFFICIENCY:
                    victim_id = job.job_id
                queued = probe_unblocked_queue(waiting, state, blocking)
                tools_invoked.append("probe_unblocked_queue")
                if queued is not None:
                    candidates.append(queued)
                _ = victim_id

        evidence = {
            "observation": observation.model_dump(mode="json"),
            "utilization": None if report is None else report.__dict__,
            "idle_nodes": [c.model_dump() for c in idle_caps[:12]],
            "pending_jobs": [j.job_id for j in state.pending_jobs[:20]],
            "largest_contiguous_block": state.available_capacity.largest_contiguous_block,
            "tool_candidates": [
                {
                    "kind": c.kind,
                    "description": c.description,
                    "proposed_action": c.proposed_action,
                    "rationale": c.rationale,
                    "tool_name": c.tool_name,
                }
                for c in candidates
            ],
            "note": (
                "Tool candidates are optional instruments. They are not the correct answer. "
                "Reject any that are not operationally feasible or not supported by evidence."
            ),
        }
        return evidence, candidates, tools_invoked

    def _candidate_to_alternative(self, candidate: ToolCandidate, tools_invoked: list[str]) -> Alternative:
        return Alternative(
            alternative_id=str(uuid4()),
            description=candidate.description,
            proposed_action=candidate.proposed_action,
            generation_method=f"agent:{self.name}+{candidate.tool_name}",
            agent_name=self.name,
            agent_rationale=candidate.rationale,
            tools_invoked=tools_invoked,
        )

    def _to_finding(self, obs, alt, comparison, value, conf, dataset: ClusterDataset) -> Finding:
        series = self._series(obs, alt, dataset)
        title = {
            OpportunityType.OVER_ALLOCATION: "Over-allocated GPU job",
            OpportunityType.POOR_PLACEMENT: "Fragmented multi-node placement",
            OpportunityType.FRAGMENTATION: "Stranded GPU capacity",
            OpportunityType.IDLE_ALLOCATION: "Idle GPU allocation",
            OpportunityType.QUEUE_INEFFICIENCY: "Queue wait with unused capacity",
        }.get(obs.signal_type, obs.signal_type.value.replace("_", " ").title())
        return Finding(
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
        )

    def _series(self, obs: Observation, alt: Alternative, dataset: ClusterDataset) -> list[UtilizationPoint]:
        job_id = obs.affected_job_ids[0] if obs.affected_job_ids else obs.decision.job_id
        samples = [s for s in dataset.samples if s.job_id == job_id]
        if not samples:
            return []
        by_ts: dict[datetime, list[float]] = {}
        for sample in samples:
            by_ts.setdefault(sample.timestamp, []).append(sample.gpu_utilization_pct)
        action = alt.proposed_action or {}
        orig = float(action.get("original_gpu_count") or 0) or None
        new = float(action.get("gpu_count") or 0) or None
        points: list[UtilizationPoint] = []
        for ts, vals in sorted(by_ts.items())[:48]:
            actual = sum(vals) / len(vals)
            alt_pct = actual
            if orig and new and new < orig:
                alt_pct = min(100.0, actual * (orig / new))
            points.append(UtilizationPoint(timestamp=ts, actual_pct=actual, alternative_pct=alt_pct))
        return points
