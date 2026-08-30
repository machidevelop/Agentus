"""SQLAlchemy ORM, engine setup, and persistence helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, select
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import StaticPool

from natilah.config import settings
from natilah.models.domain import (
    Allocation,
    ClusterDataset,
    Finding,
    GPU,
    GPUType,
    GPUUtilizationSample,
    GPU_TYPE_CATALOG,
    Job,
    Node,
    QueueSnapshot,
    SchedulerDecision,
)
from natilah.models.enums import DecisionType, JobState, OpportunityType


class Base(DeclarativeBase):
    pass


class NodeModel(Base):
    __tablename__ = "nodes"

    node_id: Mapped[str] = mapped_column(String, primary_key=True)
    hostname: Mapped[str] = mapped_column(String, nullable=False)
    gpu_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gpu_type_name: Mapped[str] = mapped_column(String, nullable=False)
    total_memory_gb: Mapped[float] = mapped_column(Float, nullable=False)
    cpu_cores: Mapped[int] = mapped_column(Integer, nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class GPUModel(Base):
    __tablename__ = "gpus"

    gpu_id: Mapped[str] = mapped_column(String, primary_key=True)
    node_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    gpu_index: Mapped[int] = mapped_column(Integer, nullable=False)
    gpu_type_name: Mapped[str] = mapped_column(String, nullable=False)
    memory_gb: Mapped[float] = mapped_column(Float, nullable=False)
    tdp_watts: Mapped[float] = mapped_column(Float, nullable=False)
    compute_capability: Mapped[str] = mapped_column(String, nullable=False)
    fp16_tflops: Mapped[float] = mapped_column(Float, nullable=False)


class JobModel(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    user: Mapped[str] = mapped_column(String, nullable=False)
    submit_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    requested_gpus: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_gpu_type: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    constraints: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)

    __table_args__ = (Index("ix_jobs_job_id_time", "job_id", "submit_time"),)


class AllocationModel(Base):
    __tablename__ = "allocations"

    allocation_id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    gpu_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    node_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class TelemetrySampleModel(Base):
    __tablename__ = "telemetry_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gpu_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    gpu_utilization_pct: Mapped[float] = mapped_column(Float, nullable=False)
    memory_utilization_pct: Mapped[float] = mapped_column(Float, nullable=False)
    memory_used_gb: Mapped[float] = mapped_column(Float, nullable=False)
    power_watts: Mapped[float | None] = mapped_column(Float, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)


class SchedulerDecisionModel(Base):
    __tablename__ = "scheduler_decisions"

    decision_id: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    decision_type: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chosen_action: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cluster_state_id: Mapped[str | None] = mapped_column(String, nullable=True)


class QueueSnapshotModel(Base):
    __tablename__ = "queue_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    pending_jobs: Mapped[list[str]] = mapped_column(JSON, default=list)
    running_jobs: Mapped[list[str]] = mapped_column(JSON, default=list)
    total_gpus: Mapped[int] = mapped_column(Integer, nullable=False)
    allocated_gpus: Mapped[int] = mapped_column(Integer, nullable=False)
    idle_gpus: Mapped[int] = mapped_column(Integer, nullable=False)


class OpportunityModel(Base):
    __tablename__ = "opportunities"

    opportunity_id: Mapped[str] = mapped_column(String, primary_key=True)
    opportunity_type: Mapped[str] = mapped_column(String, nullable=False)
    decision_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    decision: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    severity: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    affected_job_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    affected_gpu_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    alternative: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    comparison: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    utilization_series: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    monthly_value: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    annual_value: Mapped[float] = mapped_column(Float, nullable=False)

    # Specialized-agent and coordination-layer columns
    agent_name: Mapped[str] = mapped_column(String, default="", index=True)
    objective: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    claim: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    candidates_considered: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    selection_score: Mapped[float] = mapped_column(Float, default=0.0)
    attribution: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="awaiting_approval", index=True)
    rank: Mapped[int] = mapped_column(Integer, default=0, index=True)
    resolution: Mapped[str] = mapped_column(String, default="unique", index=True)
    attributed_monthly_value: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    expected_monthly_value: Mapped[float] = mapped_column(Float, default=0.0)


class CostConfigModel(Base):
    __tablename__ = "cost_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cost_per_gpu_hour: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False)
    gpu_acquisition_cost: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    gpu_amortization_years: Mapped[float] = mapped_column(Float, default=3.0)
    facility_cost_multiplier: Mapped[float] = mapped_column(Float, default=1.4)
    working_hours_per_month: Mapped[float] = mapped_column(Float, default=720.0)


class AnalysisRunModel(Base):
    __tablename__ = "analysis_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opportunities_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    if ":///" in url and ":memory:" not in url:
        path = url.split(":///", 1)[1]
        if path.startswith("./"):
            Path(path).parent.mkdir(parents=True, exist_ok=True)


def configure_engine(database_url: str | None = None) -> AsyncEngine:
    global _engine, _session_factory
    url = database_url or settings.database_url
    _ensure_sqlite_dir(url)
    kwargs: dict[str, Any] = {"echo": False}
    if url.endswith(":memory:"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    _engine = create_async_engine(url, **kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        configure_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        configure_engine()
    assert _session_factory is not None
    return _session_factory


# Columns added after the V1 schema shipped. SQLite has no migration tool here,
# so an existing database is widened in place instead of being thrown away.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "opportunities": {
        "agent_name": "VARCHAR DEFAULT ''",
        "objective": "VARCHAR",
        "recommended_action": "TEXT DEFAULT ''",
        "claim": "JSON",
        "candidates_considered": "JSON",
        "evidence": "JSON",
        "selection_score": "FLOAT DEFAULT 0.0",
        "attribution": "JSON",
        "status": "VARCHAR DEFAULT 'awaiting_approval'",
        "rank": "INTEGER DEFAULT 0",
        "resolution": "VARCHAR DEFAULT 'unique'",
        "attributed_monthly_value": "FLOAT DEFAULT 0.0",
        "expected_monthly_value": "FLOAT DEFAULT 0.0",
    },
    "analysis_runs": {"report": "JSON"},
}


async def _add_missing_columns(conn) -> None:
    for table, columns in _ADDED_COLUMNS.items():
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = {row[1] for row in result.fetchall()}
        if not existing:
            continue
        for name, ddl in columns.items():
            if name in existing:
                continue
            await conn.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN "{name}" {ddl}')


async def init_db(database_url: str | None = None) -> None:
    engine = configure_engine(database_url) if database_url else get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            await _add_missing_columns(conn)


async def reset_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _gpu_type(name: str, memory_gb: float | None = None) -> GPUType:
    if name in GPU_TYPE_CATALOG:
        return GPU_TYPE_CATALOG[name]
    return GPUType(
        name=name,
        memory_gb=memory_gb or 80.0,
        tdp_watts=400.0,
        compute_capability="8.0",
        fp16_tflops=312.0,
    )


async def replace_cluster_data(session: AsyncSession, dataset: ClusterDataset) -> None:
    for model in (
        TelemetrySampleModel,
        QueueSnapshotModel,
        SchedulerDecisionModel,
        AllocationModel,
        JobModel,
        GPUModel,
        NodeModel,
        OpportunityModel,
    ):
        await session.execute(model.__table__.delete())

    session.add_all(
        [
            NodeModel(
                node_id=n.node_id,
                hostname=n.hostname,
                gpu_count=n.gpu_count,
                gpu_type_name=n.gpu_type.name,
                total_memory_gb=n.total_memory_gb,
                cpu_cores=n.cpu_cores,
                labels=n.labels,
            )
            for n in dataset.nodes
        ]
    )
    session.add_all(
        [
            GPUModel(
                gpu_id=g.gpu_id,
                node_id=g.node_id,
                gpu_index=g.gpu_index,
                gpu_type_name=g.gpu_type.name,
                memory_gb=g.gpu_type.memory_gb,
                tdp_watts=g.gpu_type.tdp_watts,
                compute_capability=g.gpu_type.compute_capability,
                fp16_tflops=g.gpu_type.fp16_tflops,
            )
            for g in dataset.gpus
        ]
    )
    session.add_all(
        [
            JobModel(
                job_id=j.job_id,
                name=j.name,
                user=j.user,
                submit_time=j.submit_time,
                start_time=j.start_time,
                end_time=j.end_time,
                state=j.state.value,
                requested_gpus=j.requested_gpus,
                requested_gpu_type=j.requested_gpu_type,
                priority=j.priority,
                constraints=j.constraints,
            )
            for j in dataset.jobs
        ]
    )
    session.add_all(
        [
            AllocationModel(
                allocation_id=a.allocation_id,
                job_id=a.job_id,
                gpu_ids=a.gpu_ids,
                node_ids=a.node_ids,
                start_time=a.start_time,
                end_time=a.end_time,
                decision_reason=a.decision_reason,
            )
            for a in dataset.allocations
        ]
    )
    session.add_all(
        [
            SchedulerDecisionModel(
                decision_id=d.decision_id,
                timestamp=d.timestamp,
                decision_type=d.decision_type.value,
                job_id=d.job_id,
                chosen_action=d.chosen_action,
                cluster_state_id=d.cluster_state_id,
            )
            for d in dataset.decisions
        ]
    )
    session.add_all(
        [
            QueueSnapshotModel(
                timestamp=q.timestamp,
                pending_jobs=q.pending_jobs,
                running_jobs=q.running_jobs,
                total_gpus=q.total_gpus,
                allocated_gpus=q.allocated_gpus,
                idle_gpus=q.idle_gpus,
            )
            for q in dataset.queue_snapshots
        ]
    )
    if dataset.samples:
        await session.flush()
        from sqlalchemy import insert

        await session.execute(
            insert(TelemetrySampleModel),
            [
                {
                    "gpu_id": s.gpu_id,
                    "timestamp": s.timestamp,
                    "gpu_utilization_pct": s.gpu_utilization_pct,
                    "memory_utilization_pct": s.memory_utilization_pct,
                    "memory_used_gb": s.memory_used_gb,
                    "power_watts": s.power_watts,
                    "job_id": s.job_id,
                }
                for s in dataset.samples
            ],
        )
    await session.commit()


async def load_cluster_dataset(session: AsyncSession) -> ClusterDataset:
    nodes_rows = (await session.execute(select(NodeModel))).scalars().all()
    gpu_rows = (await session.execute(select(GPUModel))).scalars().all()
    job_rows = (await session.execute(select(JobModel))).scalars().all()
    alloc_rows = (await session.execute(select(AllocationModel))).scalars().all()
    sample_rows = (await session.execute(select(TelemetrySampleModel))).scalars().all()
    decision_rows = (await session.execute(select(SchedulerDecisionModel))).scalars().all()
    queue_rows = (await session.execute(select(QueueSnapshotModel))).scalars().all()

    gpus = [
        GPU(
            gpu_id=g.gpu_id,
            gpu_type=_gpu_type(g.gpu_type_name, g.memory_gb),
            node_id=g.node_id,
            gpu_index=g.gpu_index,
        )
        for g in gpu_rows
    ]
    nodes = [
        Node(
            node_id=n.node_id,
            hostname=n.hostname,
            gpu_count=n.gpu_count,
            gpu_type=_gpu_type(n.gpu_type_name, n.total_memory_gb / max(n.gpu_count, 1)),
            total_memory_gb=n.total_memory_gb,
            cpu_cores=n.cpu_cores,
            labels=n.labels or {},
        )
        for n in nodes_rows
    ]
    jobs = [
        Job(
            job_id=j.job_id,
            name=j.name,
            user=j.user,
            submit_time=j.submit_time,
            start_time=j.start_time,
            end_time=j.end_time,
            state=JobState(j.state),
            requested_gpus=j.requested_gpus,
            requested_gpu_type=j.requested_gpu_type,
            priority=j.priority,
            constraints=j.constraints or {},
        )
        for j in job_rows
    ]
    allocations = [
        Allocation(
            allocation_id=a.allocation_id,
            job_id=a.job_id,
            gpu_ids=a.gpu_ids,
            node_ids=a.node_ids,
            start_time=a.start_time,
            end_time=a.end_time,
            decision_reason=a.decision_reason,
        )
        for a in alloc_rows
    ]
    samples = [
        GPUUtilizationSample(
            gpu_id=s.gpu_id,
            timestamp=s.timestamp,
            gpu_utilization_pct=s.gpu_utilization_pct,
            memory_utilization_pct=s.memory_utilization_pct,
            memory_used_gb=s.memory_used_gb,
            power_watts=s.power_watts,
            job_id=s.job_id,
        )
        for s in sample_rows
    ]
    decisions = [
        SchedulerDecision(
            decision_id=d.decision_id,
            timestamp=d.timestamp,
            decision_type=DecisionType(d.decision_type),
            job_id=d.job_id,
            chosen_action=d.chosen_action or {},
            cluster_state_id=d.cluster_state_id,
        )
        for d in decision_rows
    ]
    queues = [
        QueueSnapshot(
            timestamp=q.timestamp,
            pending_jobs=q.pending_jobs or [],
            running_jobs=q.running_jobs or [],
            total_gpus=q.total_gpus,
            allocated_gpus=q.allocated_gpus,
            idle_gpus=q.idle_gpus,
        )
        for q in queue_rows
    ]
    return ClusterDataset(
        nodes=nodes,
        gpus=gpus,
        jobs=jobs,
        allocations=allocations,
        samples=samples,
        decisions=decisions,
        queue_snapshots=queues,
    )


async def save_findings(session: AsyncSession, findings: list[Finding]) -> None:
    await session.execute(OpportunityModel.__table__.delete())
    session.add_all(
        [
            OpportunityModel(
                opportunity_id=f.opportunity_id,
                opportunity_type=f.opportunity_type.value,
                decision_id=f.decision.decision_id,
                decision=f.decision.model_dump(mode="json"),
                severity=f.severity,
                title=f.title,
                description=f.description,
                detected_at=f.detected_at,
                affected_job_ids=f.affected_job_ids,
                affected_gpu_ids=f.affected_gpu_ids,
                alternative=f.alternative.model_dump(mode="json"),
                comparison=f.comparison.model_dump(mode="json"),
                value=f.value.model_dump(mode="json"),
                confidence=f.confidence.model_dump(mode="json"),
                utilization_series=[p.model_dump(mode="json") for p in f.utilization_series],
                monthly_value=f.value.estimated_monthly_value,
                annual_value=f.value.estimated_annual_value,
                agent_name=f.agent_name,
                objective=f.objective.value if f.objective else None,
                recommended_action=f.recommended_action,
                claim=f.claim.model_dump(mode="json"),
                candidates_considered=[c.model_dump(mode="json") for c in f.candidates_considered],
                evidence=f.evidence,
                selection_score=f.selection_score,
                attribution=f.attribution.model_dump(mode="json"),
                status=f.status.value,
                rank=f.attribution.rank,
                resolution=f.attribution.resolution.value,
                attributed_monthly_value=f.attribution.attributed_monthly_value,
                expected_monthly_value=f.attribution.expected_monthly_value,
            )
            for f in findings
        ]
    )
    await session.commit()


def _row_to_finding(row: OpportunityModel) -> Finding:
    payload = {
        "opportunity_id": row.opportunity_id,
        "opportunity_type": OpportunityType(row.opportunity_type),
        "decision": row.decision,
        "severity": row.severity,
        "title": row.title,
        "description": row.description,
        "detected_at": row.detected_at,
        "affected_job_ids": row.affected_job_ids or [],
        "affected_gpu_ids": row.affected_gpu_ids or [],
        "alternative": row.alternative,
        "comparison": row.comparison,
        "value": row.value,
        "confidence": row.confidence,
        "utilization_series": row.utilization_series or [],
        "agent_name": row.agent_name or "",
        "objective": row.objective,
        "recommended_action": row.recommended_action or "",
        "claim": row.claim or {},
        "candidates_considered": row.candidates_considered or [],
        "evidence": row.evidence or {},
        "selection_score": row.selection_score or 0.0,
        "attribution": row.attribution or {},
        "status": row.status or "awaiting_approval",
    }
    return Finding.model_validate(payload)


async def load_findings(session: AsyncSession) -> list[Finding]:
    rows = (
        (await session.execute(select(OpportunityModel).order_by(OpportunityModel.monthly_value.desc())))
        .scalars()
        .all()
    )
    return [_row_to_finding(row) for row in rows]


async def load_finding(session: AsyncSession, opportunity_id: str) -> Finding | None:
    row = await session.get(OpportunityModel, opportunity_id)
    return None if row is None else _row_to_finding(row)


async def get_cost_config_row(session: AsyncSession) -> CostConfigModel | None:
    return await session.get(CostConfigModel, 1)


async def load_ranked_findings(session: AsyncSession, limit: int = 10) -> list[Finding]:
    """Top coordinated actions: conflict-free, deduplicated, ranked by value."""
    rows = (
        (
            await session.execute(
                select(OpportunityModel)
                .where(OpportunityModel.rank > 0)
                .where(OpportunityModel.resolution.in_(["unique", "deduplicated"]))
                .order_by(OpportunityModel.rank.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_row_to_finding(row) for row in rows]


async def set_finding_status(
    session: AsyncSession,
    opportunity_id: str,
    status: str,
) -> OpportunityModel | None:
    """Record a human decision on a finding. Nothing is executed either way."""
    row = await session.get(OpportunityModel, opportunity_id)
    if row is None:
        return None
    row.status = status
    await session.commit()
    await session.refresh(row)
    return row


async def upsert_cost_config(session: AsyncSession, payload: dict[str, Any]) -> CostConfigModel:
    row = await session.get(CostConfigModel, 1)
    if row is None:
        row = CostConfigModel(id=1, **payload)
        session.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return row
