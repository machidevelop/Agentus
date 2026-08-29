from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from natilah.ingestion.synthetic import SyntheticDataGenerator
from natilah.models.database import Base, replace_cluster_data
from natilah.models.domain import ClusterDataset


@pytest_asyncio.fixture
async def async_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine: AsyncEngine) -> AsyncSession:
    async_session_factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session_factory() as session:
        yield session


@pytest.fixture
def synthetic_dataset() -> ClusterDataset:
    generator = SyntheticDataGenerator(
        num_nodes=16,
        gpus_per_node=8,
        num_jobs=50,
        time_window_hours=12,
        seed=42,
    )
    return generator.generate()


@pytest_asyncio.fixture
async def populated_session(
    async_session: AsyncSession, synthetic_dataset: ClusterDataset
) -> AsyncSession:
    await replace_cluster_data(async_session, synthetic_dataset)
    return async_session
