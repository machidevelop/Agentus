from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from natilah.api.schemas import OpportunityDetail, OpportunityListItem
from natilah.models.database import OpportunityModel, get_db_session, load_finding, load_findings

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityListItem])
async def list_opportunities(session: AsyncSession = Depends(get_db_session)) -> list[OpportunityListItem]:
    rows = (
        (await session.execute(select(OpportunityModel).order_by(OpportunityModel.monthly_value.desc())))
        .scalars()
        .all()
    )
    return [
        OpportunityListItem(
            opportunity_id=r.opportunity_id,
            opportunity_type=r.opportunity_type,
            title=r.title,
            description=r.description,
            monthly_value=r.monthly_value,
            annual_value=r.annual_value,
            confidence_level=(r.confidence or {}).get("level", "medium"),
            confidence_score=float((r.confidence or {}).get("score") or 0.0),
            severity=r.severity,
            affected_job_ids=r.affected_job_ids or [],
        )
        for r in rows
    ]


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
async def get_opportunity(
    opportunity_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> OpportunityDetail:
    finding = await load_finding(session, opportunity_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return OpportunityDetail(
        opportunity_id=finding.opportunity_id,
        opportunity_type=finding.opportunity_type.value,
        title=finding.title,
        what_happened=finding.description,
        alternative={
            "description": finding.alternative.description,
            "proposed_action": finding.alternative.proposed_action,
            "rationale": finding.alternative.agent_rationale,
            "generation_method": finding.alternative.generation_method,
            "agent_name": finding.alternative.agent_name,
            "tools_invoked": finding.alternative.tools_invoked,
            "constraints_satisfied": finding.alternative.constraints_satisfied,
        },
        impact=finding.comparison.model_dump(mode="json"),
        value=finding.value.model_dump(mode="json"),
        confidence=finding.confidence.model_dump(mode="json"),
        utilization_series=[p.model_dump(mode="json") for p in finding.utilization_series],
        detected_at=finding.detected_at,
        affected_job_ids=finding.affected_job_ids,
        affected_gpu_ids=finding.affected_gpu_ids,
        decision=finding.decision.model_dump(mode="json"),
    )
