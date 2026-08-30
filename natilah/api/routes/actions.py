"""Ranked infrastructure actions: the product surface of the agent layer.

Every item here is one validated counterfactual an engineer can act on, with
the value it is credited with after deduplication across agents. Approval is
recorded, never executed: Natilah stays read-only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from natilah.agents.coordinator import default_agents
from natilah.api.schemas import (
    ActionDetail,
    ActionListItem,
    ActionStatusUpdate,
    AgentInfo,
)
from natilah.config import settings
from natilah.models.database import (
    get_db_session,
    load_finding,
    load_ranked_findings,
    set_finding_status,
)
from natilah.models.domain import Finding
from natilah.models.enums import ActionStatus

router = APIRouter(prefix="/api", tags=["actions"])


def _to_item(finding: Finding) -> ActionListItem:
    attribution = finding.attribution
    return ActionListItem(
        rank=attribution.rank,
        opportunity_id=finding.opportunity_id,
        agent_name=finding.agent_name,
        objective=finding.objective.value if finding.objective else None,
        opportunity_type=finding.opportunity_type.value,
        title=finding.title,
        recommended_action=finding.recommended_action,
        what_happened=finding.description,
        alternative=finding.alternative.description,
        gpu_hours_recovered=attribution.attributed_gpu_hours,
        queue_hours_recovered=attribution.attributed_queue_seconds / 3600.0,
        monthly_value=attribution.attributed_monthly_value,
        annual_value=attribution.attributed_annual_value,
        claimed_monthly_value=finding.value.estimated_monthly_value,
        confidence_level=finding.confidence.level.value,
        confidence_score=finding.confidence.score,
        resolution=attribution.resolution.value,
        status=finding.status.value,
        affected_job_ids=finding.affected_job_ids,
        affected_gpu_ids=finding.affected_gpu_ids[:32],
    )


@router.get("/actions", response_model=list[ActionListItem])
async def top_actions(
    limit: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> list[ActionListItem]:
    findings = await load_ranked_findings(session, limit=limit)
    return [_to_item(f) for f in findings]


@router.get("/actions/{opportunity_id}", response_model=ActionDetail)
async def action_detail(
    opportunity_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ActionDetail:
    finding = await load_finding(session, opportunity_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Action not found")
    item = _to_item(finding)
    return ActionDetail(
        **item.model_dump(),
        claim=finding.claim.model_dump(mode="json"),
        attribution=finding.attribution.model_dump(mode="json"),
        candidates_considered=[c.model_dump(mode="json") for c in finding.candidates_considered],
        constraints_checked=finding.confidence.constraints_checked,
        impact=finding.comparison.model_dump(mode="json"),
        value=finding.value.model_dump(mode="json"),
        confidence=finding.confidence.model_dump(mode="json"),
        evidence=finding.evidence,
        utilization_series=[p.model_dump(mode="json") for p in finding.utilization_series],
    )


@router.post("/actions/{opportunity_id}/status", response_model=ActionListItem)
async def update_action_status(
    opportunity_id: str,
    body: ActionStatusUpdate,
    session: AsyncSession = Depends(get_db_session),
) -> ActionListItem:
    """Record a human decision. Approval means an engineer will act, not Natilah."""
    try:
        status = ActionStatus(body.status)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of {[s.value for s in ActionStatus]}",
        ) from exc
    row = await set_finding_status(session, opportunity_id, status.value)
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found")
    finding = await load_finding(session, opportunity_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return _to_item(finding)


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents() -> list[AgentInfo]:
    return [
        AgentInfo(
            name=agent.name,
            objective=agent.objective.value,
            signals=[s.value for s in agent.signal_types],
            finding_title=agent.finding_title,
            llm_enabled=agent.use_llm(),
        )
        for agent in default_agents()
    ]


@router.get("/agents/mode")
async def agent_mode() -> dict[str, object]:
    return {
        "agent_mode": settings.agent_mode,
        "llm_model": settings.xai_model,
        "llm_configured": bool(settings.xai_api_key),
        "safety_mode": settings.safety_mode,
        "execution": "human_approved_only",
    }
