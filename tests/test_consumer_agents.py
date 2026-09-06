"""The consumer fleet: same output contract, dollar meters, no cluster."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from natilah.agents.claim_recovery_agent import ClaimRecoveryAgent
from natilah.agents.coordinator import AgentCoordinator, default_household_agents
from natilah.agents.recurring_spend_agent import RecurringSpendAgent
from natilah.ingestion.household import generate_household, parse_household
from natilah.models.consumer import (
    ClaimLine,
    HouseholdDataset,
    MemberPlan,
    PayerPolicy,
    RecurringCharge,
)
from natilah.models.enums import CandidateOutcome, Meter, OpportunityType

NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _policy(**overrides) -> PayerPolicy:
    base = dict(
        payer_id="payer_001",
        covered_codes={"99213", "70450", "36415"},
        excluded_codes={"99499"},
        prior_auth_codes={"70450"},
        bundled_pairs={("99213", "36415")},
        allowed_amounts={"99213": 118.0, "70450": 340.0, "36415": 14.0},
        internal_appeal_days=180,
    )
    base.update(overrides)
    return PayerPolicy(**base)


def _plan(**overrides) -> MemberPlan:
    base = dict(
        member_id="member_001",
        payer_id="payer_001",
        deductible=1500.0,
        deductible_met=1500.0,
        out_of_pocket_max=6000.0,
        out_of_pocket_met=2000.0,
        coinsurance_rate=0.2,
    )
    base.update(overrides)
    return MemberPlan(**base)


def _line(**overrides) -> ClaimLine:
    base = dict(
        claim_id="CLM1",
        line_id="1",
        member_id="member_001",
        payer_id="payer_001",
        provider_id="prov_a",
        network_status="in_network",
        service_date=NOW - timedelta(days=40),
        processed_date=NOW - timedelta(days=30),
        procedure_code="99213",
        billed_amount=300.0,
        allowed_amount=118.0,
        plan_paid=0.0,
        patient_responsibility=300.0,
        denial_code="CO-197",
    )
    base.update(overrides)
    return ClaimLine(**base)


def _household(claims=None, charges=None) -> HouseholdDataset:
    return HouseholdDataset(
        as_of=NOW,
        claims=claims or [],
        charges=charges or [],
        plans=[_plan()],
        policies=[_policy()],
    )


# ------------------------------------------------------------ claim recovery


def test_denial_on_a_covered_code_is_recoverable():
    agent = ClaimRecoveryAgent()
    findings = agent.analyze_dataset(_household(claims=[_line()]))

    assert findings, "a denial on a covered code should produce a finding"
    finding = findings[0]
    assert finding.claim.primary_meter is Meter.CLAIM_DOLLARS
    # The member owes coinsurance on the allowed amount, not the billed amount.
    assert finding.claim.primary_quantity == pytest.approx(300.0 - 118.0 * 0.2, abs=0.01)
    assert finding.value.one_time_value > 0
    assert finding.value.is_recurring is False


def test_denial_on_an_excluded_code_is_not_a_finding():
    """A correctly denied service is not an opportunity."""
    agent = ClaimRecoveryAgent()
    line = _line(procedure_code="99499")
    assert agent.analyze_dataset(_household(claims=[line])) == []


def test_closed_filing_window_rejects_every_candidate():
    agent = ClaimRecoveryAgent()
    stale = _line(
        service_date=NOW - timedelta(days=400),
        processed_date=NOW - timedelta(days=380),
    )
    dataset = _household(claims=[stale])

    assert agent.analyze_dataset(dataset) == []

    # The rejection is recorded with its reason rather than silently dropped.
    observations = agent.detect(dataset)
    assert observations
    candidates = agent.generate_candidates(dataset, observations[0])
    checked, violations = agent.validate_candidate(dataset, observations[0], candidates[0])
    assert "filing_window_open" in checked
    assert any("window closed" in v.lower() for v in violations)


def test_missing_prior_authorization_blocks_a_coverage_appeal():
    agent = ClaimRecoveryAgent()
    line = _line(procedure_code="70450", allowed_amount=340.0, prior_auth_obtained=False)
    dataset = _household(claims=[line])
    observations = [o for o in agent.detect(dataset) if o.signal_type is OpportunityType.CLAIM_DENIED]
    assert observations

    candidates = agent.generate_candidates(dataset, observations[0])
    appeal = next(c for c in candidates if c.proposed_action["kind"] == "internal_appeal")
    _, violations = agent.validate_candidate(dataset, observations[0], appeal)
    assert any("prior authorization" in v.lower() for v in violations)


def test_a_member_can_never_be_credited_more_than_they_were_billed():
    agent = ClaimRecoveryAgent()
    line = _line(patient_responsibility=50.0, billed_amount=300.0)
    dataset = _household(claims=[line])
    for finding in agent.analyze_dataset(dataset):
        assert finding.claim.primary_quantity <= 50.0 + 0.01


def test_duplicate_line_is_detected_and_fully_recoverable():
    agent = ClaimRecoveryAgent()
    first = _line(claim_id="CLM1", denial_code="", plan_paid=94.4, patient_responsibility=23.6)
    dup = first.model_copy(deep=True)
    dup.claim_id = "CLM2"
    dup.patient_responsibility = 23.6
    dup.processed_date = NOW - timedelta(days=25)

    observations = agent.detect(_household(claims=[first, dup]))
    duplicates = [o for o in observations if o.signal_type is OpportunityType.DUPLICATE_CHARGE]
    assert len(duplicates) == 1
    assert duplicates[0].resource_id.startswith("CLM2")


def test_bundled_pair_without_a_modifier_is_a_finding_and_with_one_is_not():
    agent = ClaimRecoveryAgent()
    visit = _line(claim_id="CLM1", procedure_code="99213", denial_code="", plan_paid=94.4,
                  patient_responsibility=23.6)
    draw = _line(claim_id="CLM2", procedure_code="36415", denial_code="", allowed_amount=14.0,
                 plan_paid=0.0, patient_responsibility=40.0)

    flagged = agent.detect(_household(claims=[visit, draw]))
    assert any(o.signal_type is OpportunityType.IMPROPER_BUNDLING for o in flagged)

    # A distinguishing modifier is the payer's own mechanism for allowing the
    # split, so the same pair is then correctly billed.
    draw_with_modifier = draw.model_copy(deep=True)
    draw_with_modifier.modifiers = ["59"]
    cleared = agent.detect(_household(claims=[visit, draw_with_modifier]))
    assert not any(o.signal_type is OpportunityType.IMPROPER_BUNDLING for o in cleared)


def test_balance_bill_above_the_contract_ceiling():
    agent = ClaimRecoveryAgent()
    line = _line(denial_code="", allowed_amount=118.0, plan_paid=94.4,
                 patient_responsibility=205.6)
    observations = agent.detect(_household(claims=[line]))
    balance = [o for o in observations if o.signal_type is OpportunityType.BALANCE_BILL]
    assert balance
    assert balance[0].evidence["excess"] == pytest.approx(205.6 - 23.6, abs=0.01)


def test_deductible_applied_after_it_was_met():
    agent = ClaimRecoveryAgent()
    line = _line(denial_code="", plan_paid=0.0, allowed_amount=118.0,
                 applied_to_deductible=118.0, patient_responsibility=118.0)
    observations = agent.detect(_household(claims=[line]))
    assert any(o.signal_type is OpportunityType.DEDUCTIBLE_MISAPPLIED for o in observations)


# ----------------------------------------------------------- recurring spend


def _charge(**overrides) -> RecurringCharge:
    base = dict(
        charge_id="chg_1",
        merchant="Streamly",
        category="music_streaming",
        amount=11.99,
        cadence="monthly",
        first_charged_at=NOW - timedelta(days=400),
        last_charged_at=NOW - timedelta(days=5),
        charge_count=13,
        last_used_at=NOW - timedelta(days=200),
        usage_events_30d=0,
    )
    base.update(overrides)
    return RecurringCharge(**base)


def test_recurring_claim_is_not_normalized_by_the_observation_window():
    """A $11.99/month charge is $11.99/month over any window length."""
    agent = RecurringSpendAgent()
    findings = agent.analyze_dataset(_household(charges=[_charge()]))
    assert findings
    cancel = max(findings, key=lambda f: f.value.estimated_monthly_value)
    assert cancel.value.estimated_monthly_value == pytest.approx(11.99, abs=0.01)
    assert cancel.value.estimated_annual_value == pytest.approx(11.99 * 12, abs=0.1)
    assert cancel.value.one_time_value == 0.0
    assert cancel.value.is_recurring is True


def test_a_service_in_active_use_is_not_cancelled():
    agent = RecurringSpendAgent()
    active = _charge(usage_events_30d=14, last_used_at=NOW - timedelta(days=1))
    assert agent.analyze_dataset(_household(charges=[active])) == []


def test_contract_term_blocks_cancellation_with_a_stated_reason():
    agent = RecurringSpendAgent()
    locked = _charge(contract_ends_at=NOW + timedelta(days=90))
    dataset = _household(charges=[locked])
    observations = agent.detect(dataset)
    assert observations
    candidate = agent.generate_candidates(dataset, observations[0])[0]
    checked, violations = agent.validate_candidate(dataset, observations[0], candidate)
    assert "no_active_contract_term" in checked
    assert any("contract term" in v.lower() for v in violations)


def test_missing_usage_feed_lowers_confidence_rather_than_assuming_disuse():
    agent = RecurringSpendAgent()
    blind = _charge(last_used_at=None, usage_events_30d=0)
    findings = agent.analyze_dataset(_household(charges=[blind]))
    assert findings
    finding = findings[0]
    assert finding.confidence.score < 0.8
    assert any("telemetry" in u.lower() or "incomplete" in u.lower()
               for u in finding.confidence.uncertainty_sources)


def test_price_hike_claims_only_the_increase():
    agent = RecurringSpendAgent()
    hiked = _charge(amount=14.99, previous_amount=9.99, usage_events_30d=5,
                    last_used_at=NOW - timedelta(days=2))
    dataset = _household(charges=[hiked])
    observations = [o for o in agent.detect(dataset)
                    if o.signal_type is OpportunityType.SILENT_PRICE_HIKE]
    assert observations
    negotiate = next(
        c for c in agent.generate_candidates(dataset, observations[0])
        if c.proposed_action["kind"] == "negotiate"
    )
    assert negotiate.claim.primary_quantity == pytest.approx(5.0, abs=0.01)


# ------------------------------------------------------------ fleet contract


def test_the_two_consumer_meters_never_mix():
    """A recovered claim dollar and a cancelled subscription are not one dollar."""
    dataset = generate_household(seed=11)
    findings, report = AgentCoordinator(agents=default_household_agents()).analyze_dataset(dataset)
    assert findings

    meters = {f.claim.primary_meter for f in findings}
    assert meters <= {Meter.CLAIM_DOLLARS, Meter.RECURRING_DOLLARS}

    one_time = sum(f.value.one_time_value for f in findings)
    recurring = sum(
        f.value.estimated_monthly_value for f in findings
        if f.claim.primary_meter is Meter.RECURRING_DOLLARS
    )
    assert one_time > 0 and recurring > 0
    # Reported separately; never added into a single headline number.
    assert report.claimed_by_meter.keys() <= {m.value for m in Meter}


def test_consumer_findings_carry_the_same_structured_contract():
    dataset = generate_household(seed=5)
    for agent in default_household_agents():
        findings = agent.analyze_dataset(dataset)
        assert findings, f"{agent.name} found nothing on the synthetic household"
        for finding in findings:
            assert finding.agent_name == agent.name
            assert finding.objective is agent.objective
            assert finding.recommended_action
            assert finding.claim.basis
            assert finding.confidence.constraints_checked
            assert finding.candidates_considered, "rejected alternatives must be kept"
            assert any(
                c.outcome is CandidateOutcome.SELECTED for c in finding.candidates_considered
            )
            assert finding.value.assumptions


def test_coordinator_reports_when_a_household_has_nothing_to_find():
    findings, report = AgentCoordinator(agents=default_household_agents()).analyze_dataset(
        HouseholdDataset(as_of=NOW)
    )
    assert findings == []
    assert any("no claims" in note.lower() for note in report.notes)


def test_household_json_round_trips():
    raw = {
        "household_id": "h1",
        "as_of": "2026-09-01T00:00:00+00:00",
        "policies": [{"payer_id": "payer_001", "covered_codes": ["99213"],
                      "bundled_pairs": [["99213", "36415"]]}],
        "plans": [{"member_id": "member_001", "deductible": 1500.0, "deductible_met": 1500.0}],
        "claims": [{"claim_id": "CLM1", "line_id": "1", "member_id": "member_001",
                    "payer_id": "payer_001", "service_date": "2026-07-01T00:00:00+00:00",
                    "procedure_code": "99213", "billed_amount": 300.0,
                    "patient_responsibility": 300.0, "denial_code": "CO-197"}],
        "charges": [{"charge_id": "c1", "merchant": "Streamly", "amount": 11.99,
                     "first_charged_at": "2025-01-01T00:00:00+00:00",
                     "last_charged_at": "2026-08-20T00:00:00+00:00"}],
    }
    dataset = parse_household(raw)
    assert dataset.claims[0].denial_code == "CO-197"
    assert dataset.policies[0].bundles("99213", "36415")
    assert dataset.plans[0].deductible_satisfied
    assert dataset.charges[0].monthly_amount == pytest.approx(11.99)
