"""JSON file upload handler. Validates, normalizes, and persists cluster observations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.ingestion.base import DataSource
from natilah.ingestion.normalizer import normalize, validate_raw
from natilah.models.database import replace_cluster_data
from natilah.models.domain import IngestionResult, ValidationIssue


class JSONUploadSource(DataSource):
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload

    def validate(self) -> list[ValidationIssue]:
        return validate_raw(self.payload)

    async def ingest(self, db: AsyncSession) -> IngestionResult:
        issues = self.validate()
        if issues:
            raise ValueError("; ".join(f"{i.field}: {i.message}" for i in issues))
        dataset = normalize(self.payload)
        await replace_cluster_data(db, dataset)
        return IngestionResult(
            nodes=len(dataset.nodes),
            gpus=len(dataset.gpus),
            jobs=len(dataset.jobs),
            allocations=len(dataset.allocations),
            samples=len(dataset.samples),
            decisions=len(dataset.decisions),
            source="json_upload",
        )
