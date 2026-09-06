"""Consumer-side API: run the household fleet over a household's own export.

Stateless on purpose. A household posts an export, gets back a ranked list of
actions, and nothing is stored. Medical claim lines are the most sensitive data
this system will ever touch, and the safest place to keep them is nowhere.

Same guarantees as the cluster side: read-only, deduplicated by meter, ranked by
expected value, every rejected alternative kept with its reason. Nothing is
filed, cancelled, or submitted. The response is a recommendation.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from natilah.agents.coordinator import AgentCoordinator, default_household_agents
from natilah.ingestion.household import generate_household, parse_household
from natilah.models.consumer import HouseholdDataset
from natilah.models.domain import Finding
from natilah.models.enums import Meter, Resolution
from natilah.safety.guards import Action, SafetyGuard

router = APIRouter(prefix="/api/household", tags=["household"])


class HouseholdActionItem(BaseModel):
    """One recommended action, with everything needed to check it."""

    action_id: str
    rank: int | None
    agent: str
    objective: str
    signal: str
    meter: str
    title: str
    what_happened: str
    recommended_action: str
    # Money, split by how it actually arrives.
    one_time_value: float
    monthly_value: float
    annual_value: float
    confidence: float
    confidence_raw: float | None
    confidence_calibrated: bool
    deadline_note: str = ""
    constraints_checked: list[str] = Field(default_factory=list)
    alternatives_considered: int = 0
    alternatives_rejected: list[dict] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)


class HouseholdTotals(BaseModel):
    """Totals kept apart by meter, because they are not the same kind of money."""

    one_time_recoverable: float = 0.0
    recurring_monthly: float = 0.0
    recurring_annual: float = 0.0
    claimed_one_time: float = 0.0
    claimed_recurring_monthly: float = 0.0
    deduplicated_note: str = ""


class HouseholdAnalysisResponse(BaseModel):
    household_id: str
    actions: list[HouseholdActionItem]
    totals: HouseholdTotals
    findings_total: int
    findings_ranked: int
    findings_suppressed: int
    conflicts_resolved: int
    selection_gain_monthly_value: float
    notes: list[str] = Field(default_factory=list)
    execution: str = "recommendation_only"


def _deadline_note(finding: Finding) -> str:
    """Surface the clock, because in this domain the clock is the whole risk."""
    evidence = finding.evidence.get("detector_evidence", {}) or {}
    days = evidence.get("filing_days_remaining")
    if isinstance(days, (int, float)):
        return f"{days:.0f} days left to file."
    trial = evidence.get("days_remaining")
    if isinstance(trial, (int, float)):
        return f"Converts to a paid charge in {trial:.0f} days."
    return ""


def _to_item(finding: Finding) -> HouseholdActionItem:
    return HouseholdActionItem(
        action_id=finding.opportunity_id,
        rank=finding.attribution.rank,
        agent=finding.agent_name,
        objective=finding.objective.value if finding.objective else "",
        signal=finding.opportunity_type.value,
        meter=finding.claim.primary_meter.value,
        title=finding.title,
        what_happened=finding.description,
        recommended_action=finding.recommended_action,
        one_time_value=round(finding.value.one_time_value, 2),
        monthly_value=round(finding.attribution.attributed_monthly_value, 2),
        annual_value=round(finding.attribution.attributed_annual_value, 2),
        confidence=finding.confidence.score,
        confidence_raw=finding.confidence.raw_score,
        confidence_calibrated=finding.confidence.calibrated,
        deadline_note=_deadline_note(finding),
        constraints_checked=finding.confidence.constraints_checked,
        alternatives_considered=len(finding.candidates_considered),
        alternatives_rejected=[
            {
                "description": c.description,
                "reason": c.rejection_reason,
                "violations": c.violations,
            }
            for c in finding.candidates_considered
            if c.rejection_reason
        ],
        evidence=finding.evidence.get("detector_evidence", {}) or {},
    )


def analyze_household(dataset: HouseholdDataset, top_n: int = 25) -> HouseholdAnalysisResponse:
    """Run the consumer fleet and shape the result for a person, not a cluster."""
    SafetyGuard().check_action(Action(name="analyze_household", is_read_only=True))
    coordinator = AgentCoordinator(agents=default_household_agents(), top_n=top_n)
    findings, report = coordinator.analyze_dataset(dataset)

    ranked = [
        f
        for f in findings
        if f.attribution.resolution in {Resolution.UNIQUE, Resolution.DEDUPLICATED}
    ]
    ranked.sort(key=lambda f: f.attribution.rank or 10**6)

    totals = HouseholdTotals()
    for finding in ranked:
        if finding.claim.primary_meter is Meter.RECURRING_DOLLARS:
            totals.recurring_monthly += finding.attribution.attributed_monthly_value
        else:
            totals.one_time_recoverable += finding.value.one_time_value
    for finding in findings:
        if finding.claim.primary_meter is Meter.RECURRING_DOLLARS:
            totals.claimed_recurring_monthly += finding.value.estimated_monthly_value
        else:
            totals.claimed_one_time += finding.value.one_time_value

    totals.recurring_annual = totals.recurring_monthly * 12.0
    totals.one_time_recoverable = round(totals.one_time_recoverable, 2)
    totals.recurring_monthly = round(totals.recurring_monthly, 2)
    totals.recurring_annual = round(totals.recurring_annual, 2)
    totals.claimed_one_time = round(totals.claimed_one_time, 2)
    totals.claimed_recurring_monthly = round(totals.claimed_recurring_monthly, 2)
    totals.deduplicated_note = (
        "One-time recoveries and recurring savings are different kinds of money and are "
        "never added together. Claimed is what the agents proposed; the headline figures "
        "are what survived deduplication and conflict selection."
    )

    return HouseholdAnalysisResponse(
        household_id=dataset.household_id,
        actions=[_to_item(f) for f in ranked[:top_n]],
        totals=totals,
        findings_total=report.total_findings,
        findings_ranked=report.ranked_findings,
        findings_suppressed=report.suppressed_findings,
        conflicts_resolved=report.conflicts_resolved,
        selection_gain_monthly_value=report.selection_gain_monthly_value,
        notes=report.notes,
    )


@router.post("/analyze", response_model=HouseholdAnalysisResponse)
async def analyze_uploaded_household(file: UploadFile = File(...)):
    """Analyze a household export. The file is read, used, and discarded."""
    try:
        import json

        raw = json.loads((await file.read()).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read the export: {exc}") from exc
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Export must be a JSON object.")
    try:
        dataset = parse_household(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Export did not match the expected shape: {exc}"
        ) from exc
    if not dataset.has_domain_data:
        raise HTTPException(status_code=422, detail="Export contained no claims or charges.")
    return analyze_household(dataset)


@router.get("/demo", response_model=HouseholdAnalysisResponse)
async def analyze_demo_household(seed: int = 7, days: int = 120):
    """A synthetic household, so the consumer fleet can be seen working."""
    return analyze_household(generate_household(days=days, seed=seed))
