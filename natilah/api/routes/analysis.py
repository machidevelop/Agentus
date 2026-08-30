from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from natilah.agents.coordinator import AgentCoordinator
from natilah.api.schemas import (
    AgentSummarySchema,
    AnalysisRunResponse,
    AnalysisStatusResponse,
    CoordinationSummary,
)
from natilah.models.database import AnalysisRunModel, get_db_session
from natilah.models.domain import CoordinationReport
from natilah.safety.guards import Action, SafetyGuard

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_latest: dict[str, str | int | None] = {
    "run_id": None,
    "status": "idle",
    "opportunities_found": 0,
    "error": None,
}


def _summarize(report: CoordinationReport) -> CoordinationSummary:
    return CoordinationSummary(
        total_findings=report.total_findings,
        ranked_findings=report.ranked_findings,
        suppressed_findings=report.suppressed_findings,
        conflicts_resolved=report.conflicts_resolved,
        duplicate_gpu_hours_removed=report.duplicate_gpu_hours_removed,
        claimed_gpu_hours=report.claimed_gpu_hours,
        attributed_gpu_hours=report.attributed_gpu_hours,
        claimed_monthly_value=report.claimed_monthly_value,
        attributed_monthly_value=report.attributed_monthly_value,
        attributed_annual_value=report.attributed_annual_value,
        agents=[
            AgentSummarySchema(
                agent_name=a.agent_name,
                objective=a.objective.value,
                observations=a.observations,
                candidates_generated=a.candidates_generated,
                candidates_rejected_infeasible=a.candidates_rejected_infeasible,
                candidates_rejected_no_gain=a.candidates_rejected_no_gain,
                findings=a.findings,
                claimed_gpu_hours=a.claimed_gpu_hours,
                claimed_monthly_value=a.claimed_monthly_value,
                llm_used=a.llm_used,
                error=a.error,
            )
            for a in report.agents
        ],
        top_actions=report.top_actions,
    )


@router.post("/run", response_model=AnalysisRunResponse)
async def run_analysis(session: AsyncSession = Depends(get_db_session)) -> AnalysisRunResponse:
    SafetyGuard().check_action(Action(name="run_analysis", is_read_only=True))
    run_id = str(uuid4())
    _latest.update({"run_id": run_id, "status": "running", "opportunities_found": 0, "error": None})
    row = AnalysisRunModel(
        run_id=run_id,
        status="running",
        started_at=datetime.now(timezone.utc),
        opportunities_found=0,
    )
    session.add(row)
    await session.commit()
    try:
        findings, report = await AgentCoordinator().run(session)
        row.status = "completed"
        row.completed_at = datetime.now(timezone.utc)
        row.opportunities_found = report.ranked_findings
        row.report = report.model_dump(mode="json")
        await session.commit()
        _latest.update({"status": "completed", "opportunities_found": report.ranked_findings})
        return AnalysisRunResponse(
            run_id=run_id,
            status="completed",
            opportunities_found=report.ranked_findings,
            coordination=_summarize(report),
        )
    except Exception as exc:
        row.status = "failed"
        row.error = str(exc)
        row.completed_at = datetime.now(timezone.utc)
        await session.commit()
        _latest.update({"status": "failed", "error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/status", response_model=AnalysisStatusResponse)
async def analysis_status() -> AnalysisStatusResponse:
    return AnalysisStatusResponse(
        run_id=_latest["run_id"],  # type: ignore[arg-type]
        status=str(_latest["status"]),
        opportunities_found=int(_latest["opportunities_found"] or 0),
        error=_latest["error"],  # type: ignore[arg-type]
    )
