"""Idle-allocation agent.

Objective: GPUs that were held but did no work. Nothing else.

The agent looks at per-GPU telemetry for the observed hold, drafts several
ways the hold could have been shorter or smaller, validates each against the
reconstructed state, and claims only the GPU-hours that were provably dead.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean

from natilah.agents.base_agent import CandidateProposal, SpecializedAgent
from natilah.agents.claims import attach_claim, explicit_claim, intervals_for, parse_dt
from natilah.agents.toolbox import (
    ACTIVE_PCT,
    IDLE_PCT,
    AgentContext,
    dead_and_active_gpus,
    gpus_ranked_by_activity,
)
from natilah.engine.opportunity_detector import IdleAllocationDetector, SignalDetector
from natilah.models.domain import Alternative, ComparisonResult, ResourceClaim
from natilah.models.enums import AgentObjective, OpportunityType

MIN_TAIL_MINUTES = 15.0


class IdleAllocationAgent(SpecializedAgent):
    name = "idle_allocation_agent"
    objective = AgentObjective.IDLE_ALLOCATION
    signal_types = (OpportunityType.IDLE_ALLOCATION,)
    finding_title = "Idle GPU allocation"

    def build_detectors(self) -> list[SignalDetector]:
        return [IdleAllocationDetector()]

    def investigation_plan(self, ctx: AgentContext) -> list[tuple[str, dict]]:
        return [
            ("inspect_utilization", {}),
            ("inspect_utilization_timeline", {}),
            ("inspect_job_constraints", {}),
            ("probe_release_idle_gpus", {}),
            ("probe_backfill_candidates", {"gpu_ids": ctx.allocated_gpu_ids}),
            ("inspect_history", {}),
        ]

    # ------------------------------------------------------------- candidates

    def generate_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        window = ctx.hold_window()
        allocated = ctx.allocated_gpu_ids
        if window is None or not allocated:
            return []
        dead, active = dead_and_active_gpus(ctx)
        proposals: list[CandidateProposal] = []
        job_id = ctx.job.job_id if ctx.job else ""
        hold_hours = (window[1] - window[0]).total_seconds() / 3600.0

        if dead and not active:
            action = {
                "kind": "release_gpus",
                "gpu_count": 0,
                "release_gpu_ids": list(allocated),
                "original_gpu_count": len(allocated),
            }
            attach_claim(action, allocated, window, "whole allocation idle for the full hold")
            proposals.append(
                CandidateProposal(
                    kind="release_gpus",
                    description=(
                        f"Do not hold {len(allocated)} GPUs for {job_id}: every GPU stayed below "
                        f"{IDLE_PCT:.0f}% utilization for the entire {hold_hours:.1f}h hold."
                    ),
                    proposed_action=action,
                    rationale=(
                        "Per-GPU telemetry shows no GPU in the allocation crossed the idle "
                        "threshold at any sample during the hold."
                    ),
                    source="tool:probe_release_idle_gpus",
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )

        if dead and active:
            action = {
                "kind": "release_gpus",
                "gpu_count": len(active),
                "release_gpu_ids": list(dead),
                "original_gpu_count": len(allocated),
            }
            attach_claim(action, dead, window, "GPUs in the allocation that never left idle")
            proposals.append(
                CandidateProposal(
                    kind="release_gpus",
                    description=(
                        f"Hold only the {len(active)} working GPUs for {job_id} and release the "
                        f"{len(dead)} that never left idle."
                    ),
                    proposed_action=action,
                    rationale=(
                        f"{len(dead)} of {len(allocated)} GPUs stayed below {IDLE_PCT:.0f}% for the "
                        "whole hold while the rest carried the work."
                    ),
                    source="tool:probe_release_idle_gpus:subset",
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )

        if len(allocated) >= 2:
            ranked = gpus_ranked_by_activity(ctx)
            keep, release = ranked[:1], ranked[1:]
            node_ids = self._nodes_for(ctx, keep)
            action = {
                "kind": "resize",
                "gpu_count": 1,
                "requested_gpus": 1,
                "gpu_ids": keep,
                "node_ids": node_ids,
                "original_gpu_count": len(allocated),
            }
            attach_claim(action, release, window, "GPUs beyond a single-GPU hold")
            proposals.append(
                CandidateProposal(
                    kind="resize",
                    description=(
                        f"Hold a single GPU ({keep[0]}) for {job_id} instead of {len(allocated)}."
                    ),
                    proposed_action=action,
                    rationale=(
                        "If the session had to stay resident, one GPU covers the observed "
                        "activity; the rest of the allocation was dead capacity."
                    ),
                    source="tool:inspect_utilization:single_gpu_hold",
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )

        tail = self._tail_window(ctx, evidence, window)
        if tail is not None:
            tail_hours = (tail[1] - tail[0]).total_seconds() / 3600.0
            action = {
                "kind": "release_gpus",
                "gpu_count": 0,
                "release_gpu_ids": list(allocated),
                "original_gpu_count": len(allocated),
                "release_after": tail[0].isoformat(),
            }
            attach_claim(action, allocated, tail, "hold that continued after the last active sample")
            proposals.append(
                CandidateProposal(
                    kind="release_gpus",
                    description=(
                        f"Release {job_id}'s {len(allocated)} GPUs at {tail[0].isoformat()}, when its "
                        f"last active sample was recorded, instead of holding a further {tail_hours:.1f}h."
                    ),
                    proposed_action=action,
                    rationale=(
                        "Telemetry stops showing work after that timestamp while the allocation "
                        "stayed open."
                    ),
                    source="tool:inspect_utilization_timeline",
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )
        return proposals

    def _tail_window(self, ctx: AgentContext, evidence: dict, window):
        timeline = (evidence.get("tools") or {}).get("inspect_utilization_timeline") or {}
        last_active = parse_dt(timeline.get("last_active_timestamp"))
        if last_active is None:
            return None
        if last_active <= window[0] or last_active >= window[1]:
            return None
        if (window[1] - last_active).total_seconds() < MIN_TAIL_MINUTES * 60:
            return None
        return last_active, window[1]

    def _nodes_for(self, ctx: AgentContext, gpu_ids: list[str]) -> list[str]:
        gpus = ctx.dataset.gpu_by_id()
        return sorted({gpus[gid].node_id for gid in gpu_ids if gid in gpus})

    # ------------------------------------------------------------- validation

    def extra_validation(self, ctx: AgentContext, alternative: Alternative) -> tuple[list[str], list[str]]:
        checked = ["telemetry_coverage", "hold_window_known", "released_gpus_idle_in_window"]
        violations: list[str] = []
        action = alternative.proposed_action or {}
        window = ctx.hold_window()
        if window is None:
            return checked, ["Hold window could not be reconstructed from allocation or telemetry"]

        allocated = set(ctx.allocated_gpu_ids)
        released = self._released_gpu_ids(ctx, action)
        if not released:
            violations.append("Alternative releases no GPU from the observed allocation")
        outside = released - allocated
        if outside:
            violations.append(f"Alternative releases GPUs not in the allocation: {sorted(outside)[:3]}")

        claim_window = (
            parse_dt(action.get("claim_start")) or window[0],
            parse_dt(action.get("claim_end")) or window[1],
        )
        means = self._window_means(ctx, claim_window)
        if not means:
            violations.append("No telemetry samples cover the claimed window")
        covered = len(set(means) & allocated) / max(len(allocated), 1)
        if means and covered < 0.5:
            violations.append(
                f"Telemetry covers only {covered:.0%} of the allocated GPUs; release is unproven"
            )
        for gpu_id in sorted(released):
            value = means.get(gpu_id)
            if value is None:
                continue
            if value >= ACTIVE_PCT:
                violations.append(f"GPU {gpu_id} averaged {value:.1f}% in the claimed window")
            elif value >= IDLE_PCT:
                violations.append(f"GPU {gpu_id} was not idle ({value:.1f}%) in the claimed window")
        return checked, violations

    def _released_gpu_ids(self, ctx: AgentContext, action: dict) -> set[str]:
        released = set(action.get("release_gpu_ids") or [])
        if released:
            return released
        if action.get("kind") == "resize":
            keep = set(action.get("gpu_ids") or [])
            if keep:
                return set(ctx.allocated_gpu_ids) - keep
            target = int(action.get("gpu_count") or 0)
            ranked = gpus_ranked_by_activity(ctx)
            return set(ranked[target:])
        return set(action.get("claim_gpu_ids") or [])

    def _window_means(self, ctx: AgentContext, window) -> dict[str, float]:
        job_id = ctx.job.job_id if ctx.job else ""
        start, end = window
        per_gpu: dict[str, list[float]] = defaultdict(list)
        for sample in ctx.dataset.samples_for_job(job_id):
            if start <= sample.timestamp <= end:
                per_gpu[sample.gpu_id].append(sample.gpu_utilization_pct)
        return {gid: mean(vals) for gid, vals in per_gpu.items() if vals}

    # ------------------------------------------------------------------ claim

    def build_claim(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> ResourceClaim:
        action = alternative.proposed_action or {}
        explicit = explicit_claim(action, "idle GPU-hours released")
        if explicit is not None and explicit.intervals:
            return explicit
        window = ctx.hold_window()
        released = sorted(self._released_gpu_ids(ctx, action))
        return ResourceClaim(
            intervals=intervals_for(released, window),
            basis="idle GPU-hours released (derived from the proposed action)",
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
        released = sorted(self._released_gpu_ids(ctx, action))
        nodes = ", ".join(self._nodes_for(ctx, released)) or "unknown node"
        after = action.get("release_after")
        when = f" from {after}" if after else ""
        return (
            f"Reclaim {len(released)} idle GPU(s) held by {job_id} on {nodes}{when} "
            f"({', '.join(released[:6])}{'...' if len(released) > 6 else ''}). "
            "Confirm with the job owner, then enforce via an idle-reaper policy or a shorter "
            "walltime for this job family. Requires human approval; Natilah changes nothing."
        )
