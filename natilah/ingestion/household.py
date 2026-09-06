"""Read-only ingestion for the consumer domains.

Two sources, same normalized output. `load_household_json` reads an export the
user already has, which is how a real household starts: a claims download from
a payer portal and a transaction export from a bank. `generate_household` makes
a synthetic household so the consumer agents can be exercised end to end
without anybody's medical records.

Nothing here contacts a payer, a bank, or a merchant. Ingestion is a file read.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from natilah.models.consumer import (
    ClaimLine,
    HouseholdDataset,
    MemberPlan,
    PayerPolicy,
    RecurringCharge,
)


def _dt(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------- JSON


def load_household_json(path: str | Path) -> HouseholdDataset:
    """Load a household export. Unknown fields are ignored, not guessed at."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_household(raw)


def parse_household(raw: dict) -> HouseholdDataset:
    policies = []
    for p in raw.get("policies", []):
        policies.append(
            PayerPolicy(
                payer_id=p["payer_id"],
                payer_name=p.get("payer_name", ""),
                plan_id=p.get("plan_id", ""),
                covered_codes=set(p.get("covered_codes", [])),
                excluded_codes=set(p.get("excluded_codes", [])),
                prior_auth_codes=set(p.get("prior_auth_codes", [])),
                bundled_pairs={tuple(pair) for pair in p.get("bundled_pairs", [])},
                allowed_amounts=dict(p.get("allowed_amounts", {})),
                internal_appeal_days=int(p.get("internal_appeal_days", 180)),
                external_review_days=int(p.get("external_review_days", 120)),
            )
        )

    plans = []
    for m in raw.get("plans", []):
        plans.append(
            MemberPlan(
                member_id=m["member_id"],
                plan_id=m.get("plan_id", ""),
                payer_id=m.get("payer_id", ""),
                deductible=float(m.get("deductible", 0.0)),
                deductible_met=float(m.get("deductible_met", 0.0)),
                out_of_pocket_max=float(m.get("out_of_pocket_max", 0.0)),
                out_of_pocket_met=float(m.get("out_of_pocket_met", 0.0)),
                coinsurance_rate=float(m.get("coinsurance_rate", 0.2)),
                in_network_providers=set(m.get("in_network_providers", [])),
            )
        )

    claims = []
    for c in raw.get("claims", []):
        claims.append(
            ClaimLine(
                claim_id=c["claim_id"],
                line_id=str(c.get("line_id", "1")),
                member_id=c["member_id"],
                payer_id=c.get("payer_id", ""),
                provider_id=c.get("provider_id", ""),
                provider_name=c.get("provider_name", ""),
                network_status=c.get("network_status", "unknown"),
                service_date=_dt(c["service_date"]),
                processed_date=_dt(c.get("processed_date")),
                procedure_code=c.get("procedure_code", ""),
                modifiers=list(c.get("modifiers", [])),
                diagnosis_codes=list(c.get("diagnosis_codes", [])),
                units=int(c.get("units", 1)),
                billed_amount=float(c.get("billed_amount", 0.0)),
                allowed_amount=float(c.get("allowed_amount", 0.0)),
                plan_paid=float(c.get("plan_paid", 0.0)),
                patient_responsibility=float(c.get("patient_responsibility", 0.0)),
                applied_to_deductible=float(c.get("applied_to_deductible", 0.0)),
                copay=float(c.get("copay", 0.0)),
                coinsurance=float(c.get("coinsurance", 0.0)),
                denial_code=c.get("denial_code", ""),
                denial_reason=c.get("denial_reason", ""),
                prior_auth_obtained=bool(c.get("prior_auth_obtained", False)),
                is_appealed=bool(c.get("is_appealed", False)),
                appeal_count=int(c.get("appeal_count", 0)),
            )
        )

    charges = []
    for ch in raw.get("charges", []):
        charges.append(
            RecurringCharge(
                charge_id=ch["charge_id"],
                merchant=ch["merchant"],
                category=ch.get("category", ""),
                amount=float(ch.get("amount", 0.0)),
                cadence=ch.get("cadence", "monthly"),
                first_charged_at=_dt(ch["first_charged_at"]),
                last_charged_at=_dt(ch["last_charged_at"]),
                charge_count=int(ch.get("charge_count", 1)),
                last_used_at=_dt(ch.get("last_used_at")),
                usage_events_30d=int(ch.get("usage_events_30d", 0)),
                previous_amount=(
                    float(ch["previous_amount"]) if ch.get("previous_amount") else None
                ),
                price_changed_at=_dt(ch.get("price_changed_at")),
                trial_ends_at=_dt(ch.get("trial_ends_at")),
                cancellable=bool(ch.get("cancellable", True)),
                contract_ends_at=_dt(ch.get("contract_ends_at")),
                annual_equivalent_amount=(
                    float(ch["annual_equivalent_amount"])
                    if ch.get("annual_equivalent_amount")
                    else None
                ),
            )
        )

    return HouseholdDataset(
        household_id=raw.get("household_id", "household"),
        as_of=_dt(raw.get("as_of")),
        claims=claims,
        plans=plans,
        policies=policies,
        charges=charges,
    )


