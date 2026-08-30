"""Fragmentation and placement agent.

Objective: capacity that existed but could not be used because of where it
sat. Two signals feed one objective — a job spread across nodes when one node
would have held it, and stranded free GPUs while a large job waited.

This agent is deliberately the strictest of the four. Moving a job around does
not by itself recover GPU-hours: the same GPUs are still busy, just arranged
differently. Value is claimed only when a real pending job could have used the
capacity the rearrangement frees, and only for as long as that capacity stayed
free. Candidates that cannot show such a consumer are rejected.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from natilah.agents.base_agent import CandidateProposal, SpecializedAgent
from natilah.agents.claims import attach_claim, explicit_claim, free_window
from natilah.agents.toolbox import AgentContext
from natilah.engine.opportunity_detector import (
    FragmentationDetector,
    PlacementDetector,
    SignalDetector,
)
from natilah.models.domain import (
    Alternative,
    ComparisonResult,
    Job,
    ResourceClaim,
    gpu_type_matches,
)
from natilah.models.enums import AgentObjective, OpportunityType

MIN_RECOVERABLE_SECONDS = 300.0


class FragmentationPlacementAgent(SpecializedAgent):
    name = "fragmentation_placement_agent"
    objective = AgentObjective.FRAGMENTATION_PLACEMENT
    signal_types = (OpportunityType.FRAGMENTATION, OpportunityType.POOR_PLACEMENT)
    finding_title = "Fragmented capacity and placement"

    def build_detectors(self) -> list[SignalDetector]:
        return [PlacementDetector(), FragmentationDetector()]

    def state_timestamp(self, observation) -> datetime:
        if observation.signal_type == OpportunityType.POOR_PLACEMENT:
            # Reconstruct just before the allocation so the job is not yet on the nodes.
            return observation.timestamp - timedelta(seconds=1)
        return observation.timestamp

    def investigation_plan(self, ctx: AgentContext) -> list[tuple[str, dict]]:
        needed = ctx.job.requested_gpus if ctx.job else 8
        return [
            ("inspect_job_constraints", {}),
            ("inspect_topology", {}),
            ("inspect_queue", {"limit": 20}),
            ("list_idle_capacity", {"min_gpus": 1}),
            ("probe_single_node_fit", {"gpu_count": needed}),
            ("probe_consolidation_move", {"needed_gpus": needed}),
            ("inspect_history", {}),
        ]

    def claim_cap_gpu_hours(self, ctx: AgentContext) -> float:
        if ctx.observation.signal_type == OpportunityType.FRAGMENTATION:
            window = self._pending_wait_window(ctx, ctx.job)
            if window is None or ctx.job is None:
                return float("inf")
            hours = (window[1] - window[0]).total_seconds() / 3600.0
            return hours * max(ctx.job.requested_gpus, 1)
        return super().claim_cap_gpu_hours(ctx)

    # ------------------------------------------------------------- candidates

    def generate_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        if ctx.observation.signal_type == OpportunityType.POOR_PLACEMENT:
            return self._placement_candidates(ctx, evidence)
        return self._fragmentation_candidates(ctx, evidence)

    # --- poor placement -----------------------------------------------------

    def _placement_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        job, alloc = ctx.job, ctx.allocation
        if job is None or alloc is None or len(alloc.node_ids) < 2:
            return []
        needed = len(alloc.gpu_ids)
        window = ctx.hold_window()
        if window is None:
            return []

        options = (evidence.get("tools") or {}).get("probe_alternate_placement") or {}
        node_options = [
            opt.get("node_ids", [None])[0]
            for opt in options.get("options", [])
            if opt.get("node_ids")
        ]
        if not node_options:
            caps = ctx.state.available_capacity.by_node
            node_options = [
                cap.node_id
                for cap in sorted(caps.values(), key=lambda c: c.idle_gpus)
                if cap.idle_gpus >= needed
                and gpu_type_matches(job.requested_gpu_type, cap.gpu_type)
            ][:2]

        proposals: list[CandidateProposal] = []
        for node_id in dict.fromkeys(node_options):
            cap = ctx.state.available_capacity.by_node.get(node_id)
            if cap is None or cap.idle_gpus < needed:
                continue
            consumer = self._fragment_consumer(ctx, alloc.gpu_ids, window)
            if consumer is None:
                continue
            pending, gpu_ids, effective_end = consumer
            action = {
                "kind": "place",
                "gpu_count": needed,
                "gpu_ids": cap.idle_gpu_ids[:needed],
                "node_ids": [node_id],
                "require_single_node": True,
                "original_node_ids": list(alloc.node_ids),
                "frees_gpu_ids": list(alloc.gpu_ids),
                "unblocked_job_ids": [pending.job_id],
                "queue_time_reduction_seconds": (effective_end - window[0]).total_seconds(),
            }
            attach_claim(
                action,
                gpu_ids,
                (window[0], effective_end),
                "fragments returned to the free pool and consumed by a waiting job",
                queue_job_ids=[pending.job_id],
                queue_seconds=(effective_end - window[0]).total_seconds(),
            )
            proposals.append(
                CandidateProposal(
                    kind="place",
                    description=(
                        f"Place {job.job_id} entirely on {node_id} instead of spreading it across "
                        f"{', '.join(alloc.node_ids)}, leaving a usable block for {pending.job_id}."
                    ),
                    proposed_action=action,
                    rationale=(
                        f"{node_id} had {cap.idle_gpus} idle {cap.gpu_type} GPUs at decision time, "
                        f"and pending job {pending.job_id} ({pending.requested_gpus} GPUs) could "
                        "have used the fragments the split placement stranded."
                    ),
                    source="tool:probe_alternate_placement",
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )
        return proposals

    def _fragment_consumer(
        self,
        ctx: AgentContext,
        freed_gpu_ids: list[str],
        window: tuple[datetime, datetime],
    ):
        """The waiting job that could actually have used the freed fragments."""
        gpus_by_id = ctx.dataset.gpu_by_id()
        by_node: dict[str, list[str]] = {}
        for gpu_id in freed_gpu_ids:
            gpu = gpus_by_id.get(gpu_id)
            if gpu:
                by_node.setdefault(gpu.node_id, []).append(gpu_id)

        best = None
        for pending in ctx.state.pending_jobs[:40]:
            if pending.start_time is None or pending.start_time <= window[0]:
                continue
            for node_id, gpu_ids in by_node.items():
                cap = ctx.state.available_capacity.by_node.get(node_id)
                pool = list(gpu_ids) + (cap.idle_gpu_ids if cap else [])
                if pending.requested_gpu_type:
                    pool = [
                        g
                        for g in pool
                        if g in gpus_by_id and gpus_by_id[g].gpu_type.name == pending.requested_gpu_type
                    ]
                if len(pool) < pending.requested_gpus:
                    continue
                wait_end = min(window[1], pending.start_time)
                intervals, effective_end = free_window(
                    ctx.dataset,
                    pool[: pending.requested_gpus],
                    (window[0], wait_end),
                    pending.requested_gpus,
                    holder_job_id=ctx.job.job_id if ctx.job else None,
                )
                if effective_end is None:
                    continue
                seconds = (effective_end - window[0]).total_seconds()
                if seconds < MIN_RECOVERABLE_SECONDS:
                    continue
                value = seconds * pending.requested_gpus
                if best is None or value > best[0]:
                    best = (value, pending, [i.gpu_id for i in intervals], effective_end)
        if best is None:
            return None
        return best[1], best[2], best[3]

    # --- fragmentation ------------------------------------------------------

    def _fragmentation_candidates(self, ctx: AgentContext, evidence: dict) -> list[CandidateProposal]:
        pending = ctx.job
        if pending is None:
            return []
        window = self._pending_wait_window(ctx, pending)
        if window is None:
            return []
        needed = pending.requested_gpus
        nvlink = pending.constraints.get("nvlink") == "required"
        proposals: list[CandidateProposal] = []

        moves = ((evidence.get("tools") or {}).get("probe_consolidation_move") or {}).get("moves") or []
        for move in moves[:2]:
            cap = ctx.state.available_capacity.by_node.get(move["from_node"])
            if cap is None:
                continue
            pool = list(cap.idle_gpu_ids) + list(move.get("source_gpu_ids") or [])
            if len(pool) < needed:
                continue
            intervals, effective_end = free_window(
                ctx.dataset, pool[:needed], window, needed, holder_job_id=move["move_job_id"]
            )
            if effective_end is None:
                continue
            seconds = (effective_end - window[0]).total_seconds()
            if seconds < MIN_RECOVERABLE_SECONDS:
                continue
            action = {
                "kind": "consolidate",
                "gpu_count": needed,
                "node_ids": [move["from_node"]],
                "require_single_node": True,
                "move_job_id": move["move_job_id"],
                "move_to_node": move["to_node"],
                "block_created": move["block_created"],
                "start_job_id": pending.job_id,
                "unblocked_job_ids": [pending.job_id],
                "queue_time_reduction_seconds": seconds,
            }
            attach_claim(
                action,
                [i.gpu_id for i in intervals],
                (window[0], effective_end),
                "contiguous block rebuilt by relocating one small job",
                queue_job_ids=[pending.job_id],
                queue_seconds=seconds,
            )
            proposals.append(
                CandidateProposal(
                    kind="consolidate",
                    description=(
                        f"Relocate {move['move_job_id']} from {move['from_node']} to "
                        f"{move['to_node']} to rebuild a {move['block_created']}-GPU block and start "
                        f"{pending.job_id} instead of leaving it queued."
                    ),
                    proposed_action=action,
                    rationale=(
                        f"{move['from_node']} held {cap.idle_gpus} stranded idle GPUs; moving a "
                        f"{move['gpus_moved']}-GPU job off it produces a block large enough for "
                        f"{pending.job_id}."
                    ),
                    source="tool:probe_consolidation_move",
                    tools_invoked=list(ctx.tools_invoked or []),
                )
            )

        if not nvlink:
            spread = self._spread_placement(ctx, pending, window, needed)
            if spread is not None:
                proposals.append(spread)
        return proposals

    def _spread_placement(self, ctx: AgentContext, pending: Job, window, needed: int):
        gathered: list[str] = []
        nodes: list[str] = []
        for cap in sorted(
            ctx.state.available_capacity.by_node.values(), key=lambda c: c.idle_gpus, reverse=True
        ):
            if not gpu_type_matches(pending.requested_gpu_type, cap.gpu_type):
                continue
            take = cap.idle_gpu_ids[: max(0, needed - len(gathered))]
            if not take:
                continue
            gathered.extend(take)
            nodes.append(cap.node_id)
            if len(gathered) >= needed:
                break
        if len(gathered) < needed:
            return None
        intervals, effective_end = free_window(ctx.dataset, gathered[:needed], window, needed)
        if effective_end is None:
            return None
        seconds = (effective_end - window[0]).total_seconds()
        if seconds < MIN_RECOVERABLE_SECONDS:
            return None
        action = {
            "kind": "place",
            "gpu_count": needed,
            "gpu_ids": gathered[:needed],
            "node_ids": sorted(set(nodes)),
            "start_job_id": pending.job_id,
            "unblocked_job_ids": [pending.job_id],
            "queue_time_reduction_seconds": seconds,
        }
        attach_claim(
            action,
            gathered[:needed],
            (window[0], effective_end),
            "stranded fragments gathered across nodes for a job with no locality constraint",
            queue_job_ids=[pending.job_id],
            queue_seconds=seconds,
        )
        return CandidateProposal(
            kind="place",
            description=(
                f"Run {pending.job_id} across the stranded fragments on {', '.join(sorted(set(nodes)))} "
                f"rather than waiting for one contiguous {needed}-GPU block."
            ),
            proposed_action=action,
            rationale=(
                f"{pending.job_id} declares no NVLink or single-node constraint, and "
                f"{len(gathered)} matching GPUs were idle across {len(set(nodes))} node(s)."
            ),
            source="tool:list_idle_capacity:spread",
            tools_invoked=list(ctx.tools_invoked or []),
        )

    def _pending_wait_window(self, ctx: AgentContext, pending: Job | None):
        if pending is None or pending.start_time is None:
            return None
        start = ctx.observation.timestamp
        if pending.start_time <= start:
            return None
        return start, pending.start_time

    # ------------------------------------------------------------- validation

    def extra_validation(self, ctx: AgentContext, alternative: Alternative) -> tuple[list[str], list[str]]:
        checked = ["consumer_job_still_waiting", "capacity_stayed_free", "gpu_type_match"]
        violations: list[str] = []
        action = alternative.proposed_action or {}
        jobs = ctx.dataset.job_by_id()
        gpus_by_id = ctx.dataset.gpu_by_id()

        consumers = list(action.get("unblocked_job_ids") or action.get("claim_queue_job_ids") or [])
        if not consumers:
            violations.append("Alternative names no waiting job that would use the freed capacity")
        for job_id in consumers:
            consumer = jobs.get(job_id)
            if consumer is None:
                violations.append(f"Unknown consumer job {job_id}")
                continue
            if consumer.start_time is not None and consumer.start_time <= ctx.observation.timestamp:
                violations.append(f"{job_id} had already started; it could not consume this capacity")

        claim_gpus = list(action.get("claim_gpu_ids") or [])
        if not claim_gpus:
            violations.append("Alternative claims no specific GPUs")
        for job_id in consumers[:1]:
            consumer = jobs.get(job_id)
            if consumer is None:
                continue
            if len(claim_gpus) < consumer.requested_gpus:
                violations.append(
                    f"{len(claim_gpus)} GPU(s) claimed for {job_id}, which needs "
                    f"{consumer.requested_gpus}"
                )
            if consumer.requested_gpu_type:
                mismatched = [
                    g
                    for g in claim_gpus
                    if g in gpus_by_id
                    and not gpu_type_matches(consumer.requested_gpu_type, gpus_by_id[g].gpu_type.name)
                ]
                if mismatched:
                    violations.append(
                        f"GPU {mismatched[0]} does not match {job_id}'s requested type "
                        f"{consumer.requested_gpu_type}"
                    )
            if consumer.constraints.get("nvlink") == "required":
                nodes = {gpus_by_id[g].node_id for g in claim_gpus if g in gpus_by_id}
                if len(nodes) > 1:
                    violations.append(f"{job_id} requires NVLink and cannot span {len(nodes)} nodes")

        move_job_id = action.get("move_job_id")
        if move_job_id:
            checked.append("relocated_job_fits_target")
            alloc = ctx.dataset.allocation_by_job().get(move_job_id)
            target = ctx.state.available_capacity.by_node.get(str(action.get("move_to_node")))
            if alloc is None:
                violations.append(f"Unknown relocation source job {move_job_id}")
            elif target is None:
                violations.append("Relocation target node not found in reconstructed state")
            elif target.idle_gpus < len(alloc.gpu_ids):
                violations.append(
                    f"Target node {target.node_id} had {target.idle_gpus} idle GPUs, relocation "
                    f"needs {len(alloc.gpu_ids)}"
                )
            elif alloc.gpu_ids and not gpu_type_matches(
                gpus_by_id[alloc.gpu_ids[0]].gpu_type.name, target.gpu_type
            ):
                violations.append("Relocation target node has a different GPU type")
        return checked, violations

    # ------------------------------------------------------------------ claim

    def build_claim(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> ResourceClaim:
        action = alternative.proposed_action or {}
        explicit = explicit_claim(action, "capacity unlocked for a waiting job")
        if explicit is not None and explicit.intervals:
            return explicit
        return ResourceClaim(
            basis="no waiting job could be shown to consume the freed capacity"
        )

    # ----------------------------------------------------------- presentation

    def recommended_action(
        self,
        ctx: AgentContext,
        alternative: Alternative,
        comparison: ComparisonResult,
    ) -> str:
        action = alternative.proposed_action or {}
        consumers = ", ".join(action.get("unblocked_job_ids") or []) or "the waiting job"
        hours = float(action.get("queue_time_reduction_seconds") or 0.0) / 3600.0
        if action.get("move_job_id"):
            return (
                f"Rebuild a {action.get('block_created')}-GPU block on {', '.join(action.get('node_ids') or [])} "
                f"by relocating {action.get('move_job_id')} to {action.get('move_to_node')}, so "
                f"{consumers} starts up to {hours:.1f}h earlier. Treat it as a defragmentation "
                "policy question, not a one-off move. Requires human approval; Natilah changes nothing."
            )
        if ctx.observation.signal_type == OpportunityType.POOR_PLACEMENT:
            job_id = ctx.job.job_id if ctx.job else "the job"
            return (
                f"Pack {job_id} onto {', '.join(action.get('node_ids') or [])} instead of spreading it; "
                f"the fragments it stranded would have served {consumers} up to {hours:.1f}h earlier. "
                "Check the scheduler's node-selection weights. Requires human approval; Natilah "
                "changes nothing."
            )
        return (
            f"Allow {consumers} to run across stranded fragments on "
            f"{', '.join(action.get('node_ids') or [])} (no locality constraint declared), removing up "
            f"to {hours:.1f}h of wait. Requires human approval; Natilah changes nothing."
        )
