"""Queue-efficiency agent.

Objective: jobs that waited while the capacity to run them existed.

Two shapes are considered separately, because they need different evidence:
capacity that was simply idle at submit time, and capacity that was held but
unused by a running job. Both claims are truncated to the window in which the
GPUs actually stayed available, so a wait is never priced longer than the
capacity that would have covered it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

from natilah.agents.base_agent import CandidateProposal, SpecializedAgent
from natilah.agents.claims import attach_claim, explicit_claim, free_window, parse_dt
from natilah.agents.toolbox import ACTIVE_PCT, AgentContext, wait_window
from natilah.engine.opportunity_detector import QueueInefficiencyDetector, SignalDetector
from natilah.models.domain import (
    Alternative,
    ComparisonResult,
    GPUInterval,
    ResourceClaim,
    gpu_type_matches,
)
from natilah.models.enums import AgentObjective, OpportunityType

MIN_RECOVERABLE_SECONDS = 300.0


class QueueEfficiencyAgent(SpecializedAgent):
    name = "queue_efficiency_agent"
    objective = AgentObjective.QUEUE_EFFICIENCY
    signal_types = (OpportunityType.QUEUE_INEFFICIENCY,)
    finding_title = "Queue wait with usable capacity"

    def build_detectors(self) -> list[SignalDetector]:
        return [QueueInefficiencyDetector()]

    def state_timestamp(self, observation) -> datetime:
        return observation.timestamp + timedelta(seconds=1)

    def investigation_plan(self, ctx: AgentContext) -> list[tuple[str, dict]]:
        needed = ctx.job.requested_gpus if ctx.job else 1
        return [
            ("inspect_job_constraints", {}),
            ("inspect_queue", {"limit": 15}),
            ("list_idle_capacity", {"min_gpus": 1}),
            ("probe_single_node_fit", {"gpu_count": needed}),
            ("probe_blocking_jobs", {}),
            ("inspect_history", {}),
        ]

    def claim_cap_gpu_hours(self, ctx: AgentContext) -> float:
        window = wait_window(ctx.job) if ctx.job else None
        if window is None or ctx.job is None:
            return float("inf")
        hours = (window[1] - window[0]).total_seconds() / 3600.0
        return hours * max(ctx.job.requested_gpus, 1)

    # ------------------------------------------------------------- candidates

    def generate_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        job = ctx.job
        window = wait_window(job) if job else None
        if job is None or window is None:
            return []
        wait_seconds = (window[1] - window[0]).total_seconds()
        proposals: list[CandidateProposal] = []

        idle = self._idle_candidate(ctx, job, window)
        if idle is not None:
            proposals.append(idle)

        for blocker in self._blockers(ctx, job)[:2]:
            proposal = self._blocker_candidate(ctx, job, window, blocker)
            if proposal is not None:
                proposals.append(proposal)

        if not proposals:
            return []
        # Cheapest interpretation first: idle capacity beats reclaiming from a peer.
        proposals.sort(key=lambda p: 0 if p.kind == "reorder_idle" else 1)
        _ = wait_seconds
        return proposals

    def _idle_candidate(self, ctx: AgentContext, job, window) -> CandidateProposal | None:
        needed = job.requested_gpus
        nvlink = job.constraints.get("nvlink") == "required"
        caps = ctx.state.available_capacity.by_node
        chosen: list[str] = []
        nodes: list[str] = []

        single = [
            cap
            for cap in caps.values()
            if cap.idle_gpus >= needed
            and gpu_type_matches(job.requested_gpu_type, cap.gpu_type)
        ]
        if single:
            single.sort(key=lambda c: c.idle_gpus)
            cap = single[0]
            chosen = cap.idle_gpu_ids[:needed]
            nodes = [cap.node_id]
        elif not nvlink:
            for cap in sorted(caps.values(), key=lambda c: c.idle_gpus, reverse=True):
                if not gpu_type_matches(job.requested_gpu_type, cap.gpu_type):
                    continue
                take = cap.idle_gpu_ids[: max(0, needed - len(chosen))]
                if not take:
                    continue
                chosen.extend(take)
                nodes.append(cap.node_id)
                if len(chosen) >= needed:
                    break
        if len(chosen) < needed:
            return None

        intervals, effective_end = self._free_window(ctx, chosen, window, needed)
        if effective_end is None:
            return None
        recoverable = (effective_end - window[0]).total_seconds()
        if recoverable < MIN_RECOVERABLE_SECONDS:
            return None

        action = {
            "kind": "reorder",
            "gpu_count": needed,
            "gpu_ids": chosen[:needed],
            "node_ids": sorted(set(nodes)),
            "require_single_node": nvlink,
            "start_job_id": job.job_id,
            "unblocked_job_ids": [job.job_id],
            "queue_time_reduction_seconds": recoverable,
        }
        attach_claim(
            action,
            [i.gpu_id for i in intervals],
            (window[0], effective_end),
            "idle GPUs that were free while the job queued",
            queue_job_ids=[job.job_id],
            queue_seconds=recoverable,
        )
        return CandidateProposal(
            kind="reorder_idle",
            description=(
                f"Start {job.job_id} at submit time on {', '.join(sorted(set(nodes)))} using "
                f"{needed} idle GPU(s), instead of queueing it for "
                f"{(window[1] - window[0]).total_seconds() / 3600:.1f}h."
            ),
            proposed_action=action,
            rationale=(
                f"At submit time those GPUs were unallocated and matched the request; they stayed "
                f"free for {recoverable / 3600:.1f}h of the observed wait."
            ),
            source="tool:list_idle_capacity",
            tools_invoked=list(ctx.tools_invoked or []),
        )

    def _blocker_candidate(self, ctx: AgentContext, job, window, blocker: dict) -> CandidateProposal | None:
        needed = job.requested_gpus
        unused_ids = blocker.get("unused_gpu_ids") or []
        if len(unused_ids) < needed:
            return None
        chosen = unused_ids[:needed]
        intervals, effective_end = self._free_window(
            ctx, chosen, window, needed, holder_job_id=blocker["job_id"]
        )
        if effective_end is None:
            return None
        recoverable = (effective_end - window[0]).total_seconds()
        if recoverable < MIN_RECOVERABLE_SECONDS:
            return None

        action = {
            "kind": "reorder",
            "gpu_count": needed,
            "start_job_id": job.job_id,
            "unblocked_job_ids": [job.job_id],
            "release_from_job_id": blocker["job_id"],
            "queue_time_reduction_seconds": recoverable,
            "original_gpu_count": blocker.get("allocated"),
        }
        attach_claim(
            action,
            [i.gpu_id for i in intervals],
            (window[0], effective_end),
            "GPUs held but unused by a running job while this job queued",
            queue_job_ids=[job.job_id],
            queue_seconds=recoverable,
        )
        return CandidateProposal(
            kind="reorder_blocker",
            description=(
                f"Reclaim {needed} of the {blocker.get('unused')} GPUs {blocker['job_id']} held "
                f"without using them, and start {job.job_id} instead of queueing it."
            ),
            proposed_action=action,
            rationale=(
                f"{blocker['job_id']} held {blocker.get('allocated')} GPUs with only "
                f"{blocker.get('active')} above {ACTIVE_PCT:.0f}% while {job.job_id} waited."
            ),
            source="tool:probe_blocking_jobs",
            tools_invoked=list(ctx.tools_invoked or []),
        )

    # ---------------------------------------------------------------- helpers

    def _blockers(self, ctx: AgentContext, job) -> list[dict]:
        """Running jobs holding unused GPUs of a type the waiting job could use."""
        alloc_by_job = ctx.dataset.allocation_by_job()
        detector_ids = {
            b.get("job_id") for b in (ctx.observation.evidence.get("blocking_jobs") or [])
        }
        blockers: list[dict] = []
        for running in ctx.state.running_jobs:
            if detector_ids and running.job_id not in detector_ids:
                continue
            alloc = alloc_by_job.get(running.job_id)
            if alloc is None:
                continue
            if not gpu_type_matches(job.requested_gpu_type, running.requested_gpu_type):
                continue
            per_gpu: dict[str, list[float]] = defaultdict(list)
            for sample in ctx.dataset.samples_for_job(running.job_id):
                if sample.timestamp <= (job.start_time or ctx.state.timestamp):
                    per_gpu[sample.gpu_id].append(sample.gpu_utilization_pct)
            if not per_gpu:
                continue
            means = {gid: mean(vals) for gid, vals in per_gpu.items() if vals}
            unused_ids = [gid for gid in alloc.gpu_ids if means.get(gid, 0.0) <= ACTIVE_PCT]
            active = len(alloc.gpu_ids) - len(unused_ids)
            if len(unused_ids) < job.requested_gpus:
                continue
            blockers.append(
                {
                    "job_id": running.job_id,
                    "allocated": len(alloc.gpu_ids),
                    "active": active,
                    "unused": len(unused_ids),
                    "priority": running.priority,
                    "unused_gpu_ids": unused_ids,
                    "allocation_end": alloc.end_time,
                }
            )
        blockers.sort(key=lambda b: (-b["unused"], b["job_id"]))
        return blockers

    def _free_window(
        self,
        ctx: AgentContext,
        gpu_ids: list[str],
        window: tuple[datetime, datetime],
        needed: int,
        holder_job_id: str | None = None,
    ) -> tuple[list[GPUInterval], datetime | None]:
        return free_window(ctx.dataset, gpu_ids, window, needed, holder_job_id)

    # ------------------------------------------------------------- validation

    def extra_validation(self, ctx: AgentContext, alternative: Alternative) -> tuple[list[str], list[str]]:
        checked = [
            "wait_window_known",
            "capacity_available_for_full_request",
            "gpu_type_match",
            "nvlink_single_node_if_required",
        ]
        violations: list[str] = []
        job = ctx.job
        action = alternative.proposed_action or {}
        window = wait_window(job) if job else None
        if job is None or window is None:
            return checked, ["Queue wait window could not be reconstructed"]

        claim_gpus = list(action.get("claim_gpu_ids") or action.get("gpu_ids") or [])
        if len(claim_gpus) < job.requested_gpus:
            violations.append(
                f"Alternative frees {len(claim_gpus)} GPU(s) for a {job.requested_gpus}-GPU request"
            )
        gpus_by_id = ctx.dataset.gpu_by_id()
        if job.requested_gpu_type:
            for gpu_id in claim_gpus:
                gpu = gpus_by_id.get(gpu_id)
                if gpu and not gpu_type_matches(job.requested_gpu_type, gpu.gpu_type.name):
                    violations.append(
                        f"GPU {gpu_id} is {gpu.gpu_type.name}, job requires {job.requested_gpu_type}"
                    )
                    break
        if job.constraints.get("nvlink") == "required":
            nodes = {gpus_by_id[g].node_id for g in claim_gpus if g in gpus_by_id}
            if len(nodes) > 1:
                violations.append("NVLink job cannot be started across multiple nodes")

        claim_end = parse_dt(action.get("claim_end"))
        if claim_end is None or claim_end <= window[0]:
            violations.append("Capacity did not stay available long enough to start the job")

        blocker_id = action.get("release_from_job_id")
        if blocker_id:
            checked.extend(["blocker_unused_confirmed", "priority_not_inverted"])
            blocker = next((b for b in self._blockers(ctx, job) if b["job_id"] == blocker_id), None)
            if blocker is None:
                violations.append(f"{blocker_id} was not holding enough unused GPUs at submit time")
            else:
                if blocker["priority"] > job.priority:
                    violations.append(
                        f"{blocker_id} ran at higher priority ({blocker['priority']} > {job.priority}); "
                        "reclaiming its GPUs would invert scheduler priority"
                    )
                if blocker["unused"] < job.requested_gpus:
                    violations.append(
                        f"{blocker_id} held only {blocker['unused']} unused GPUs, request needs "
                        f"{job.requested_gpus}"
                    )
        return checked, violations

    # ------------------------------------------------------------------ claim

    def build_claim(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> ResourceClaim:
        action = alternative.proposed_action or {}
        explicit = explicit_claim(action, "queue wait recovered on capacity that was free")
        if explicit is not None and explicit.intervals:
            return explicit
        job = ctx.job
        window = wait_window(job) if job else None
        if job is None or window is None:
            return ResourceClaim(basis="no reconstructable wait window")
        gpu_ids = list(action.get("gpu_ids") or [])[: job.requested_gpus]
        if not gpu_ids:
            return ResourceClaim(basis="alternative named no capacity to start the job on")
        intervals, effective_end = self._free_window(ctx, gpu_ids, window, job.requested_gpus)
        if effective_end is None:
            return ResourceClaim(basis="capacity was not free during the wait")
        return ResourceClaim(
            intervals=intervals,
            queue_job_ids=[job.job_id],
            queue_seconds=(effective_end - window[0]).total_seconds(),
            basis="queue wait recovered on capacity that was demonstrably free",
        )

    # ----------------------------------------------------------- presentation

    def recommended_action(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> str:
        action = alternative.proposed_action or {}
        job = ctx.job
        job_id = job.job_id if job else "unknown job"
        hours = float(action.get("queue_time_reduction_seconds") or 0.0) / 3600.0
        blocker = action.get("release_from_job_id")
        if blocker:
            return (
                f"Reclaim {action.get('gpu_count')} unused GPU(s) from {blocker} so {job_id} starts "
                f"up to {hours:.1f}h earlier. Operationally: apply an idle-GPU reaper or a shrink "
                "policy to the holding job's family, not a one-off preemption. Requires human "
                "approval; Natilah changes nothing."
            )
        nodes = ", ".join(action.get("node_ids") or []) or "idle capacity"
        return (
            f"Backfill {job_id} onto {nodes} at submit time to remove up to {hours:.1f}h of wait. "
            "Check why the scheduler skipped this capacity (partition, reservation, or backfill "
            "window) before changing policy. Requires human approval; Natilah changes nothing."
        )
