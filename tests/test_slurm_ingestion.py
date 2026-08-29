"""Tests for the Slurm connector: parsing, dataset build, and full pipeline integration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from natilah.ingestion.slurm import (
    SlurmDataSource,
    expand_nodelist,
    gpu_from_tres,
    parse_gres,
    parse_sacct,
    parse_sinfo,
    parse_squeue_snapshot,
    parse_tres,
    resolve_gpu_type,
)
from natilah.models.database import Base, replace_cluster_data


# ---------------------------------------------------------------------------
# Fixtures: realistic Slurm output
# ---------------------------------------------------------------------------

SAMPLE_SINFO = """\
gpu-node-01|64|524288|gpu:a100:8(S:0-1)|idle|gpu
gpu-node-02|64|524288|gpu:a100:8(S:0-1)|idle|gpu
gpu-node-03|64|524288|gpu:a100:8(S:0-1)|idle|gpu
gpu-node-04|64|524288|gpu:a100:8(S:0-1)|idle|gpu
gpu-node-05|128|1048576|gpu:h100:8(S:0-1)|idle|gpu-h100
"""

SAMPLE_SACCT = """\
JobID|JobName|User|Submit|Start|End|State|ReqTRES|AllocTRES|NodeList|Partition|Priority|ExitCode
1001|gpt-pretrain|alice|2026-08-22T08:00:00|2026-08-22T08:05:00|2026-08-22T16:00:00|COMPLETED|billing=8,cpu=64,gres/gpu=8,mem=512G,node=1|billing=8,cpu=64,gres/gpu=8,gres/gpu:a100=8,mem=512G,node=1|gpu-node-03|gpu|1000|0:0
1002|inference-svc|bob|2026-08-22T09:00:00|2026-08-22T09:02:00|2026-08-22T10:00:00|COMPLETED|billing=2,cpu=16,gres/gpu=2,mem=128G,node=1|billing=2,cpu=16,gres/gpu=2,gres/gpu:a100=2,mem=128G,node=1|gpu-node-01|gpu|500|0:0
1003|finetune-llm|charlie|2026-08-22T10:00:00|2026-08-22T11:00:00|2026-08-22T18:00:00|COMPLETED|billing=4,cpu=32,gres/gpu=4,mem=256G,node=1|billing=4,cpu=32,gres/gpu=4,gres/gpu:a100=4,mem=256G,node=1|gpu-node-02|gpu|800|0:0
1004|eval-bench|dave|2026-08-22T11:30:00|2026-08-22T12:15:00|2026-08-22T14:00:00|COMPLETED|billing=8,cpu=64,gres/gpu=8,mem=512G,node=1|billing=8,cpu=64,gres/gpu=8,gres/gpu:a100=8,mem=512G,node=1|gpu-node-01,gpu-node-02|gpu|600|0:0
1005|data-prep|eve|2026-08-22T14:00:00|2026-08-22T14:01:00|2026-08-22T15:00:00|COMPLETED|billing=1,cpu=8,gres/gpu=1,mem=64G,node=1|billing=1,cpu=8,gres/gpu=1,gres/gpu:a100=1,mem=64G,node=1|gpu-node-04|gpu|300|0:0
1006|long-wait|frank|2026-08-22T06:00:00|2026-08-22T08:30:00|2026-08-22T09:30:00|COMPLETED|billing=2,cpu=16,gres/gpu=2,mem=128G,node=1|billing=2,cpu=16,gres/gpu=2,gres/gpu:a100=2,mem=128G,node=1|gpu-node-04|gpu|200|0:0
"""

SAMPLE_SQUEUE = """\
2001|pending-train|grace|PENDING|2026-08-22T12:00:00|N/A|N/A|gres:gpu:8|900
2002|running-eval|heidi|RUNNING|2026-08-22T10:00:00|2026-08-22T10:05:00|gpu-node-05|gres:gpu:4|700
"""


# ---------------------------------------------------------------------------
# Unit tests: parsing helpers
# ---------------------------------------------------------------------------

class TestExpandNodelist:
    def test_single_node(self):
        assert expand_nodelist("gpu-node-01") == ["gpu-node-01"]

    def test_range(self):
        assert expand_nodelist("gpu-node-[01-04]") == [
            "gpu-node-01", "gpu-node-02", "gpu-node-03", "gpu-node-04"
        ]

    def test_list(self):
        assert expand_nodelist("gpu-node-[01,03,05]") == [
            "gpu-node-01", "gpu-node-03", "gpu-node-05"
        ]

    def test_mixed_range_and_list(self):
        result = expand_nodelist("node[01-03,05,07-09]")
        assert result == ["node01", "node02", "node03", "node05", "node07", "node08", "node09"]

    def test_multiple_prefixes(self):
        result = expand_nodelist("rack1-node[01-02],rack2-node[03-04]")
        assert result == ["rack1-node01", "rack1-node02", "rack2-node03", "rack2-node04"]

    def test_null(self):
        assert expand_nodelist("(null)") == []
        assert expand_nodelist("") == []
        assert expand_nodelist("N/A") == []

    def test_comma_separated_simple(self):
        assert expand_nodelist("gpu-node-01,gpu-node-02") == ["gpu-node-01", "gpu-node-02"]


class TestParseGres:
    def test_gpu_type_count_socket(self):
        assert parse_gres("gpu:a100:8(S:0-1)") == ("a100", 8)

    def test_gpu_count_only(self):
        assert parse_gres("gpu:8") == (None, 8)

    def test_gpu_type_count(self):
        assert parse_gres("gpu:h100_80gb:4") == ("h100_80gb", 4)

    def test_gres_prefix(self):
        assert parse_gres("gres:gpu:8") == (None, 8)
        assert parse_gres("gres/gpu:a100:4") == ("a100", 4)

    def test_null(self):
        assert parse_gres("(null)") == (None, 0)
        assert parse_gres("") == (None, 0)

    def test_multi_gres(self):
        name, count = parse_gres("gpu:a100:8(S:0-1),mps:0")
        assert name == "a100"
        assert count == 8


class TestParseTres:
    def test_basic(self):
        tres = parse_tres("billing=8,cpu=64,gres/gpu=8,gres/gpu:a100=8,mem=512G,node=1")
        assert tres["gres/gpu"] == "8"
        assert tres["gres/gpu:a100"] == "8"
        assert tres["cpu"] == "64"

    def test_gpu_from_tres(self):
        tres = parse_tres("billing=8,cpu=64,gres/gpu=8,gres/gpu:a100=8,mem=512G,node=1")
        name, count = gpu_from_tres(tres)
        assert name == "a100"
        assert count == 8

    def test_gpu_from_tres_no_type(self):
        tres = parse_tres("billing=2,cpu=16,gres/gpu=2,mem=128G,node=1")
        name, count = gpu_from_tres(tres)
        assert name is None
        assert count == 2


class TestResolveGpuType:
    def test_known_types(self):
        assert resolve_gpu_type("a100") == "A100-80GB"
        assert resolve_gpu_type("h100_80gb") == "H100-80GB"
        assert resolve_gpu_type("a100_sxm4_80gb") == "A100-80GB"

    def test_unknown_passthrough(self):
        assert resolve_gpu_type("custom_gpu_v1") == "custom_gpu_v1"

    def test_none(self):
        assert resolve_gpu_type(None) == "A100-80GB"


# ---------------------------------------------------------------------------
# Unit tests: output parsers
# ---------------------------------------------------------------------------

class TestParseSacct:
    def test_parses_jobs(self):
        records = parse_sacct(SAMPLE_SACCT)
        assert len(records) == 6
        assert records[0]["JobID"] == "1001"
        assert records[0]["JobName"] == "gpt-pretrain"
        assert records[0]["User"] == "alice"

    def test_skips_job_steps(self):
        text = SAMPLE_SACCT + "1001.batch|batch||2026-08-22T08:05:00|2026-08-22T08:05:00|2026-08-22T16:00:00|COMPLETED||||gpu||\n"
        records = parse_sacct(text)
        assert all("." not in r["JobID"] for r in records)

    def test_empty(self):
        assert parse_sacct("") == []
        assert parse_sacct("JobID|JobName\n") == []


class TestParseSinfo:
    def test_parses_nodes(self):
        records = parse_sinfo(SAMPLE_SINFO)
        assert len(records) == 5
        assert records[0]["hostname"] == "gpu-node-01"
        assert records[0]["cpus"] == "64"

    def test_expands_ranges(self):
        text = "gpu-node-[01-03]|64|524288|gpu:a100:8|idle|gpu\n"
        records = parse_sinfo(text)
        assert len(records) == 3
        assert records[0]["hostname"] == "gpu-node-01"
        assert records[2]["hostname"] == "gpu-node-03"


class TestParseSqueue:
    def test_parses_snapshot(self):
        records = parse_squeue_snapshot(SAMPLE_SQUEUE)
        assert len(records) == 2
        assert records[0]["jobid"] == "2001"
        assert records[0]["state"] == "PENDING"
        assert records[1]["state"] == "RUNNING"


# ---------------------------------------------------------------------------
# Integration: SlurmDataSource.build_dataset
# ---------------------------------------------------------------------------

class TestSlurmDatasetBuild:
    def test_builds_nodes_and_gpus(self):
        source = SlurmDataSource(sacct_text=SAMPLE_SACCT, sinfo_text=SAMPLE_SINFO)
        ds = source.build_dataset()
        assert len(ds.nodes) == 5
        assert len(ds.gpus) == 40  # 5 nodes × 8 GPUs
        node_types = {n.node_id: n.gpu_type.name for n in ds.nodes}
        assert node_types["gpu-node-01"] == "A100-80GB"
        assert node_types["gpu-node-05"] == "H100-80GB"

    def test_builds_jobs_and_allocations(self):
        source = SlurmDataSource(sacct_text=SAMPLE_SACCT, sinfo_text=SAMPLE_SINFO)
        ds = source.build_dataset()
        assert len(ds.jobs) == 6
        assert len(ds.allocations) == 6
        job_ids = {j.job_id for j in ds.jobs}
        assert "1001" in job_ids
        assert "1006" in job_ids

    def test_multi_node_allocation(self):
        source = SlurmDataSource(sacct_text=SAMPLE_SACCT, sinfo_text=SAMPLE_SINFO)
        ds = source.build_dataset()
        alloc_1004 = next(a for a in ds.allocations if a.job_id == "1004")
        assert set(alloc_1004.node_ids) == {"gpu-node-01", "gpu-node-02"}
        assert len(alloc_1004.gpu_ids) == 8

    def test_queue_decisions_for_long_waits(self):
        source = SlurmDataSource(sacct_text=SAMPLE_SACCT, sinfo_text=SAMPLE_SINFO)
        ds = source.build_dataset()
        queue_decs = [d for d in ds.decisions if d.decision_type.value == "queue"]
        waited_jobs = {d.job_id for d in queue_decs}
        assert "1003" in waited_jobs  # 60 min wait
        assert "1006" in waited_jobs  # 150 min wait

    def test_synthesizes_queue_snapshots(self):
        source = SlurmDataSource(sacct_text=SAMPLE_SACCT, sinfo_text=SAMPLE_SINFO)
        ds = source.build_dataset()
        assert len(ds.queue_snapshots) > 0
        assert all(q.total_gpus == 40 for q in ds.queue_snapshots)

    def test_squeue_snapshot_parsing(self):
        ts = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
        source = SlurmDataSource(
            sacct_text=SAMPLE_SACCT,
            sinfo_text=SAMPLE_SINFO,
            squeue_snapshots=[(ts, SAMPLE_SQUEUE)],
        )
        ds = source.build_dataset()
        real_snapshots = [q for q in ds.queue_snapshots if q.timestamp == ts]
        assert len(real_snapshots) == 1
        assert "2001" in real_snapshots[0].pending_jobs
        assert "2002" in real_snapshots[0].running_jobs

    def test_gpu_type_override(self):
        source = SlurmDataSource(
            sacct_text=SAMPLE_SACCT, sinfo_text=SAMPLE_SINFO, gpu_type_override="H100-80GB"
        )
        ds = source.build_dataset()
        assert all(n.gpu_type.name == "H100-80GB" for n in ds.nodes)

    def test_validation(self):
        source = SlurmDataSource(sacct_text="", sinfo_text="")
        issues = source.validate()
        assert len(issues) >= 2
        fields = {i.field for i in issues}
        assert "sacct" in fields
        assert "sinfo" in fields


# ---------------------------------------------------------------------------
# Integration: full pipeline (Slurm → ingest → analyze → findings)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def slurm_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def slurm_session(slurm_engine: AsyncEngine) -> AsyncSession:
    factory = sessionmaker(slurm_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


async def test_slurm_ingest_and_analyze(slurm_session: AsyncSession):
    """Acceptance test: Slurm data → ingest → full pipeline → findings produced."""
    source = SlurmDataSource(sacct_text=SAMPLE_SACCT, sinfo_text=SAMPLE_SINFO)
    result = await source.ingest(slurm_session)

    assert result.source == "slurm"
    assert result.nodes == 5
    assert result.gpus == 40
    assert result.jobs == 6
    assert result.allocations == 6

    from natilah.agents.gpu_allocation_agent import GPUAllocationAgent

    agent = GPUAllocationAgent()
    findings = await agent.analyze(slurm_session)

    assert len(findings) > 0, "Pipeline must produce at least one finding from Slurm data"
    for f in findings:
        assert f.value.estimated_monthly_value >= 0
        assert f.confidence.score > 0
        assert f.alternative.agent_name == "gpu_allocation"
        assert len(f.alternative.constraints_satisfied) > 0
