"""Recurring household spend agent.

Objective: the recurring-dollars meter. Money that leaves a household every
month until somebody stops it. This is a different meter from claim recovery
and that separation is the whole point of the fleet design: a recovered
medical dollar and a cancelled subscription are not the same dollar, so they
are counted in different meters and never credited against each other.

Five conditions:

    unused subscription    charged every cycle, not used in the observed window
    duplicate service      two merchants billing for the same category at once
    silent price hike      the amount rose without a new agreement
    trial conversion       a trial about to convert into a real charge
    billing term arbitrage the same service costs less billed annually

The meter is dollars per month, so this agent's findings are a run rate and
`estimated_monthly_value` is the honest figure. Claim recovery is a one-time
recovery. The ledger reports them separately rather than adding them.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from natilah.agents.resource_agent import (
    ResourceAgent,
    ResourceCandidate,
    ResourceObservation,
)
from natilah.models.consumer import HouseholdDataset, RecurringCharge
from natilah.models.domain import ResourceClaim, ResourceQuantity
from natilah.models.enums import AgentObjective, Meter, OpportunityType

# Below this a monthly saving is not worth an interruption.
MIN_MONTHLY_DOLLARS = 2.0

# Unused for this long, across at least two billing cycles, is dormant.
DORMANT_DAYS = 60

# A rise of at least this much is a hike rather than a tax or rounding change.
PRICE_HIKE_FRACTION = 0.08

# How near a trial has to be to converting before it is worth surfacing.
TRIAL_HORIZON_DAYS = 14

# Categories where two active merchants is genuinely redundant. Two streaming
# services is a choice; two password managers is an oversight.
EXCLUSIVE_CATEGORIES = {
    "password_manager",
    "cloud_storage",
    "vpn",
    "antivirus",
    "music_streaming",
    "fitness_app",
    "note_taking",
}


def _monthly(charge_id: str, amount_per_month: float, basis: str) -> ResourceClaim:
    """A claim in dollars per month, scoped to the charge it stops."""
    return ResourceClaim(
        primary_meter=Meter.RECURRING_DOLLARS,
        quantities=[
            ResourceQuantity(
                meter=Meter.RECURRING_DOLLARS, resource_id=charge_id, amount=amount_per_month
            )
        ],
        basis=basis,
    )


class RecurringSpendAgent(ResourceAgent):
    """One agent, one meter: dollars leaving the household every month."""

    name = "recurring_spend_agent"
    objective = AgentObjective.RECURRING_SPEND
    primary_meter = Meter.RECURRING_DOLLARS
    signal_types = (
        OpportunityType.UNUSED_SUBSCRIPTION,
        OpportunityType.DUPLICATE_SERVICE,
        OpportunityType.SILENT_PRICE_HIKE,
        OpportunityType.TRIAL_CONVERSION,
        OpportunityType.BILLING_TERM_ARBITRAGE,
    )
    finding_title = "Recurring spend"
    max_candidates = 4

    # ------------------------------------------------------------------ entry

    def analysis_hours(self, dataset: HouseholdDataset) -> float:
        window = dataset.window()
        if window is None:
            return 720.0
        return max((window[1] - window[0]).total_seconds() / 3600.0, 1.0)

    # ----------------------------------------------------------------- detect

    def detect(self, dataset: HouseholdDataset) -> list[ResourceObservation]:
        if not getattr(dataset, "charges", None):
            return []
        now = dataset.reference_time()
        return [
            *self._detect_unused(dataset, now),
            *self._detect_duplicates(dataset, now),
            *self._detect_price_hikes(dataset, now),
            *self._detect_trials(dataset, now),
            *self._detect_term_arbitrage(dataset, now),
        ]

    def _detect_unused(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for charge in dataset.charges:
            if charge.monthly_amount < MIN_MONTHLY_DOLLARS or not charge.cancellable:
                continue
            idle_days = charge.days_since_used(now)
            # Charged repeatedly and untouched. One cycle is not evidence.
            if idle_days < DORMANT_DAYS or charge.charge_count < 2:
                continue
            if charge.usage_events_30d > 0:
                continue
            known_usage = charge.last_used_at is not None
            out.append(
                ResourceObservation(
                    observation_id=f"unused:{charge.charge_id}",
                    signal_type=OpportunityType.UNUSED_SUBSCRIPTION,
                    resource_id=charge.charge_id,
                    timestamp=charge.last_charged_at,
                    severity=min(1.0, charge.annualized / 600.0),
                    description=(
                        f"{charge.merchant} has charged {charge.charge_count} times "
                        f"(${charge.monthly_amount:,.2f}/month) with no recorded use in "
                        + (
                            f"{idle_days:.0f} days."
                            if known_usage
                            else "the observed window."
                        )
                    ),
                    evidence={
                        "signal_reason": "Recurring charge with no usage across multiple cycles",
                        "merchant": charge.merchant,
                        "monthly_amount": round(charge.monthly_amount, 2),
                        "annualized": round(charge.annualized, 2),
                        "charge_count": charge.charge_count,
                        "days_since_used": None if idle_days == float("inf") else round(idle_days, 1),
                        "usage_feed_available": known_usage,
                    },
                    # No usage feed is a real gap and the finding says so
                    # rather than treating absence of data as absence of use.
                    data_completeness=1.0 if known_usage else 0.55,
                    signal_strength=0.9 if known_usage else 0.6,
                    recurrence=charge.charge_count,
                )
            )
        return out

    def _detect_duplicates(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        by_category: dict[str, list[RecurringCharge]] = defaultdict(list)
        for charge in dataset.charges:
            if charge.category in EXCLUSIVE_CATEGORIES:
                by_category[charge.category].append(charge)

        out: list[ResourceObservation] = []
        for category, charges in by_category.items():
            if len(charges) < 2:
                continue
            # Keep the cheapest, and the rest are the redundant ones.
            charges.sort(key=lambda c: c.monthly_amount)
            keep = charges[0]
            for extra in charges[1:]:
                if extra.monthly_amount < MIN_MONTHLY_DOLLARS or not extra.cancellable:
                    continue
                out.append(
                    ResourceObservation(
                        observation_id=f"duplicate:{extra.charge_id}",
                        signal_type=OpportunityType.DUPLICATE_SERVICE,
                        resource_id=extra.charge_id,
                        timestamp=extra.last_charged_at,
                        severity=min(1.0, extra.annualized / 600.0),
                        description=(
                            f"{extra.merchant} and {keep.merchant} both bill for {category}. "
                            f"Keeping {keep.merchant} at ${keep.monthly_amount:,.2f}/month "
                            f"releases ${extra.monthly_amount:,.2f}/month."
                        ),
                        evidence={
                            "signal_reason": f"Two active {category} services billed at once",
                            "category": category,
                            "redundant_merchant": extra.merchant,
                            "retained_merchant": keep.merchant,
                            "retained_monthly": round(keep.monthly_amount, 2),
                            "released_monthly": round(extra.monthly_amount, 2),
                        },
                        data_completeness=1.0,
                        signal_strength=0.8,
                        recurrence=len(charges) - 1,
                    )
                )
        return out

    def _detect_price_hikes(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for charge in dataset.charges:
            previous = charge.previous_amount
            if not previous or previous <= 0:
                continue
            increase = charge.amount - previous
            if increase <= 0 or (increase / previous) < PRICE_HIKE_FRACTION:
                continue
            monthly_increase = increase / max(
                1e-9, charge.amount / max(charge.monthly_amount, 1e-9)
            )
            if monthly_increase < MIN_MONTHLY_DOLLARS:
                continue
            out.append(
                ResourceObservation(
                    observation_id=f"hike:{charge.charge_id}",
                    signal_type=OpportunityType.SILENT_PRICE_HIKE,
                    resource_id=charge.charge_id,
                    timestamp=charge.price_changed_at or charge.last_charged_at,
                    severity=min(1.0, (increase / previous)),
                    description=(
                        f"{charge.merchant} raised its price from ${previous:,.2f} to "
                        f"${charge.amount:,.2f} ({increase / previous:.0%}), which is "
                        f"${monthly_increase:,.2f}/month more."
                    ),
                    evidence={
                        "signal_reason": "Price increased without a new agreement",
                        "merchant": charge.merchant,
                        "previous_amount": previous,
                        "current_amount": charge.amount,
                        "increase_fraction": round(increase / previous, 4),
                        "monthly_increase": round(monthly_increase, 2),
                        "changed_at": (
                            charge.price_changed_at.isoformat()
                            if charge.price_changed_at
                            else None
                        ),
                    },
                    data_completeness=1.0,
                    signal_strength=0.85,
                    recurrence=0,
                )
            )
        return out

    def _detect_trials(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for charge in dataset.charges:
            if charge.trial_ends_at is None:
                continue
            days = (charge.trial_ends_at - now).total_seconds() / 86400.0
            if days < 0 or days > TRIAL_HORIZON_DAYS:
                continue
            if charge.monthly_amount < MIN_MONTHLY_DOLLARS:
                continue
            out.append(
                ResourceObservation(
                    observation_id=f"trial:{charge.charge_id}",
                    signal_type=OpportunityType.TRIAL_CONVERSION,
                    resource_id=charge.charge_id,
                    timestamp=charge.trial_ends_at,
                    severity=min(1.0, charge.annualized / 400.0),
                    description=(
                        f"{charge.merchant} converts from trial to "
                        f"${charge.monthly_amount:,.2f}/month in {days:.0f} days."
                    ),
                    evidence={
                        "signal_reason": "Trial converts to a paid charge inside the horizon",
                        "merchant": charge.merchant,
                        "trial_ends_at": charge.trial_ends_at.isoformat(),
                        "days_remaining": round(days, 1),
                        "monthly_amount": round(charge.monthly_amount, 2),
                        "used_recently": charge.usage_events_30d > 0,
                    },
                    data_completeness=1.0,
                    # A trial the household actually uses is not waste, so the
                    # signal is weak when there is real usage behind it.
                    signal_strength=0.9 if charge.usage_events_30d == 0 else 0.35,
                    recurrence=0,
                )
            )
        return out

    def _detect_term_arbitrage(
        self, dataset: HouseholdDataset, now: datetime
    ) -> list[ResourceObservation]:
        out: list[ResourceObservation] = []
        for charge in dataset.charges:
            annual = charge.annual_equivalent_amount
            if not annual or charge.cadence != "monthly":
                continue
            monthly_equivalent = annual / 12.0
            saving = charge.monthly_amount - monthly_equivalent
            if saving < MIN_MONTHLY_DOLLARS:
                continue
            # Only worth switching where the household actually uses it.
            if charge.usage_events_30d == 0 and charge.days_since_used(now) > DORMANT_DAYS:
                continue
            out.append(
                ResourceObservation(
                    observation_id=f"term:{charge.charge_id}",
                    signal_type=OpportunityType.BILLING_TERM_ARBITRAGE,
                    resource_id=charge.charge_id,
                    timestamp=charge.last_charged_at,
                    severity=min(1.0, saving * 12.0 / 400.0),
                    description=(
                        f"{charge.merchant} costs ${charge.monthly_amount:,.2f}/month monthly "
                        f"but ${monthly_equivalent:,.2f}/month billed annually, a saving of "
                        f"${saving:,.2f}/month on a service in active use."
                    ),
                    evidence={
                        "signal_reason": "Annual billing is cheaper for a service already in use",
                        "merchant": charge.merchant,
                        "monthly_price": round(charge.monthly_amount, 2),
                        "annual_price": round(annual, 2),
                        "annual_as_monthly": round(monthly_equivalent, 2),
                        "monthly_saving": round(saving, 2),
                        "usage_events_30d": charge.usage_events_30d,
                    },
                    data_completeness=1.0,
                    signal_strength=0.75,
                    recurrence=0,
                )
            )
        return out

    # ------------------------------------------------------------- candidates

    def generate_candidates(
        self, dataset: HouseholdDataset, observation: ResourceObservation
    ) -> list[ResourceCandidate]:
        charge = self._charge_for(dataset, observation)
        if charge is None:
            return []
        signal = observation.signal_type
        cid = charge.charge_id
        monthly = charge.monthly_amount
        candidates: list[ResourceCandidate] = []

        if signal in {
            OpportunityType.UNUSED_SUBSCRIPTION,
            OpportunityType.DUPLICATE_SERVICE,
            OpportunityType.TRIAL_CONVERSION,
        }:
            candidates.append(
                ResourceCandidate(
                    kind="cancel",
                    description=f"Cancel {charge.merchant}, releasing ${monthly:,.2f}/month.",
                    proposed_action={
                        "kind": "cancel",
                        "charge_id": cid,
                        "merchant": charge.merchant,
                        "monthly_released": round(monthly, 2),
                        "cancel_before": (
                            charge.trial_ends_at.isoformat() if charge.trial_ends_at else None
                        ),
                    },
                    rationale=observation.evidence.get("signal_reason", ""),
                    source="rules:cancel",
                    claim=_monthly(cid, monthly, f"Full monthly charge for {charge.merchant}"),
                )
            )
            # Downgrading keeps the service and recovers part of the money, so
            # it is a real alternative rather than a weaker version of cancel.
            candidates.append(
                ResourceCandidate(
                    kind="downgrade",
                    description=(
                        f"Downgrade {charge.merchant} to its entry tier, recovering roughly "
                        f"${monthly * 0.5:,.2f}/month while keeping access."
                    ),
                    proposed_action={
                        "kind": "downgrade",
                        "charge_id": cid,
                        "merchant": charge.merchant,
                        "monthly_released": round(monthly * 0.5, 2),
                    },
                    rationale=(
                        "Keeps the service available at lower cost, which is the reversible "
                        "option when usage data is incomplete."
                    ),
                    source="rules:downgrade",
                    claim=_monthly(
                        cid, monthly * 0.5, f"Half the monthly charge for {charge.merchant}"
                    ),
                )
            )

        if signal is OpportunityType.SILENT_PRICE_HIKE:
            increase = float(observation.evidence.get("monthly_increase", 0.0))
            candidates.append(
                ResourceCandidate(
                    kind="negotiate",
                    description=(
                        f"Ask {charge.merchant} to restore the prior rate, recovering "
                        f"${increase:,.2f}/month."
                    ),
                    proposed_action={
                        "kind": "negotiate",
                        "charge_id": cid,
                        "merchant": charge.merchant,
                        "target_amount": observation.evidence.get("previous_amount"),
                        "monthly_released": round(increase, 2),
                    },
                    rationale=(
                        "Retention pricing usually restores the previous rate for an existing "
                        "customer, and the increase was not separately agreed."
                    ),
                    source="rules:negotiate",
                    claim=_monthly(cid, increase, f"Price increase applied by {charge.merchant}"),
                )
            )
            candidates.append(
                ResourceCandidate(
                    kind="cancel",
                    description=f"Cancel {charge.merchant} rather than accept the increase.",
                    proposed_action={
                        "kind": "cancel",
                        "charge_id": cid,
                        "merchant": charge.merchant,
                        "monthly_released": round(monthly, 2),
                    },
                    rationale="Cancelling recovers the whole charge, not only the increase.",
                    source="rules:cancel",
                    claim=_monthly(cid, monthly, f"Full monthly charge for {charge.merchant}"),
                )
            )

        if signal is OpportunityType.BILLING_TERM_ARBITRAGE:
            saving = float(observation.evidence.get("monthly_saving", 0.0))
            candidates.append(
                ResourceCandidate(
                    kind="switch_to_annual",
                    description=(
                        f"Switch {charge.merchant} to annual billing, saving "
                        f"${saving:,.2f}/month."
                    ),
                    proposed_action={
                        "kind": "switch_to_annual",
                        "charge_id": cid,
                        "merchant": charge.merchant,
                        "annual_price": observation.evidence.get("annual_price"),
                        "monthly_released": round(saving, 2),
                    },
                    rationale=(
                        "The service is in active use and the annual term is cheaper, so the "
                        "saving does not depend on changing behaviour."
                    ),
                    source="rules:switch_to_annual",
                    claim=_monthly(cid, saving, f"Term difference for {charge.merchant}"),
                )
            )

        return candidates

    # ------------------------------------------------------------- validation

    def validate_candidate(
        self,
        dataset: HouseholdDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> tuple[list[str], list[str]]:
        charge = self._charge_for(dataset, observation)
        checked: list[str] = []
        violations: list[str] = []
        if charge is None:
            return checked, ["Charge no longer present in the dataset."]

        now = dataset.reference_time()
        kind = candidate.proposed_action.get("kind")

        checked.append("charge_is_cancellable")
        if kind in {"cancel", "downgrade"} and not charge.cancellable:
            violations.append(f"{charge.merchant} is not cancellable in the observed window.")

        checked.append("no_active_contract_term")
        if (
            kind in {"cancel", "downgrade"}
            and charge.contract_ends_at is not None
            and charge.contract_ends_at > now
        ):
            days = (charge.contract_ends_at - now).total_seconds() / 86400.0
            violations.append(
                f"A contract term runs for another {days:.0f} days; cancelling early may "
                "incur a penalty that is not modelled."
            )

        checked.append("claim_within_monthly_charge")
        claimed = candidate.claim.primary_quantity
        if claimed > charge.monthly_amount + 0.01:
            violations.append(
                f"Claim of ${claimed:,.2f}/month exceeds the ${charge.monthly_amount:,.2f}/month "
                "actually charged."
            )

        checked.append("service_not_in_active_use")
        if kind == "cancel" and charge.usage_events_30d > 0:
            violations.append(
                f"{charge.merchant} was used {charge.usage_events_30d} times in the last 30 days; "
                "cancelling would remove a service in active use."
            )

        if kind == "switch_to_annual":
            checked.append("annual_price_known")
            if not charge.annual_equivalent_amount:
                violations.append("No annual price is published for this service.")

        return checked, violations

    def claim_cap(self, dataset: HouseholdDataset, observation: ResourceObservation) -> float:
        charge = self._charge_for(dataset, observation)
        if charge is None:
            return 0.0
        return max(0.0, charge.monthly_amount)

    # ----------------------------------------------------------------- action

    def recommended_action(
        self,
        dataset: HouseholdDataset,
        observation: ResourceObservation,
        candidate: ResourceCandidate,
    ) -> str:
        charge = self._charge_for(dataset, observation)
        amount = candidate.claim.primary_quantity
        kind = candidate.proposed_action.get("kind", "review")
        if charge is None:
            return f"Review the charge, worth ${amount:,.2f}/month."
        verb = {
            "cancel": f"Cancel {charge.merchant}",
            "downgrade": f"Downgrade {charge.merchant} to its entry tier",
            "negotiate": f"Ask {charge.merchant} to restore the previous rate",
            "switch_to_annual": f"Move {charge.merchant} to annual billing",
        }.get(kind, f"Review {charge.merchant}")
        deadline = ""
        if charge.trial_ends_at is not None:
            deadline = f" Act before the trial converts on {charge.trial_ends_at.date()}."
        return (
            f"{verb} to release ${amount:,.2f}/month (${amount * 12:,.2f}/year). "
            f"{observation.evidence.get('signal_reason', '')}.{deadline}"
        )

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _charge_for(
        dataset: HouseholdDataset, observation: ResourceObservation
    ) -> RecurringCharge | None:
        for charge in dataset.charges:
            if charge.charge_id == observation.resource_id:
                return charge
        return None
