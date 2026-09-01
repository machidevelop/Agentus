"""Commitment coverage agent.

Objective: the committed-dollars meter. Not GPU-hours seen from a billing angle.

Reserved instances, savings plans, and spot policies are money already spent or
money about to be spent. This agent reads the fleet's commitment portfolio
against actual usage and finds three conditions:

    reservation underuse   committed capacity sitting idle — GPU-hours bought
                           ahead of time that nothing ran on
    spot eligibility       on-demand jobs that meet every criterion for spot
                           (low priority, short, no deadline) and would have
                           cost 70% less
    commitment expiry      reservations expiring soon with poor utilization,
                           about to auto-renew into the same mismatch

Every finding claims in dollars, not GPU-hours, because the waste is an
accounting fact: the commitment was purchased and the usage did not match.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from natilah.agents.resource_agent import (
    ResourceAgent,
    ResourceCandidate,
    ResourceObservation,
)
from natilah.models.domain import (
    ClusterDataset,
    ResourceClaim,
    ResourceQuantity,
    gpu_type_matches,
)
from natilah.models.enums import AgentObjective, Meter, OpportunityType
from natilah.models.resources import Commitment

logger = logging.getLogger(__name__)

MAX_SPOT_HOURS = 4.0
SPOT_PRIORITY_MAX = 0
SPOT_DISCOUNT = 0.70
EXPIRY_HORIZON_DAYS = 30
UNDERUSE_THRESHOLD = 0.50

DEADLINE_KEYS = frozenset(
    {"deadline", "deadline_utc", "due_by", "due_at", "sla", "start_before", "must_start_by"}
)
FALSEY = {"false", "no", "0", "off"}
TRUTHY = {"true", "yes", "1", "on"}


def _hours(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() / 3600.0)


class CommitmentCoverageAgent(ResourceAgent):
    name = "commitment_coverage_agent"
    objective = AgentObjective.COMMITMENT_COVERAGE
    primary_meter = Meter.COMMITTED_DOLLARS
    signal_types = (
        OpportunityType.RESERVATION_UNDERUSE,
        OpportunityType.SPOT_ELIGIBLE,
        OpportunityType.COMMITMENT_EXPIRY,
    )
    finding_title = "Commitment mismatch"

    # ------------------------------------------------------------------ detect

    def detect(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        return [
            *self._detect_underuse(dataset),
            *self._detect_spot_eligible(dataset),
            *self._detect_expiry(dataset),
        ]

    def _detect_underuse(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for commitment in dataset.commitments:
            if commitment.kind != "reserved":
                continue
            actual_hours = self._actual_hours(dataset, commitment)
            committed = commitment.committed_hours
            if committed <= 0:
                continue
            utilization = actual_hours / committed
            if utilization >= UNDERUSE_THRESHOLD:
                continue
            wasted_hours = committed - actual_hours
            wasted_dollars = wasted_hours * commitment.hourly_rate
            observations.append(
                ResourceObservation(
                    observation_id=f"reservation_underuse:{commitment.commitment_id}",
                    signal_type=OpportunityType.RESERVATION_UNDERUSE,
                    resource_id=commitment.commitment_id,
                    timestamp=commitment.start,
                    severity=round(min(1.0, (1.0 - utilization) * 1.5), 4),
                    description=(
                        f"Reservation {commitment.commitment_id} covers "
                        f"{commitment.quantity} x {commitment.gpu_type or 'GPU'} for "
                        f"{committed:.0f} committed-hours but only {actual_hours:.0f}h were used "
                        f"({utilization:.0%} utilization), wasting ${wasted_dollars:,.0f}."
                    ),
                    evidence={
                        "commitment_id": commitment.commitment_id,
                        "gpu_type": commitment.gpu_type,
                        "committed_hours": round(committed, 2),
                        "actual_hours": round(actual_hours, 2),
                        "utilization": round(utilization, 4),
                        "wasted_hours": round(wasted_hours, 2),
                        "wasted_dollars": round(wasted_dollars, 2),
                        "hourly_rate": commitment.hourly_rate,
                        "on_demand_rate": commitment.on_demand_rate,
                        "quantity": commitment.quantity,
                        "signal_reason": (
                            f"{utilization:.0%} utilization on a {commitment.quantity}-GPU "
                            f"reservation over {_hours(commitment.start, commitment.end):.0f}h"
                        ),
                    },
                    data_completeness=min(1.0, actual_hours / max(committed * 0.1, 1.0)),
                    signal_strength=round(min(1.0, (1.0 - utilization) / 0.5), 4),
                    recurrence=max(
                        0,
                        sum(
                            1
                            for c in dataset.commitments
                            if c.kind == "reserved"
                            and c.gpu_type == commitment.gpu_type
                            and c.commitment_id != commitment.commitment_id
                        ),
                    ),
                )
            )
        return observations

    def _detect_spot_eligible(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        for job in dataset.jobs:
            reason = self._spot_ineligible_reason(job)
            if reason is not None:
                continue
            rate = self._on_demand_rate(dataset, job)
            if rate <= 0:
                continue
            hours = _hours(job.start_time, job.end_time)
            on_demand_cost = hours * job.requested_gpus * rate
            spot_cost = on_demand_cost * (1.0 - SPOT_DISCOUNT)
            savings = on_demand_cost - spot_cost
            if savings <= 0:
                continue
            observations.append(
                ResourceObservation(
                    observation_id=f"spot_eligible:{job.job_id}",
                    signal_type=OpportunityType.SPOT_ELIGIBLE,
                    resource_id=job.job_id,
                    timestamp=job.start_time,
                    severity=round(min(1.0, SPOT_DISCOUNT * 1.3), 4),
                    description=(
                        f"Job {job.job_id} ran {job.requested_gpus} "
                        f"{job.requested_gpu_type or 'GPU'}(s) on-demand for {hours:.1f}h "
                        f"(${on_demand_cost:,.0f}) but qualifies for spot at "
                        f"${spot_cost:,.0f} — saving ${savings:,.0f}."
                    ),
                    affected_job_ids=[job.job_id],
                    evidence={
                        "job_id": job.job_id,
                        "gpu_type": job.requested_gpu_type or "",
                        "gpu_count": job.requested_gpus,
                        "hours": round(hours, 4),
                        "on_demand_rate": rate,
                        "on_demand_cost": round(on_demand_cost, 2),
                        "spot_cost": round(spot_cost, 2),
                        "savings": round(savings, 2),
                        "spot_discount": SPOT_DISCOUNT,
                        "signal_reason": (
                            f"Low-priority {hours:.1f}h job on {job.requested_gpus} GPU(s) "
                            f"eligible for {SPOT_DISCOUNT:.0%} spot discount"
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=round(min(1.0, SPOT_DISCOUNT / 0.5), 4),
                    recurrence=max(
                        0,
                        sum(
                            1
                            for j in dataset.jobs
                            if self._spot_ineligible_reason(j) is None
                            and j.job_id != job.job_id
                        ),
                    ),
                )
            )
        return observations

    def _detect_expiry(self, dataset: ClusterDataset) -> list[ResourceObservation]:
        observations: list[ResourceObservation] = []
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=EXPIRY_HORIZON_DAYS)
        for commitment in dataset.commitments:
            if commitment.end > horizon or commitment.end < now:
                continue
            actual_hours = self._actual_hours(dataset, commitment)
            committed = commitment.committed_hours
            utilization = actual_hours / committed if committed > 0 else 0.0
            days_left = max(0.0, (commitment.end - now).total_seconds() / 86400.0)
            remaining_dollars = days_left * 24.0 * commitment.quantity * commitment.hourly_rate
            observations.append(
                ResourceObservation(
                    observation_id=f"commitment_expiry:{commitment.commitment_id}",
                    signal_type=OpportunityType.COMMITMENT_EXPIRY,
                    resource_id=commitment.commitment_id,
                    timestamp=commitment.end,
                    severity=round(min(1.0, (1.0 - utilization) + (1.0 - days_left / EXPIRY_HORIZON_DAYS)), 4),
                    description=(
                        f"Commitment {commitment.commitment_id} ({commitment.kind}, "
                        f"{commitment.quantity} x {commitment.gpu_type or 'GPU'}) expires in "
                        f"{days_left:.0f} days with {utilization:.0%} utilization"
                        f"{', auto-renew ON' if commitment.auto_renew else ''}. "
                        f"${remaining_dollars:,.0f} in remaining commitment."
                    ),
                    evidence={
                        "commitment_id": commitment.commitment_id,
                        "kind": commitment.kind,
                        "gpu_type": commitment.gpu_type,
                        "quantity": commitment.quantity,
                        "days_left": round(days_left, 1),
                        "utilization": round(utilization, 4),
                        "auto_renew": commitment.auto_renew,
                        "hourly_rate": commitment.hourly_rate,
                        "on_demand_rate": commitment.on_demand_rate,
                        "remaining_dollars": round(remaining_dollars, 2),
                        "committed_hours": round(committed, 2),
                        "actual_hours": round(actual_hours, 2),
                        "signal_reason": (
                            f"Expiring in {days_left:.0f} days at {utilization:.0%} utilization"
                            f"{' with auto-renew' if commitment.auto_renew else ''}"
                        ),
                    },
                    data_completeness=min(1.0, actual_hours / max(committed * 0.1, 1.0)),
                    signal_strength=round(
                        min(1.0, (1.0 - utilization) * 0.6 + (1.0 - days_left / EXPIRY_HORIZON_DAYS) * 0.4),
                        4,
                    ),
                    recurrence=max(
                        0,
                        sum(
                            1
                            for c in dataset.commitments
                            if c.commitment_id != commitment.commitment_id
                            and now <= c.end <= horizon
                        ),
                    ),
                )
            )
        return observations

    # -------------------------------------------------------------- candidates

    def generate_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        if observation.signal_type is OpportunityType.RESERVATION_UNDERUSE:
            return self._underuse_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.SPOT_ELIGIBLE:
            return self._spot_candidates(dataset, observation)
        if observation.signal_type is OpportunityType.COMMITMENT_EXPIRY:
            return self._expiry_candidates(dataset, observation)
        return []

    def _underuse_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        wasted = float(ev.get("wasted_dollars") or 0.0)
        committed_hours = float(ev.get("committed_hours") or 0.0)
        actual_hours = float(ev.get("actual_hours") or 0.0)
        quantity = int(ev.get("quantity") or 0)
        utilization = float(ev.get("utilization") or 0.0)
        if wasted <= 0:
            return []

        candidates: list[ResourceCandidate] = []

        right_size = max(1, int(quantity * utilization * 1.2))
        if right_size < quantity:
            savings = (quantity - right_size) / quantity * wasted
            candidates.append(
                ResourceCandidate(
                    kind="downsize_reservation",
                    description=(
                        f"Downsize reservation from {quantity} to {right_size} "
                        f"{ev.get('gpu_type', 'GPU')}(s) to match actual usage."
                    ),
                    proposed_action={
                        "kind": "downsize_reservation",
                        "commitment_id": observation.resource_id,
                        "current_quantity": quantity,
                        "proposed_quantity": right_size,
                        "gpu_type": ev.get("gpu_type"),
                    },
                    rationale=(
                        f"Actual usage is {utilization:.0%} of committed capacity; a right-sized "
                        f"reservation of {right_size} covers the workload with 20% headroom."
                    ),
                    source="detector:underuse:downsize",
                    claim=self._dollars_claim(
                        observation.resource_id, savings,
                        f"Savings from reducing {quantity} to {right_size} GPUs in reservation.",
                    ),
                )
            )

        on_demand_rate = float(ev.get("on_demand_rate") or 0.0)
        hourly_rate = float(ev.get("hourly_rate") or 0.0)
        if on_demand_rate > 0 and actual_hours > 0:
            on_demand_cost = actual_hours * on_demand_rate
            reserved_cost = committed_hours * hourly_rate
            if on_demand_cost < reserved_cost:
                candidates.append(
                    ResourceCandidate(
                        kind="switch_to_on_demand",
                        description=(
                            f"Let reservation expire and switch to on-demand: actual usage costs "
                            f"${on_demand_cost:,.0f} vs ${reserved_cost:,.0f} reserved."
                        ),
                        proposed_action={
                            "kind": "switch_to_on_demand",
                            "commitment_id": observation.resource_id,
                            "on_demand_cost": round(on_demand_cost, 2),
                            "reserved_cost": round(reserved_cost, 2),
                        },
                        rationale=(
                            "At current utilization, on-demand is cheaper than maintaining the "
                            "reservation — the commitment discount does not overcome the idle cost."
                        ),
                        source="detector:underuse:on_demand",
                        claim=self._dollars_claim(
                            observation.resource_id, reserved_cost - on_demand_cost,
                            f"Delta between reserved (${reserved_cost:,.0f}) and on-demand "
                            f"(${on_demand_cost:,.0f}) at current utilization.",
                        ),
                    )
                )

        peers = [
            c for c in dataset.commitments
            if c.commitment_id != observation.resource_id
            and c.kind == "reserved"
            and c.gpu_type == ev.get("gpu_type")
        ]
        if peers:
            peer = peers[0]
            peer_util = self._actual_hours(dataset, peer) / max(peer.committed_hours, 1.0)
            if peer_util < UNDERUSE_THRESHOLD:
                combined_quantity = quantity + peer.quantity
                combined_actual = actual_hours + self._actual_hours(dataset, peer)
                combined_committed = committed_hours + peer.committed_hours
                combined_wasted = (combined_committed - combined_actual) * hourly_rate
                solo_wasted = wasted + (peer.committed_hours - self._actual_hours(dataset, peer)) * peer.hourly_rate
                if combined_wasted < solo_wasted:
                    candidates.append(
                        ResourceCandidate(
                            kind="consolidate_reservations",
                            description=(
                                f"Consolidate with reservation {peer.commitment_id} into one "
                                f"right-sized {ev.get('gpu_type', 'GPU')} reservation."
                            ),
                            proposed_action={
                                "kind": "consolidate_reservations",
                                "commitment_id": observation.resource_id,
                                "peer_commitment_id": peer.commitment_id,
                                "combined_quantity": combined_quantity,
                            },
                            rationale=(
                                "Two underused reservations of the same GPU type waste more "
                                "separately than one right-sized reservation would."
                            ),
                            source="detector:underuse:consolidate",
                            claim=self._dollars_claim(
                                observation.resource_id, solo_wasted - combined_wasted,
                                "Savings from consolidating two underused reservations.",
                            ),
                        )
                    )
        return candidates

    def _spot_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        savings = float(ev.get("savings") or 0.0)
        on_demand_cost = float(ev.get("on_demand_cost") or 0.0)
        spot_cost = float(ev.get("spot_cost") or 0.0)
        if savings <= 0:
            return []

        candidates: list[ResourceCandidate] = []
        candidates.append(
            ResourceCandidate(
                kind="switch_to_spot",
                description=(
                    f"Run job {observation.resource_id} on spot instances at "
                    f"${spot_cost:,.0f} instead of ${on_demand_cost:,.0f} on-demand."
                ),
                proposed_action={
                    "kind": "switch_to_spot",
                    "job_id": observation.resource_id,
                    "on_demand_cost": round(on_demand_cost, 2),
                    "spot_cost": round(spot_cost, 2),
                    "spot_discount": SPOT_DISCOUNT,
                },
                rationale=(
                    "Job is low-priority, short, has no deadline, and is not interactive — "
                    "it meets every criterion for spot with a preemption-tolerant workload."
                ),
                source="detector:spot:full_switch",
                claim=self._dollars_claim(
                    observation.resource_id, savings,
                    f"On-demand ${on_demand_cost:,.0f} minus spot ${spot_cost:,.0f}.",
                ),
            )
        )

        fallback_savings = savings * 0.8
        candidates.append(
            ResourceCandidate(
                kind="spot_with_fallback",
                description=(
                    f"Run job {observation.resource_id} on spot with on-demand fallback — "
                    f"captures ~80% of the ${savings:,.0f} saving with automatic recovery."
                ),
                proposed_action={
                    "kind": "spot_with_fallback",
                    "job_id": observation.resource_id,
                    "on_demand_cost": round(on_demand_cost, 2),
                    "expected_savings": round(fallback_savings, 2),
                    "spot_discount": SPOT_DISCOUNT,
                },
                rationale=(
                    "Spot with on-demand fallback captures most of the saving while protecting "
                    "against preemption — the 20% haircut assumes a fraction of runs fall back."
                ),
                source="detector:spot:with_fallback",
                claim=self._dollars_claim(
                    observation.resource_id, fallback_savings,
                    "80% of full spot savings, assuming occasional on-demand fallback.",
                ),
            )
        )
        return candidates

    def _expiry_candidates(
        self, dataset: ClusterDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        ev = observation.evidence
        remaining = float(ev.get("remaining_dollars") or 0.0)
        utilization = float(ev.get("utilization") or 0.0)
        auto_renew = bool(ev.get("auto_renew"))
        quantity = int(ev.get("quantity") or 0)
        if remaining <= 0:
            return []

        candidates: list[ResourceCandidate] = []

        if auto_renew or utilization < UNDERUSE_THRESHOLD:
            wasted_on_renewal = remaining * (1.0 - utilization)
            candidates.append(
                ResourceCandidate(
                    kind="dont_renew",
                    description=(
                        f"Do not renew commitment {observation.resource_id} — at "
                        f"{utilization:.0%} utilization, renewal wastes "
                        f"${wasted_on_renewal:,.0f}/term."
                    ),
                    proposed_action={
                        "kind": "dont_renew",
                        "commitment_id": observation.resource_id,
                        "auto_renew": auto_renew,
                        "utilization": utilization,
                    },
                    rationale=(
                        "Current utilization does not justify the commitment at any term length. "
                        "On-demand or spot covers the actual workload more cheaply."
                    ),
                    source="detector:expiry:dont_renew",
                    claim=self._dollars_claim(
                        observation.resource_id, wasted_on_renewal,
                        f"Projected waste on next term at {utilization:.0%} utilization.",
                    ),
                )
            )

        if quantity > 1 and utilization > 0:
            right_size = max(1, int(quantity * utilization * 1.2))
            if right_size < quantity:
                rate = float(ev.get("hourly_rate") or 0.0)
                days_left = float(ev.get("days_left") or 0.0)
                saved_gpus = quantity - right_size
                savings = saved_gpus * days_left * 24.0 * rate
                candidates.append(
                    ResourceCandidate(
                        kind="right_size_before_renewal",
                        description=(
                            f"Renew at {right_size} instead of {quantity} "
                            f"{ev.get('gpu_type', 'GPU')}(s) to match actual usage."
                        ),
                        proposed_action={
                            "kind": "right_size_before_renewal",
                            "commitment_id": observation.resource_id,
                            "current_quantity": quantity,
                            "proposed_quantity": right_size,
                        },
                        rationale=(
                            "A smaller renewal still captures the reservation discount on the "
                            "GPUs that are actually used, without paying for the idle ones."
                        ),
                        source="detector:expiry:right_size",
                        claim=self._dollars_claim(
                            observation.resource_id, savings,
                            f"Savings from renewing {right_size} instead of {quantity} GPUs.",
                        ),
                    )
                )
        return candidates

    # -------------------------------------------------------------- validation

    def validate_candidate(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> tuple[list[str], list[str]]:
        action = candidate.proposed_action or {}
        checked = ["commitment_or_job_exists", "claimed_amount_positive"]
        violations: list[str] = []

        if observation.signal_type in (
            OpportunityType.RESERVATION_UNDERUSE,
            OpportunityType.COMMITMENT_EXPIRY,
        ):
            cid = str(action.get("commitment_id") or observation.resource_id)
            found = any(c.commitment_id == cid for c in dataset.commitments)
            if not found:
                violations.append(f"Commitment {cid} not found in dataset")

            if action.get("kind") == "consolidate_reservations":
                checked.append("peer_commitment_exists")
                peer_id = str(action.get("peer_commitment_id") or "")
                if not any(c.commitment_id == peer_id for c in dataset.commitments):
                    violations.append(f"Peer commitment {peer_id} not found in dataset")

        elif observation.signal_type is OpportunityType.SPOT_ELIGIBLE:
            checked.append("job_is_spot_eligible")
            job_id = str(action.get("job_id") or observation.resource_id)
            job = dataset.job_by_id().get(job_id)
            if job is None:
                violations.append(f"Job {job_id} not found in dataset")
            else:
                reason = self._spot_ineligible_reason(job)
                if reason:
                    violations.append(f"Job {job_id} is not spot-eligible: {reason}")

        claimed = candidate.claim.primary_quantity
        if claimed <= 0:
            violations.append("Candidate claims no measurable dollar amount")

        return checked, violations

    # ------------------------------------------------------------ presentation

    def recommended_action(
        self,
        dataset: ClusterDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        dollars = candidate.claim.primary_quantity
        analysis_hours = self.analysis_hours(dataset)
        per_month = self.economic_config.working_hours_per_month
        monthly = (dollars / analysis_hours) * per_month if analysis_hours > 0 else 0.0
        action = candidate.proposed_action or {}

        if observation.signal_type is OpportunityType.RESERVATION_UNDERUSE:
            if action.get("kind") == "downsize_reservation":
                head = (
                    f"Right-size reservation {observation.resource_id} from "
                    f"{action.get('current_quantity')} to {action.get('proposed_quantity')} "
                    f"GPU(s) — worth ${monthly:,.0f}/month"
                )
            elif action.get("kind") == "switch_to_on_demand":
                head = (
                    f"Let reservation {observation.resource_id} expire and switch to on-demand "
                    f"— at current utilization, on-demand is ${monthly:,.0f}/month cheaper"
                )
            else:
                head = (
                    f"Consolidate reservation {observation.resource_id} with "
                    f"{action.get('peer_commitment_id')} — worth ${monthly:,.0f}/month"
                )
        elif observation.signal_type is OpportunityType.SPOT_ELIGIBLE:
            head = (
                f"Switch job {observation.resource_id} to spot instances "
                f"— worth ${monthly:,.0f}/month across similar jobs"
            )
        else:
            if action.get("kind") == "dont_renew":
                head = (
                    f"Disable auto-renew on commitment {observation.resource_id} "
                    f"— renewal at current utilization wastes ${monthly:,.0f}/month"
                )
            else:
                head = (
                    f"Renew commitment {observation.resource_id} at "
                    f"{action.get('proposed_quantity')} instead of "
                    f"{action.get('current_quantity')} GPU(s) — saves ${monthly:,.0f}/month"
                )

        return (
            f"{head}. Review with finance and capacity planning. Requires human "
            "approval; Natilah changes nothing."
        )

    # ----------------------------------------------------------------- helpers

    def _actual_hours(self, dataset: ClusterDataset, commitment: Commitment) -> float:
        """GPU-hours of the committed type actually used during the commitment window."""
        total = 0.0
        for allocation in dataset.allocations:
            if allocation.start_time >= commitment.end:
                continue
            alloc_end = allocation.end_time or commitment.end
            if alloc_end <= commitment.start:
                continue
            matching_gpus = sum(
                1 for gid in allocation.gpu_ids
                if self._gpu_matches_type(dataset, gid, commitment.gpu_type)
            )
            if matching_gpus == 0:
                continue
            overlap_start = max(allocation.start_time, commitment.start)
            overlap_end = min(alloc_end, commitment.end)
            total += matching_gpus * _hours(overlap_start, overlap_end)
        return total

    def _gpu_matches_type(self, dataset: ClusterDataset, gpu_id: str, target_type: str) -> bool:
        if not target_type:
            return True
        gpu = dataset.gpu_by_id().get(gpu_id)
        if gpu is None:
            return False
        return gpu_type_matches(target_type, gpu.gpu_type.name)

    def _on_demand_rate(self, dataset: ClusterDataset, job) -> float:
        """On-demand rate for a job's GPU type from commitment data or economic config."""
        gpu_type = job.requested_gpu_type or ""
        for commitment in dataset.commitments:
            if commitment.on_demand_rate > 0 and gpu_type_matches(gpu_type, commitment.gpu_type):
                return commitment.on_demand_rate
        return self.gpu_rate(gpu_type)

    def _spot_ineligible_reason(self, job) -> str | None:
        if job.start_time is None or job.end_time is None:
            return "run window is unknown"
        hours = _hours(job.start_time, job.end_time)
        if hours <= 0:
            return "run window is empty"
        if hours > MAX_SPOT_HOURS:
            return f"ran {hours:.1f}h, beyond the {MAX_SPOT_HOURS:.0f}h spot ceiling"
        if job.priority > SPOT_PRIORITY_MAX:
            return f"priority {job.priority} is above the spot ceiling"
        constraints = {str(k).lower(): str(v).lower() for k, v in (job.constraints or {}).items()}
        for key in DEADLINE_KEYS:
            if key in constraints:
                return f"carries a {key} constraint"
        if constraints.get("spot") in FALSEY:
            return "explicitly marked non-spot-eligible"
        if constraints.get("interactive") in TRUTHY:
            return "is an interactive session"
        return None

    def _dollars_claim(
        self, resource_id: str, amount: float, basis: str
    ) -> ResourceClaim:
        return ResourceClaim(
            quantities=[
                ResourceQuantity(
                    meter=Meter.COMMITTED_DOLLARS,
                    resource_id=resource_id,
                    amount=max(0.0, amount),
                )
            ],
            basis=basis,
            primary_meter=Meter.COMMITTED_DOLLARS,
        )
