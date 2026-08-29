from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from natilah.api.schemas import CostConfigSchema, DashboardSummary
from natilah.config import DEFAULT_GPU_COSTS, settings
from natilah.models.database import (
    CostConfigModel,
    GPUModel,
    OpportunityModel,
    SchedulerDecisionModel,
    get_db_session,
    upsert_cost_config,
)

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(session: AsyncSession = Depends(get_db_session)) -> DashboardSummary:
    gpus = (await session.execute(select(func.count()).select_from(GPUModel))).scalar_one()
    decisions = (await session.execute(select(func.count()).select_from(SchedulerDecisionModel))).scalar_one()
    opps = (await session.execute(select(OpportunityModel))).scalars().all()
    monthly = sum(o.monthly_value for o in opps)
    annual = sum(o.annual_value for o in opps)
    hours = sum(float((o.value or {}).get("gpu_hours_recovered") or 0.0) for o in opps)
    equiv = sum(float((o.value or {}).get("equivalent_gpus_recovered") or 0.0) for o in opps)
    return DashboardSummary(
        gpus_analyzed=int(gpus or 0),
        decisions_analyzed=int(decisions or 0),
        opportunities_found=len(opps),
        gpu_hours_recovered=hours,
        equivalent_gpus=equiv,
        monthly_value=monthly,
        annual_value=annual,
        production_changes=0,
        analysis_status="ready" if opps else "idle",
        safety_mode=settings.safety_mode,
    )


@router.get("/config/costs", response_model=CostConfigSchema)
async def get_costs(session: AsyncSession = Depends(get_db_session)) -> CostConfigSchema:
    row = await session.get(CostConfigModel, 1)
    if row is None:
        return CostConfigSchema(cost_per_gpu_hour=dict(DEFAULT_GPU_COSTS))
    return CostConfigSchema(
        cost_per_gpu_hour=row.cost_per_gpu_hour,
        gpu_amortization_years=row.gpu_amortization_years,
        facility_cost_multiplier=row.facility_cost_multiplier,
        working_hours_per_month=row.working_hours_per_month,
    )


@router.put("/config/costs", response_model=CostConfigSchema)
async def put_costs(
    body: CostConfigSchema,
    session: AsyncSession = Depends(get_db_session),
) -> CostConfigSchema:
    row = await upsert_cost_config(session, body.model_dump())
    return CostConfigSchema(
        cost_per_gpu_hour=row.cost_per_gpu_hour,
        gpu_amortization_years=row.gpu_amortization_years,
        facility_cost_multiplier=row.facility_cost_multiplier,
        working_hours_per_month=row.working_hours_per_month,
    )
