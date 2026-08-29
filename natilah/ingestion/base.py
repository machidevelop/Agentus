"""Abstract ingestion interface. Future Slurm/K8s/Prometheus connectors implement this."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.models.domain import IngestionResult, ValidationIssue


class DataSource(ABC):
    @abstractmethod
    async def ingest(self, db: AsyncSession) -> IngestionResult:
        """Ingest data into the normalized model. Never touches production infrastructure."""
        ...

    @abstractmethod
    def validate(self) -> list[ValidationIssue]:
        """Validate data before ingestion."""
        ...
