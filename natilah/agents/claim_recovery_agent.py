"""Health claim recovery agent.

Objective: the claim-dollars meter. A payer adjudicated a line and told the
member what they owe. This agent decides whether that number follows from the
payer's own published rules, and where it does not, what the member is owed
back and which filing path recovers it.

The arbitrage this exists for: roughly a fifth of in-network marketplace claims
are denied, under one percent are appealed, and something close to half of the
appeals that do get filed are overturned. The gap is not information. Members
know they were denied. It is the labour of assembling the appeal.

Six conditions, six shapes of a wrong number:

    denied              the payer paid nothing on a code its own policy covers
    underpaid           the plan paid less than the member's cost share implies
    duplicate charge    the same code, same provider, same day, billed twice
    improper bundling   two codes billed separately that the edit table bundles,
                        with no modifier to justify the split
    balance bill        an in-network provider charged above the allowed amount,
                        which the contract does not permit
    deductible misapplied  money applied to a deductible that was already met

The division of labour is the same one the infrastructure agents use. Rules
decide feasibility: is the filing window open, does the policy cover the code,
does the arithmetic hold. Nothing here is a coverage determination or medical
advice, and nothing is filed. The agent proposes; a human approves.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from natilah.agents.resource_agent import (
    ResourceAgent,
    ResourceCandidate,
    ResourceObservation,
)
from natilah.models.consumer import ClaimLine, HouseholdDataset, MemberPlan, PayerPolicy
from natilah.models.domain import ResourceClaim, ResourceQuantity
from natilah.models.enums import AgentObjective, Meter, OpportunityType

# A recovery below this is not worth a member's signature.
MIN_RECOVERABLE_DOLLARS = 5.0

# Underpayment tolerance. Adjudication rounds; a few dollars is not a finding.
UNDERPAYMENT_TOLERANCE = 2.0

# Appeals filed this close to the deadline are unlikely to land in time.
FILING_BUFFER_DAYS = 7


def _dollars(claim_id: str, amount: float) -> ResourceClaim:
    """A claim in dollars, scoped to the line it recovers from.

    The resource id is the claim line, which is what lets the coordination
    layer credit one disputed dollar once even when two conditions fire on
    the same line.
    """
    return ResourceClaim(
        primary_meter=Meter.CLAIM_DOLLARS,
        quantities=[
            ResourceQuantity(meter=Meter.CLAIM_DOLLARS, resource_id=claim_id, amount=amount)
        ],
        basis=f"Disputed patient responsibility on claim line {claim_id}",
    )


class ClaimRecoveryAgent(ResourceAgent):
    """One agent, one meter: dollars wrongly charged to a member."""

    name = "claim_recovery_agent"
    objective = AgentObjective.CLAIM_RECOVERY
    primary_meter = Meter.CLAIM_DOLLARS
    signal_types = (
        OpportunityType.CLAIM_DENIED,
        OpportunityType.CLAIM_UNDERPAID,
        OpportunityType.DUPLICATE_CHARGE,
        OpportunityType.IMPROPER_BUNDLING,
        OpportunityType.BALANCE_BILL,
        OpportunityType.DEDUCTIBLE_MISAPPLIED,
    )
    finding_title = "Recoverable claim dollars"
    max_candidates = 5

    # ------------------------------------------------------------------ entry

    def analysis_hours(self, dataset: HouseholdDataset) -> float:
        window = dataset.window()
        if window is None:
            return 720.0
        return max((window[1] - window[0]).total_seconds() / 3600.0, 1.0)

    # ----------------------------------------------------------------- detect

    def detect(self, dataset: HouseholdDataset) -> list[ResourceObservation]:
        if not getattr(dataset, "claims", None):
            return []
        now = dataset.reference_time()
        observations: list[ResourceObservation] = []
        observations.extend(self._detect_denials(dataset, now))
        observations.extend(self._detect_underpayments(dataset, now))
        observations.extend(self._detect_duplicates(dataset, now))
        observations.extend(self._detect_bundling(dataset, now))
        observations.extend(self._detect_balance_bills(dataset, now))
        observations.extend(self._detect_deductible_errors(dataset, now))
        return observations

    # ---- denial

    def _detect_denials(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for line in dataset.claims:
            if not line.is_denied or line.patient_responsibility < MIN_RECOVERABLE_DOLLARS:
                continue
            policy = dataset.policy_for(line.payer_id)
            if policy is None:
                continue
            # A denial is only recoverable if the payer's own policy covers the
            # code. An excluded code was correctly denied and is not a finding.
            if not policy.covers(line.procedure_code):
                continue

            plan = dataset.plan_for(line.member_id)
            recoverable = self._recoverable_from_denial(line, plan, policy)
            if recoverable < MIN_RECOVERABLE_DOLLARS:
                continue

            days_left = policy.internal_appeal_days - line.days_since_processed(now)
            out.append(
                ResourceObservation(
                    observation_id=f"denial:{line.claim_id}:{line.line_id}",
                    signal_type=OpportunityType.CLAIM_DENIED,
                    resource_id=f"{line.claim_id}:{line.line_id}",
                    timestamp=line.processed_date or line.service_date,
                    severity=min(1.0, recoverable / 2000.0),
                    description=(
                        f"{line.payer_id} denied {line.procedure_code} with code "
                        f"{line.denial_code or 'none given'} and billed the member "
                        f"${line.patient_responsibility:,.2f}, but the plan's own policy "
                        f"covers {line.procedure_code}."
                    ),
                    evidence={
                        "signal_reason": (
                            f"Denial code {line.denial_code or 'unspecified'} on a covered code"
                        ),
                        "procedure_code": line.procedure_code,
                        "denial_code": line.denial_code,
                        "denial_reason": line.denial_reason,
                        "billed_amount": line.billed_amount,
                        "patient_responsibility": line.patient_responsibility,
                        "policy_covers_code": True,
                        "filing_days_remaining": round(days_left, 1),
                        "prior_auth_required": line.procedure_code in policy.prior_auth_codes,
                        "prior_auth_obtained": line.prior_auth_obtained,
                    },
                    data_completeness=1.0 if line.processed_date else 0.7,
                    signal_strength=0.9 if line.denial_code else 0.6,
                    recurrence=self._recurrence(dataset, line),
                )
            )
        return out

    def _recoverable_from_denial(
        self, line: ClaimLine, plan: MemberPlan | None, policy: PayerPolicy
    ) -> float:
        """What the member gets back if the denial is overturned.

        The payer would pay the allowed amount less the member's real cost
        share. Where the contracted rate is known it beats the billed amount,
        because billed charges are not what anyone actually pays.
        """
        allowed = line.allowed_amount or policy.allowed_amounts.get(
            line.procedure_code, line.billed_amount
        )
        allowed = min(allowed, line.billed_amount) if line.billed_amount else allowed
        member_share = self._expected_member_share(allowed, plan)
        recoverable = line.patient_responsibility - member_share
        return max(0.0, min(recoverable, line.patient_responsibility))

    @staticmethod
    def _expected_member_share(allowed: float, plan: MemberPlan | None) -> float:
        """Deductible first, then coinsurance, capped by out-of-pocket max."""
        if plan is None:
            return 0.0
        to_deductible = min(allowed, plan.deductible_remaining)
        after_deductible = allowed - to_deductible
        coinsurance = after_deductible * max(0.0, min(1.0, plan.coinsurance_rate))
        share = to_deductible + coinsurance
        return min(share, plan.out_of_pocket_remaining)

    # ---- underpayment

    def _detect_underpayments(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for line in dataset.claims:
            if line.is_denied or line.allowed_amount <= 0:
                continue
            plan = dataset.plan_for(line.member_id)
            if plan is None:
                continue
            expected_share = self._expected_member_share(line.allowed_amount, plan)
            overcharge = line.patient_responsibility - expected_share
            if overcharge < max(MIN_RECOVERABLE_DOLLARS, UNDERPAYMENT_TOLERANCE):
                continue
            out.append(
                ResourceObservation(
                    observation_id=f"underpaid:{line.claim_id}:{line.line_id}",
                    signal_type=OpportunityType.CLAIM_UNDERPAID,
                    resource_id=f"{line.claim_id}:{line.line_id}",
                    timestamp=line.processed_date or line.service_date,
                    severity=min(1.0, overcharge / 1000.0),
                    description=(
                        f"On an allowed amount of ${line.allowed_amount:,.2f} the member's "
                        f"cost share should be ${expected_share:,.2f}, but the payer billed "
                        f"${line.patient_responsibility:,.2f}."
                    ),
                    evidence={
                        "signal_reason": "Member cost share exceeds plan terms on the allowed amount",
                        "allowed_amount": line.allowed_amount,
                        "plan_paid": line.plan_paid,
                        "expected_member_share": round(expected_share, 2),
                        "charged_member": line.patient_responsibility,
                        "deductible_remaining": plan.deductible_remaining,
                        "coinsurance_rate": plan.coinsurance_rate,
                    },
                    data_completeness=1.0,
                    signal_strength=0.85,
                    recurrence=self._recurrence(dataset, line),
                )
            )
        return out

    # ---- duplicates

    def _detect_duplicates(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        groups: dict[tuple, list[ClaimLine]] = defaultdict(list)
        for line in dataset.claims:
            if line.patient_responsibility <= 0:
                continue
            groups[
                (
                    line.member_id,
                    line.provider_id,
                    line.service_date.date(),
                    line.procedure_code,
                    tuple(sorted(line.modifiers)),
                )
            ].append(line)

        out: list[ResourceObservation] = []
        for key, lines in groups.items():
            if len(lines) < 2:
                continue
            lines.sort(key=lambda l: (l.processed_date or l.service_date))
            # The first submission stands; every later identical line is the
            # duplicate, and its whole member charge is recoverable.
            for dup in lines[1:]:
                if dup.patient_responsibility < MIN_RECOVERABLE_DOLLARS:
                    continue
                out.append(
                    ResourceObservation(
                        observation_id=f"duplicate:{dup.claim_id}:{dup.line_id}",
                        signal_type=OpportunityType.DUPLICATE_CHARGE,
                        resource_id=f"{dup.claim_id}:{dup.line_id}",
                        timestamp=dup.processed_date or dup.service_date,
                        severity=min(1.0, dup.patient_responsibility / 500.0),
                        description=(
                            f"{dup.procedure_code} was billed {len(lines)} times by "
                            f"{dup.provider_name or dup.provider_id} for one service date "
                            f"({dup.service_date.date()}), with no distinguishing modifier."
                        ),
                        evidence={
                            "signal_reason": "Identical code, provider, and service date billed more than once",
                            "duplicate_of": lines[0].line_id,
                            "occurrences": len(lines),
                            "procedure_code": dup.procedure_code,
                            "service_date": dup.service_date.isoformat(),
                            "charged_member": dup.patient_responsibility,
                        },
                        data_completeness=1.0,
                        signal_strength=0.95,
                        recurrence=len(lines) - 1,
                    )
                )
        return out

    # ---- bundling

    def _detect_bundling(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        by_encounter: dict[tuple, list[ClaimLine]] = defaultdict(list)
        for line in dataset.claims:
            by_encounter[(line.member_id, line.provider_id, line.service_date.date())].append(line)

        out: list[ResourceObservation] = []
        for lines in by_encounter.values():
            if len(lines) < 2:
                continue
            policy = dataset.policy_for(lines[0].payer_id)
            if policy is None:
                continue
            for i, primary in enumerate(lines):
                for secondary in lines[i + 1 :]:
                    if not policy.bundles(primary.procedure_code, secondary.procedure_code):
                        continue
                    # A modifier on either line is the payer's own mechanism for
                    # allowing the split. If one is present the split is proper.
                    modifiers = set(primary.modifiers) | set(secondary.modifiers)
                    if modifiers & policy.unbundling_modifiers:
                        continue
                    # The lesser line is the one that should not have been paid
                    # separately, so its member charge is what is recoverable.
                    lesser = min(primary, secondary, key=lambda l: l.patient_responsibility)
                    if lesser.patient_responsibility < MIN_RECOVERABLE_DOLLARS:
                        continue
                    other = secondary if lesser is primary else primary
                    out.append(
                        ResourceObservation(
                            observation_id=f"bundling:{lesser.claim_id}:{lesser.line_id}",
                            signal_type=OpportunityType.IMPROPER_BUNDLING,
                            resource_id=f"{lesser.claim_id}:{lesser.line_id}",
                            timestamp=lesser.processed_date or lesser.service_date,
                            severity=min(1.0, lesser.patient_responsibility / 500.0),
                            description=(
                                f"{primary.procedure_code} and {secondary.procedure_code} were "
                                "billed separately on one encounter, but the payer's edit table "
                                "bundles them and no modifier justifies the split."
                            ),
                            evidence={
                                "signal_reason": "Bundled code pair billed separately without a modifier",
                                "code_pair": [primary.procedure_code, secondary.procedure_code],
                                "modifiers_present": sorted(modifiers),
                                "recognized_unbundling_modifiers": sorted(
                                    policy.unbundling_modifiers
                                ),
                                "bundled_into": other.procedure_code,
                                "charged_member": lesser.patient_responsibility,
                            },
                            data_completeness=1.0,
                            signal_strength=0.8,
                            recurrence=0,
                        )
                    )
        return out

    # ---- balance billing

    def _detect_balance_bills(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for line in dataset.claims:
            if line.network_status != "in_network" or line.allowed_amount <= 0:
                continue
            # Under an in-network contract the member cannot be charged above
            # the allowed amount less what the plan paid.
            ceiling = line.expected_patient_share
            excess = line.patient_responsibility - ceiling
            if excess < MIN_RECOVERABLE_DOLLARS:
                continue
            out.append(
                ResourceObservation(
                    observation_id=f"balancebill:{line.claim_id}:{line.line_id}",
                    signal_type=OpportunityType.BALANCE_BILL,
                    resource_id=f"{line.claim_id}:{line.line_id}",
                    timestamp=line.processed_date or line.service_date,
                    severity=min(1.0, excess / 1000.0),
                    description=(
                        f"{line.provider_name or line.provider_id} is in network and billed the "
                        f"member ${line.patient_responsibility:,.2f} against an allowed amount of "
                        f"${line.allowed_amount:,.2f}, ${excess:,.2f} above the contract ceiling."
                    ),
                    evidence={
                        "signal_reason": "In-network provider charged above the contracted allowed amount",
                        "allowed_amount": line.allowed_amount,
                        "plan_paid": line.plan_paid,
                        "contract_ceiling": round(ceiling, 2),
                        "charged_member": line.patient_responsibility,
                        "excess": round(excess, 2),
                    },
                    data_completeness=1.0,
                    signal_strength=0.9,
                    recurrence=self._recurrence(dataset, line),
                )
            )
        return out

    # ---- deductible

    def _detect_deductible_errors(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for line in dataset.claims:
            if line.applied_to_deductible < MIN_RECOVERABLE_DOLLARS:
                continue
            plan = dataset.plan_for(line.member_id)
            if plan is None or not plan.deductible_satisfied:
                continue
            # The deductible was already met, so this money should have been
            # adjudicated at coinsurance instead of charged in full.
            should_owe = line.applied_to_deductible * max(0.0, min(1.0, plan.coinsurance_rate))
            recoverable = line.applied_to_deductible - should_owe
            if recoverable < MIN_RECOVERABLE_DOLLARS:
                continue
            out.append(
                ResourceObservation(
                    observation_id=f"deductible:{line.claim_id}:{line.line_id}",
                    signal_type=OpportunityType.DEDUCTIBLE_MISAPPLIED,
                    resource_id=f"{line.claim_id}:{line.line_id}",
                    timestamp=line.processed_date or line.service_date,
                    severity=min(1.0, recoverable / 1000.0),
                    description=(
                        f"${line.applied_to_deductible:,.2f} was applied to a deductible that "
                        f"was already satisfied (${plan.deductible_met:,.2f} of "
                        f"${plan.deductible:,.2f} met)."
                    ),
                    evidence={
                        "signal_reason": "Charge applied to an already-satisfied deductible",
                        "applied_to_deductible": line.applied_to_deductible,
                        "deductible": plan.deductible,
                        "deductible_met": plan.deductible_met,
                        "coinsurance_rate": plan.coinsurance_rate,
                        "should_owe_at_coinsurance": round(should_owe, 2),
                    },
                    data_completeness=1.0,
                    signal_strength=0.9,
                    recurrence=self._recurrence(dataset, line),
                )
            )
        return out

    @staticmethod
    def _recurrence(dataset: HouseholdDataset, line: ClaimLine) -> int:
        """How often this payer has produced the same denial code this window.

        A pattern across several claims is stronger evidence than one line,
        and it is also the argument that wins a systemic appeal.
        """
        if not line.denial_code:
            return 0
        return max(
            0,
            sum(
                1
                for other in dataset.claims
                if other.denial_code == line.denial_code
                and other.payer_id == line.payer_id
                and other.line_id != line.line_id
            ),
        )

    # ------------------------------------------------------------- candidates

    def generate_candidates(
        self, dataset: HouseholdDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        line = self._line_for(dataset, observation)
        if line is None:
            return []
        policy = dataset.policy_for(line.payer_id)
        plan = dataset.plan_for(line.member_id)
        recoverable = self._recoverable(dataset, observation, line, plan, policy)
        if recoverable <= 0:
            return []

        claim_id = observation.resource_id
        signal = observation.signal_type
        candidates: list[ResourceCandidate] = []

        # Every condition can be argued to the payer. The argument differs.
        candidates.append(
            ResourceCandidate(
                kind="internal_appeal",
                description=(
                    f"File a first-level internal appeal for ${recoverable:,.2f} on "
                    f"{line.procedure_code}."
                ),
                proposed_action={
                    "kind": "internal_appeal",
                    "claim_id": line.claim_id,
                    "line_id": line.line_id,
                    "payer_id": line.payer_id,
                    "procedure_code": line.procedure_code,
                    "amount_disputed": round(recoverable, 2),
                    "argument": self._argument(signal, line, plan, policy),
                    "filing_deadline_days": (
                        policy.internal_appeal_days if policy else None
                    ),
                },
                rationale=self._argument(signal, line, plan, policy),
                source="rules:internal_appeal",
                claim=_dollars(claim_id, recoverable),
            )
        )

        # Coding problems are faster to fix by resubmission than by argument,
        # and a corrected claim does not consume an appeal level.
        if signal in {
            OpportunityType.IMPROPER_BUNDLING,
            OpportunityType.DUPLICATE_CHARGE,
        }:
            candidates.append(
                ResourceCandidate(
                    kind="corrected_resubmission",
                    description=(
                        f"Ask the provider to void and resubmit the line, recovering "
                        f"${recoverable:,.2f} without spending an appeal level."
                    ),
                    proposed_action={
                        "kind": "corrected_resubmission",
                        "claim_id": line.claim_id,
                        "line_id": line.line_id,
                        "provider_id": line.provider_id,
                        "amount_disputed": round(recoverable, 2),
                        "reason": (
                            "duplicate submission"
                            if signal is OpportunityType.DUPLICATE_CHARGE
                            else "bundled codes billed separately without a modifier"
                        ),
                    },
                    rationale=(
                        "A billing correction resolves this faster than an appeal and keeps "
                        "both internal appeal levels available if it fails."
                    ),
                    source="rules:corrected_resubmission",
                    claim=_dollars(claim_id, recoverable),
                )
            )

        # A balance bill is a contract dispute with the provider, not a
        # coverage dispute with the payer.
        if signal is OpportunityType.BALANCE_BILL:
            candidates.append(
                ResourceCandidate(
                    kind="balance_bill_dispute",
                    description=(
                        f"Dispute ${recoverable:,.2f} with the provider under the in-network "
                        "contract ceiling, copying the payer."
                    ),
                    proposed_action={
                        "kind": "balance_bill_dispute",
                        "claim_id": line.claim_id,
                        "line_id": line.line_id,
                        "provider_id": line.provider_id,
                        "payer_id": line.payer_id,
                        "allowed_amount": line.allowed_amount,
                        "amount_disputed": round(recoverable, 2),
                    },
                    rationale=(
                        "The provider's own network contract caps member responsibility at the "
                        "allowed amount, so this is enforceable without a coverage argument."
                    ),
                    source="rules:balance_bill_dispute",
                    claim=_dollars(claim_id, recoverable),
                )
            )

        # Once internal appeals are exhausted, external review is the path that
        # is still open, and independent reviewers overturn a large share.
        if line.appeal_count >= 1 and policy is not None:
            candidates.append(
                ResourceCandidate(
                    kind="external_review",
                    description=(
                        f"Request independent external review of ${recoverable:,.2f}; the "
                        "internal appeal has already been used."
                    ),
                    proposed_action={
                        "kind": "external_review",
                        "claim_id": line.claim_id,
                        "line_id": line.line_id,
                        "payer_id": line.payer_id,
                        "amount_disputed": round(recoverable, 2),
                        "filing_deadline_days": policy.external_review_days,
                    },
                    rationale=(
                        "Internal appeal is exhausted and the external review window is open. "
                        "An independent reviewer is not the party that issued the denial."
                    ),
                    source="rules:external_review",
                    claim=_dollars(claim_id, recoverable),
                )
            )

        return candidates

    def _argument(
        self,
        signal: OpportunityType,
        line: ClaimLine,
        plan: MemberPlan | None,
        policy: PayerPolicy | None,
    ) -> str:
        """The specific rule the appeal cites. Never a generic complaint."""
        if signal is OpportunityType.CLAIM_DENIED:
            return (
                f"The plan's own coverage policy lists {line.procedure_code} as covered, and "
                f"denial code {line.denial_code or 'unspecified'} does not apply to the "
                "documented service."
            )
        if signal is OpportunityType.CLAIM_UNDERPAID:
            share = self._expected_member_share(line.allowed_amount, plan)
            return (
                f"On an allowed amount of ${line.allowed_amount:,.2f} the plan's cost-sharing "
                f"terms produce a member responsibility of ${share:,.2f}, not "
                f"${line.patient_responsibility:,.2f}."
            )
        if signal is OpportunityType.DUPLICATE_CHARGE:
            return (
                f"{line.procedure_code} was already adjudicated for this provider and service "
                "date; this line is a duplicate submission."
            )
        if signal is OpportunityType.IMPROPER_BUNDLING:
            return (
                "The payer's own correct-coding edits bundle these procedures, and no "
                "distinguishing modifier was submitted to justify billing them separately."
            )
        if signal is OpportunityType.BALANCE_BILL:
            return (
                "The provider is in network, so the contract caps member responsibility at the "
                f"allowed amount of ${line.allowed_amount:,.2f}."
            )
        if signal is OpportunityType.DEDUCTIBLE_MISAPPLIED:
            met = plan.deductible_met if plan else 0.0
            return (
                f"The member's deductible was already satisfied (${met:,.2f} met) on the date "
                "of service, so this charge should have been adjudicated at coinsurance."
            )
        return "The adjudication does not follow from the plan's stated terms."

    # ------------------------------------------------------------- validation

    def validate_candidate(
        self,
        dataset: HouseholdDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> tuple[list[str], list[str]]:
        """Hard checks. Rules decide feasibility, never the drafted argument."""
        line = self._line_for(dataset, observation)
        checked: list[str] = []
        violations: list[str] = []
        if line is None:
            return checked, ["Claim line no longer present in the dataset."]

        policy = dataset.policy_for(line.payer_id)
        now = dataset.reference_time()
        kind = candidate.proposed_action.get("kind")

        # 1. The filing window has to still be open, with room to be received.
        checked.append("filing_window_open")
        if policy is not None:
            elapsed = line.days_since_processed(now)
            limit = (
                policy.external_review_days
                if kind == "external_review"
                else policy.internal_appeal_days
            )
            if elapsed > limit:
                violations.append(
                    f"Filing window closed: {elapsed:.0f} days since adjudication exceeds the "
                    f"{limit}-day limit."
                )
            elif elapsed > limit - FILING_BUFFER_DAYS:
                violations.append(
                    f"Only {limit - elapsed:.0f} days remain of the {limit}-day window, inside "
                    f"the {FILING_BUFFER_DAYS}-day buffer required for delivery."
                )

        # 2. An excluded code was correctly denied. There is nothing to appeal.
        checked.append("code_covered_by_policy")
        if policy is not None and not policy.covers(line.procedure_code):
            violations.append(
                f"{line.procedure_code} is excluded by the plan, so the denial follows policy."
            )

        # 3. Prior authorization that was required and not obtained is a real
        #    denial reason, and an appeal on coverage grounds will not carry it.
        checked.append("prior_authorization_satisfied")
        if (
            policy is not None
            and kind in {"internal_appeal", "external_review"}
            and line.procedure_code in policy.prior_auth_codes
            and not line.prior_auth_obtained
        ):
            violations.append(
                f"{line.procedure_code} required prior authorization that was not obtained; "
                "the denial has a valid basis."
            )

        # 4. Never claim more than the member was actually charged.
        checked.append("claim_within_member_charge")
        claimed = candidate.claim.primary_quantity
        if claimed > line.patient_responsibility + 0.01:
            violations.append(
                f"Claim of ${claimed:,.2f} exceeds the ${line.patient_responsibility:,.2f} "
                "the member was billed."
            )

        # 5. External review only exists once internal appeal is exhausted.
        if kind == "external_review":
            checked.append("internal_appeal_exhausted")
            if line.appeal_count < 1:
                violations.append(
                    "External review requires the internal appeal to be filed and decided first."
                )

        # 6. Do not re-file something already under appeal.
        checked.append("not_already_pending")
        if line.is_appealed and kind == "internal_appeal" and line.appeal_count >= 2:
            violations.append(
                f"This line has already been appealed {line.appeal_count} times; internal "
                "levels are exhausted."
            )

        return checked, violations

    def claim_cap(self, dataset: HouseholdDataset, observation: ResourceObservation) -> float:
        """A member can never recover more than they were charged."""
        line = self._line_for(dataset, observation)
        if line is None:
            return 0.0
        return max(0.0, line.patient_responsibility)

    # ----------------------------------------------------------------- action

    def recommended_action(
        self,
        dataset: HouseholdDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        line = self._line_for(dataset, observation)
        amount = candidate.claim.primary_quantity
        kind = candidate.proposed_action.get("kind", "appeal")
        if line is None:
            return f"Dispute ${amount:,.2f}."
        verb = {
            "internal_appeal": f"File a first-level appeal with {line.payer_id}",
            "corrected_resubmission": (
                f"Ask {line.provider_name or line.provider_id} to void and resubmit"
            ),
            "balance_bill_dispute": (
                f"Dispute the balance bill with {line.provider_name or line.provider_id}"
            ),
            "external_review": "Request independent external review",
        }.get(kind, "Dispute the line")
        return (
            f"{verb} for ${amount:,.2f} on claim {line.claim_id} line {line.line_id} "
            f"({line.procedure_code}, service date {line.service_date.date()}). "
            f"{self._argument(observation.signal_type, line, dataset.plan_for(line.member_id), dataset.policy_for(line.payer_id))}"
        )

    # ---------------------------------------------------------------- helpers

    def _recoverable(
        self,
        dataset: HouseholdDataset,
        observation: ResourceObservation,
        line: ClaimLine,
        plan: MemberPlan | None,
        policy: PayerPolicy | None,
    ) -> float:
        """The deterministic dollar amount, per condition.

        Probability of winning lives in the confidence score, never in here.
        This number is what the member is owed if the argument lands.
        """
        signal = observation.signal_type
        if signal is OpportunityType.CLAIM_DENIED and policy is not None:
            return round(self._recoverable_from_denial(line, plan, policy), 2)
        if signal is OpportunityType.CLAIM_UNDERPAID:
            expected = self._expected_member_share(line.allowed_amount, plan)
            return round(max(0.0, line.patient_responsibility - expected), 2)
        if signal is OpportunityType.DUPLICATE_CHARGE:
            return round(line.patient_responsibility, 2)
        if signal is OpportunityType.IMPROPER_BUNDLING:
            return round(line.patient_responsibility, 2)
        if signal is OpportunityType.BALANCE_BILL:
            return round(max(0.0, line.patient_responsibility - line.expected_patient_share), 2)
        if signal is OpportunityType.DEDUCTIBLE_MISAPPLIED and plan is not None:
            should = line.applied_to_deductible * max(0.0, min(1.0, plan.coinsurance_rate))
            return round(max(0.0, line.applied_to_deductible - should), 2)
        return 0.0

    @staticmethod
    def _line_for(
        dataset: HouseholdDataset, observation: ResourceObservation
    ) -> ClaimLine | None:
        claim_id, _, line_id = observation.resource_id.partition(":")
        for line in dataset.claims:
            if line.claim_id == claim_id and line.line_id == line_id:
                return line
        return None
