"""Records for the consumer domains.

The scheduling model does not fit here. A denied medical claim is not a
scheduler decision and an over-priced subscription is not a standing condition
on a piece of hardware. What carries across is the shape of the evidence: an
observed decision somebody else made about the user's money, and a rule set
that decides whether a different decision was available.

Two rules hold, exactly as they do for the infrastructure records:

  * a record describes what was observed, never what to do about it
  * every amount is in dollars, so the meter's rate is 1.0 and the claim
    quantity is the money itself

Nothing here is medical advice or a coverage determination. These records
describe what a payer already did and what its own published rules say.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ------------------------------------------------------------------- health


NetworkStatus = Literal["in_network", "out_of_network", "unknown"]


class PayerPolicy(BaseModel):
    """The payer's own published rules, as the agent reads them back.

    This is the deterministic half of a claim appeal. The model may draft the
    argument, but whether a code is covered, whether two codes may be billed
    together, and how long the filing window runs are all lookups, not
    judgment calls.
    """

    payer_id: str
    payer_name: str = ""
    plan_id: str = ""

    covered_codes: set[str] = Field(default_factory=set)
    excluded_codes: set[str] = Field(default_factory=set)
    prior_auth_codes: set[str] = Field(default_factory=set)

    # Pairs that may not be billed together unless a modifier distinguishes
    # them. Mirrors the shape of a national correct-coding edit table.
    bundled_pairs: set[tuple[str, str]] = Field(default_factory=set)
    unbundling_modifiers: set[str] = Field(default_factory=lambda: {"59", "25", "XE", "XS", "XP", "XU"})

    # Contracted allowed amount per code, where the agent has it.
    allowed_amounts: dict[str, float] = Field(default_factory=dict)

    internal_appeal_days: int = 180
    external_review_days: int = 120
    payer_response_days: int = 30

    def covers(self, code: str) -> bool:
        if code in self.excluded_codes:
            return False
        if not self.covered_codes:
            return True
        return code in self.covered_codes

    def bundles(self, code_a: str, code_b: str) -> bool:
        return (code_a, code_b) in self.bundled_pairs or (code_b, code_a) in self.bundled_pairs


class MemberPlan(BaseModel):
    """The member's cost-sharing position at a point in time."""

    member_id: str
    plan_id: str = ""
    payer_id: str = ""
    plan_year_start: date | None = None

    deductible: float = 0.0
    deductible_met: float = 0.0
    out_of_pocket_max: float = 0.0
    out_of_pocket_met: float = 0.0
    coinsurance_rate: float = 0.2
    office_visit_copay: float = 0.0

    # Providers the member's plan actually contracted with, by identifier.
    in_network_providers: set[str] = Field(default_factory=set)

    @property
    def deductible_remaining(self) -> float:
        return max(0.0, self.deductible - self.deductible_met)

    @property
    def deductible_satisfied(self) -> bool:
        return self.deductible_remaining <= 0.0

    @property
    def out_of_pocket_remaining(self) -> float:
        if self.out_of_pocket_max <= 0:
            return float("inf")
        return max(0.0, self.out_of_pocket_max - self.out_of_pocket_met)


class ClaimLine(BaseModel):
    """One line of an explanation of benefits, as the payer adjudicated it.

    `patient_responsibility` is what the member was told they owe. The agent's
    whole job is deciding whether that number follows from the payer's own
    rules, and if it does not, by how much it is wrong.
    """

    claim_id: str
    line_id: str
    member_id: str
    payer_id: str = ""

    provider_id: str = ""
    provider_name: str = ""
    network_status: NetworkStatus = "unknown"

    service_date: datetime
    processed_date: datetime | None = None

    procedure_code: str = ""
    modifiers: list[str] = Field(default_factory=list)
    diagnosis_codes: list[str] = Field(default_factory=list)
    units: int = 1
    place_of_service: str = ""

    billed_amount: float = 0.0
    allowed_amount: float = 0.0
    plan_paid: float = 0.0
    patient_responsibility: float = 0.0

    applied_to_deductible: float = 0.0
    copay: float = 0.0
    coinsurance: float = 0.0

    denial_code: str = ""
    denial_reason: str = ""
    prior_auth_obtained: bool = False
    is_appealed: bool = False
    appeal_count: int = 0

    @property
    def is_denied(self) -> bool:
        return bool(self.denial_code) or (self.plan_paid <= 0.0 and self.billed_amount > 0.0)

    @property
    def expected_patient_share(self) -> float:
        """What the member should owe from the payer's own allowed amount."""
        return max(0.0, self.allowed_amount - self.plan_paid)

    def days_since_processed(self, now: datetime) -> float:
        ref = self.processed_date or self.service_date
        return max(0.0, (now - ref).total_seconds() / 86400.0)


