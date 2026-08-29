from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from natilah.api.schemas import IngestionGenerateRequest, IngestionResponse
from natilah.ingestion.json_upload import JSONUploadSource
from natilah.ingestion.synthetic import SyntheticDataGenerator
from natilah.models.database import get_db_session

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.post("/generate", response_model=IngestionResponse)
async def generate_synthetic(
    body: IngestionGenerateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> IngestionResponse:
    source = SyntheticDataGenerator(
        num_nodes=body.num_nodes,
        gpus_per_node=body.gpus_per_node,
        num_jobs=body.num_jobs,
        time_window_hours=body.time_window_hours,
        seed=body.seed,
    )
    try:
        result = await source.ingest(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return IngestionResponse(**result.model_dump())


@router.post("/upload", response_model=IngestionResponse)
async def upload_json(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> IngestionResponse:
    raw = await file.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    source = JSONUploadSource(payload)
    issues = source.validate()
    if issues:
        raise HTTPException(
            status_code=400,
            detail="; ".join(f"{i.field}: {i.message}" for i in issues),
        )
    result = await source.ingest(session)
    return IngestionResponse(**result.model_dump())