# -------------------------------------------------------------- synthetic


_CODES = ["99213", "99214", "70450", "80053", "93000", "20610", "36415", "97110"]
_ALLOWED = {
    "99213": 118.0,
    "99214": 172.0,
    "70450": 340.0,
    "80053": 46.0,
    "93000": 62.0,
    "20610": 96.0,
    "36415": 14.0,
    "97110": 88.0,
}
_MERCHANTS = [
    ("Streamly", "music_streaming", 11.99),
    ("Tunebox", "music_streaming", 9.99),
    ("VaultPass", "password_manager", 4.99),
    ("KeyRing", "password_manager", 3.99),
    ("CloudBin", "cloud_storage", 9.99),
    ("FitTrack", "fitness_app", 14.99),
    ("NewsDaily", "news", 8.00),
    ("MealPlan", "food", 12.50),
    ("ShieldVPN", "vpn", 6.99),
]


def generate_household(
    days: int = 120,
    claim_count: int = 40,
    seed: int = 7,
    as_of: datetime | None = None,
) -> HouseholdDataset:
    """A synthetic household with realistic adjudication errors seeded in.

    The error rates are deliberately in the same range the public data shows
    for marketplace plans, so a demo run produces a plausible number rather
    than a flattering one.
    """
    rng = random.Random(seed)
    now = as_of or datetime(2026, 9, 1, tzinfo=timezone.utc)
    start = now - timedelta(days=days)

    policy = PayerPolicy(
        payer_id="payer_001",
        payer_name="Meridian Health",
        plan_id="plan_ppo_2026",
        covered_codes=set(_CODES),
        excluded_codes={"99499"},
        prior_auth_codes={"70450"},
        bundled_pairs={("99213", "36415"), ("20610", "97110")},
        allowed_amounts=dict(_ALLOWED),
        internal_appeal_days=180,
        external_review_days=120,
    )
    plan = MemberPlan(
        member_id="member_001",
        plan_id="plan_ppo_2026",
        payer_id="payer_001",
        deductible=1500.0,
        deductible_met=1500.0,  # already satisfied, so misapplied charges show
        out_of_pocket_max=6000.0,
        out_of_pocket_met=2100.0,
        coinsurance_rate=0.2,
        in_network_providers={"prov_a", "prov_b"},
    )

    claims: list[ClaimLine] = []
    for i in range(claim_count):
        code = rng.choice(_CODES)
        allowed = _ALLOWED[code]
        billed = round(allowed * rng.uniform(1.6, 3.2), 2)
        service = start + timedelta(days=rng.randint(0, max(days - 20, 1)))
        processed = service + timedelta(days=rng.randint(5, 20))
        provider = rng.choice(["prov_a", "prov_b"])
        line = ClaimLine(
            claim_id=f"CLM{1000 + i}",
            line_id="1",
            member_id="member_001",
            payer_id="payer_001",
            provider_id=provider,
            provider_name={"prov_a": "Northside Clinic", "prov_b": "Harbor Imaging"}[provider],
            network_status="in_network",
            service_date=service,
            processed_date=processed,
            procedure_code=code,
            billed_amount=billed,
            allowed_amount=allowed,
            plan_paid=round(allowed * 0.8, 2),
            patient_responsibility=round(allowed * 0.2, 2),
            coinsurance=round(allowed * 0.2, 2),
        )

        roll = rng.random()
        # ~19% denial rate, matching published marketplace figures.
        if roll < 0.19:
            line.plan_paid = 0.0
            line.patient_responsibility = billed
            line.denial_code = rng.choice(["CO-197", "CO-50", "CO-16", "CO-97"])
            line.denial_reason = "Service not covered as billed"
            if code == "70450":
                line.prior_auth_obtained = rng.random() < 0.5
        elif roll < 0.25:
            # Balance bill: charged above the contracted ceiling.
            line.patient_responsibility = round(billed - line.plan_paid, 2)
        elif roll < 0.30:
            # Deductible applied though the deductible was already met.
            line.applied_to_deductible = round(allowed * 0.6, 2)
            line.patient_responsibility = round(allowed * 0.6, 2)
        claims.append(line)

    # A duplicate submission and an unbundled pair, so those detectors have
    # something real to find.
    if claims:
        dup = claims[0].model_copy(deep=True)
        dup.claim_id = "CLM9001"
        dup.processed_date = (dup.processed_date or now) + timedelta(days=3)
        claims.append(dup)

        base = claims[1]
        pair = base.model_copy(deep=True)
        pair.claim_id = "CLM9002"
        pair.procedure_code = "36415"
        pair.allowed_amount = _ALLOWED["36415"]
        pair.billed_amount = 40.0
        pair.plan_paid = 0.0
        pair.patient_responsibility = 40.0
        pair.modifiers = []
        base.procedure_code = "99213"
        base.allowed_amount = _ALLOWED["99213"]
        claims.append(pair)

    charges: list[RecurringCharge] = []
    for idx, (merchant, category, price) in enumerate(_MERCHANTS):
        first = start - timedelta(days=rng.randint(60, 400))
        charge = RecurringCharge(
            charge_id=f"chg_{idx:03d}",
            merchant=merchant,
            category=category,
            amount=price,
            cadence="monthly",
            first_charged_at=first,
            last_charged_at=now - timedelta(days=rng.randint(1, 25)),
            charge_count=max(2, int((now - first).days / 30)),
            usage_events_30d=rng.choice([0, 0, 0, 3, 11]),
        )
        if charge.usage_events_30d:
            charge.last_used_at = now - timedelta(days=rng.randint(1, 20))
        else:
            charge.last_used_at = now - timedelta(days=rng.randint(70, 260))
        charges.append(charge)

    # Seeded, specific conditions the agent should find.
    charges[5].previous_amount = 9.99          # FitTrack raised its price
    charges[5].price_changed_at = now - timedelta(days=40)
    charges[6].trial_ends_at = now + timedelta(days=6)   # NewsDaily trial converts
    charges[6].usage_events_30d = 0
    charges[7].annual_equivalent_amount = 99.0          # MealPlan cheaper annually
    charges[7].usage_events_30d = 9
    charges[7].last_used_at = now - timedelta(days=2)
    charges[8].contract_ends_at = now + timedelta(days=120)  # ShieldVPN locked in

    return HouseholdDataset(
        household_id="household_demo",
        as_of=now,
        claims=claims,
        plans=[plan],
        policies=[policy],
        charges=charges,
    )