# ------------------------------------------------------- recurring household


Cadence = Literal["monthly", "annual", "quarterly", "weekly"]

_CADENCE_MONTHS = {"weekly": 0.230137, "monthly": 1.0, "quarterly": 3.0, "annual": 12.0}


class RecurringCharge(BaseModel):
    """A charge that repeats until somebody stops it.

    Usage is the signal that separates a subscription somebody wants from one
    they forgot. Where a usage feed exists the agent reads it; where it does
    not, `last_used_at` stays None and the finding says so rather than
    pretending otherwise.
    """

    charge_id: str
    merchant: str
    category: str = ""
    amount: float = 0.0
    cadence: Cadence = "monthly"

    first_charged_at: datetime
    last_charged_at: datetime
    charge_count: int = 1

    last_used_at: datetime | None = None
    usage_events_30d: int = 0

    # Set when the merchant raised the price without a new agreement.
    previous_amount: float | None = None
    price_changed_at: datetime | None = None

    trial_ends_at: datetime | None = None
    cancellable: bool = True
    contract_ends_at: datetime | None = None

    # The same service billed annually, where the merchant publishes one.
    annual_equivalent_amount: float | None = None

    @property
    def monthly_amount(self) -> float:
        return self.amount / _CADENCE_MONTHS.get(self.cadence, 1.0)

    @property
    def annualized(self) -> float:
        return self.monthly_amount * 12.0

    def days_since_used(self, now: datetime) -> float:
        if self.last_used_at is None:
            return float("inf")
        return max(0.0, (now - self.last_used_at).total_seconds() / 86400.0)


class HouseholdDataset(BaseModel):
    """Everything the consumer agents read, normalized.

    Mirrors `ClusterDataset`: the agents take it whole, index into it, and
    never mutate it. `window()` exists because every agent prices against the
    observed window rather than assuming a month.
    """

    household_id: str = "household"
    as_of: datetime | None = None

    claims: list[ClaimLine] = Field(default_factory=list)
    plans: list[MemberPlan] = Field(default_factory=list)
    policies: list[PayerPolicy] = Field(default_factory=list)
    charges: list[RecurringCharge] = Field(default_factory=list)

    def plan_for(self, member_id: str) -> MemberPlan | None:
        for plan in self.plans:
            if plan.member_id == member_id:
                return plan
        return None

    def policy_for(self, payer_id: str) -> PayerPolicy | None:
        for policy in self.policies:
            if policy.payer_id == payer_id:
                return policy
        return None

    def claims_for(self, member_id: str) -> list[ClaimLine]:
        return [c for c in self.claims if c.member_id == member_id]

    def window(self) -> tuple[datetime, datetime] | None:
        stamps: list[datetime] = []
        for claim in self.claims:
            stamps.append(claim.service_date)
            if claim.processed_date:
                stamps.append(claim.processed_date)
        for charge in self.charges:
            stamps.extend([charge.first_charged_at, charge.last_charged_at])
        if not stamps:
            return None
        return min(stamps), max(stamps)

    def reference_time(self) -> datetime:
        """The 'now' the agents reason from. Explicit so runs are repeatable."""
        if self.as_of is not None:
            return self.as_of
        window = self.window()
        if window is None:
            from datetime import timezone

            return datetime.now(timezone.utc)
        return window[1]

    @property
    def has_domain_data(self) -> bool:
        return bool(self.claims or self.charges)
