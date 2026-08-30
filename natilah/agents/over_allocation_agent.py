"""Over-allocation agent.

Objective: jobs that ran, but on more GPUs than their own telemetry ever used.

Distinct from the idle agent: here the job did real work. The question is how
many GPUs that work actually needed, measured against peak concurrent demand
rather than a mean, so a bursty job is not shrunk below its own peak.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from natilah.agents.base_agent import CandidateProposal, SpecializedAgent
from natilah.agents.claims import attach_claim, explicit_claim, intervals_for
from natilah.agents.toolbox import ACTIVE_PCT, AgentContext, gpu_means_for, gpus_ranked_by_activity
from natilah.agents.tools import probe_headroom_size
from natilah.engine.opportunity_detector import OverAllocationDetector, SignalDetector
from natilah.models.domain import Alternative, ComparisonResult, ResourceClaim
from natilah.models.enums import AgentObjective, OpportunityType

HEADROOM_LADDER = (0.10, 0.20, 0.35)


class OverAllocationAgent(SpecializedAgent):
    name = "over_allocation_agent"
    objective = AgentObjective.OVER_ALLOCATION
    signal_types = (OpportunityType.OVER_ALLOCATION,)
    finding_title = "Over-allocated GPU job"

    def __init__(self, *args, **kwargs):
        self._peak_cache: dict[str, int] = {}
        super().__init__(*args, **kwargs)

    def build_detectors(self) -> list[SignalDetector]:
        return [OverAllocationDetector()]

    def investigation_plan(self, ctx: AgentContext) -> list[tuple[str, dict]]:
        plan = [
            ("inspect_utilization", {}),
            ("inspect_utilization_timeline", {}),
            ("inspect_job_constraints", {}),
            ("inspect_history", {}),
        ]
        plan.extend(("probe_headroom_size", {"headroom": h}) for h in HEADROOM_LADDER)
        return plan

    # ------------------------------------------------------------- candidates

    def generate_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        window = ctx.hold_window()
        allocated = ctx.allocated_gpu_ids
        if window is None or len(allocated) < 2 or ctx.utilization is None:
            return []

        ranked = gpus_ranked_by_activity(ctx)
        peak_concurrent = self.peak_concurrent_active(ctx)
        means = gpu_means_for(ctx)
        active = sum(1 for gid in allocated if means.get(gid, 0.0) > ACTIVE_PCT)

        sizes: dict[int, tuple[str, str]] = {}
        for headroom in HEADROOM_LADDER:
            candidate = probe_headroom_size(ctx.utilization, headroom=headroom)
            if candidate is None:
                continue
            size = int(candidate.proposed_action.get("gpu_count") or 0)
            if 0 < size < len(allocated):
                sizes.setdefault(
                    size,
                    (
                        f"tool:probe_headroom_size:{int(headroom * 100)}pct",
                        f"Observed peak plus {int(headroom * 100)}% headroom fits in {size} GPUs.",
                    ),
                )
        if 0 < peak_concurrent < len(allocated):
            sizes.setdefault(
                peak_concurrent,
                (
                    "tool:inspect_utilization_timeline:peak_concurrency",
                    f"At no sample did more than {peak_concurrent} GPU(s) exceed "
                    f"{ACTIVE_PCT:.0f}% at the same time.",
                ),
            )
        if 0 < active < len(allocated):
            sizes.setdefault(
                active,
                (
                    "tool:inspect_utilization:active_subset",
                    f"{active} of {len(allocated)} GPUs averaged above {ACTIVE_PCT:.0f}% "
                    "across the run.",
                ),
            )

        job_id = ctx.job.job_id if ctx.job else ""
        proposals: list[CandidateProposal] = []
        for size, (source, rationale) in sorted(sizes.items()):
            keep = ranked[:size]
            release = ranked[size:]
            action = {
                "kind": "resize",
                "gpu_count": size,
                "requested_gpus": size,
                "gpu_ids": keep,
                "node_ids": self._nodes_for(ctx, keep),
                "original_gpu_count": len(allocated),
                "require_single_node": ctx.job is not None
                and ctx.job.constraints.get("nvlink") == "required",
            }
            attach_claim(action, release, window, f"GPUs beyond a {size}-GPU allocation")
            proposals.append(
                CandidateProposal(
                    kind="resize",
                    description=(
                        f"Allocate {size} GPUs to {job_id} instead of {len(allocated)}."
                    ),
                    proposed_action=action,
                    rationale=rationale,
                    source=source,
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )
        return proposals

    def peak_concurrent_active(self, ctx: AgentContext) -> int:
        """Largest number of GPUs above the active threshold at any one sample."""
        job_id = ctx.job.job_id if ctx.job else ""
        cached = self._peak_cache.get(job_id)
        if cached is not None:
            return cached
        by_ts: dict[object, int] = defaultdict(int)
        for sample in ctx.dataset.samples_for_job(job_id):
            if sample.gpu_utilization_pct > ACTIVE_PCT:
                by_ts[sample.timestamp] += 1
        peak = max(by_ts.values(), default=0)
        self._peak_cache[job_id] = peak
        return peak

    def _nodes_for(self, ctx: AgentContext, gpu_ids: list[str]) -> list[str]:
        gpus = ctx.dataset.gpu_by_id()
        return sorted({gpus[gid].node_id for gid in gpu_ids if gid in gpus})

    # ------------------------------------------------------------- validation

    def extra_validation(self, ctx: AgentContext, alternative: Alternative) -> tuple[list[str], list[str]]:
        checked = [
            "peak_concurrency_covered",
            "removed_gpus_below_active_threshold",
            "nvlink_topology_preserved",
            "telemetry_coverage",
        ]
        violations: list[str] = []
        action = alternative.proposed_action or {}
        allocated = ctx.allocated_gpu_ids
        size = int(action.get("gpu_count") or action.get("requested_gpus") or len(allocated))
        if size < 1:
            violations.append("Alternative leaves the job with no GPU")
        if size >= len(allocated):
            violations.append("Alternative does not reduce the allocation")

        peak = self.peak_concurrent_active(ctx)
        if size < peak:
            violations.append(
                f"{size} GPUs cannot cover the observed peak of {peak} concurrently active GPUs"
            )

        means = gpu_means_for(ctx)
        if not means:
            violations.append("No utilization telemetry for the allocated GPUs")
        elif len(set(means) & set(allocated)) / max(len(allocated), 1) < 0.5:
            violations.append("Telemetry covers under half of the allocated GPUs")

        keep = list(action.get("gpu_ids") or gpus_ranked_by_activity(ctx)[:size])
        removed = [gid for gid in allocated if gid not in set(keep)]
        for gid in removed:
            value = means.get(gid)
            if value is not None and value > ACTIVE_PCT:
                violations.append(f"GPU {gid} averaged {value:.1f}%, above the active threshold")

        if ctx.job is not None and ctx.job.constraints.get("nvlink") == "required":
            if len(self._nodes_for(ctx, keep)) > 1:
                violations.append("NVLink job would be split across nodes by this resize")
        return checked, violations

    # ------------------------------------------------------------------ claim

    def build_claim(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> ResourceClaim:
        action = alternative.proposed_action or {}
        explicit = explicit_claim(action, "GPU-hours released by right-sizing")
        if explicit is not None and explicit.intervals:
            return explicit
        allocated = ctx.allocated_gpu_ids
        size = int(action.get("gpu_count") or action.get("requested_gpus") or len(allocated))
        keep = set(action.get("gpu_ids") or gpus_ranked_by_activity(ctx)[:size])
        release = [gid for gid in allocated if gid not in keep]
        return ResourceClaim(
            intervals=intervals_for(release, ctx.hold_window()),
            basis=(
                "GPU-hours released by right-sizing, assuming the same work runs on the "
                "retained GPUs at the observed peak"
            ),
        )

    # ----------------------------------------------------------- presentation

    def recommended_action(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> str:
        action = alternative.proposed_action or {}
        job_id = ctx.job.job_id if ctx.job else "unknown job"
        size = int(action.get("gpu_count") or 0)
        original = int(action.get("original_gpu_count") or len(ctx.allocated_gpu_ids))
        profile = ctx.history.profile_for(job_id)
        family = f" (job family {profile.family})" if profile else ""
        peak = self.peak_concurrent_active(ctx)
        return (
            f"Right-size {job_id}{family} from {original} to {size} GPUs; peak concurrent demand "
            f"was {peak} GPU(s). Change the submission template for this family and re-measure "
            "one run before applying it broadly. Requires human approval; Natilah changes nothing."
        )
