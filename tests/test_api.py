from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from natilah.api.app import app
from natilah.models.database import get_db_session


@pytest_asyncio.fixture
async def async_client(populated_session):
    async def _get_test_session():
        yield populated_session

    app.dependency_overrides[get_db_session] = _get_test_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_health(async_client: AsyncClient):
    resp = await async_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["safety_mode"] == "read_only"


@pytest.mark.asyncio
async def test_api_dashboard_summary(async_client: AsyncClient):
    resp = await async_client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "gpus_analyzed" in data
    assert "production_changes" in data
    assert data["production_changes"] == 0
    assert data["safety_mode"] == "read_only"


@pytest.mark.asyncio
async def test_api_ingest_generate(async_client: AsyncClient):
    resp = await async_client.post(
        "/api/ingestion/generate",
        json={"num_nodes": 8, "gpus_per_node": 8, "num_jobs": 20},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["jobs"] == 20
    assert data["source"] == "synthetic"


@pytest.mark.asyncio
async def test_api_analysis_run(async_client: AsyncClient):
    resp = await async_client.post("/api/analysis/run")
    assert resp.status_code == 200
    data = resp.json()
    assert "opportunities_found" in data


@pytest.mark.asyncio
async def test_api_opportunities_list(async_client: AsyncClient):
    # First run analysis to populate findings
    await async_client.post("/api/analysis/run")
    resp = await async_client.get("/api/opportunities")
    assert resp.status_code == 200
    opps = resp.json()
    assert isinstance(opps, list)
    if len(opps) > 0:
        opp_id = opps[0]["opportunity_id"]
        detail_resp = await async_client.get(f"/api/opportunities/{opp_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["opportunity_id"] == opp_id
        assert "what_happened" in detail
        assert "alternative" in detail


@pytest.mark.asyncio
async def test_api_config_costs(async_client: AsyncClient):
    get_resp = await async_client.get("/api/config/costs")
    assert get_resp.status_code == 200
    costs = get_resp.json()
    assert "cost_per_gpu_hour" in costs

    costs["cost_per_gpu_hour"]["A100-80GB"] = 2.50
    put_resp = await async_client.put("/api/config/costs", json=costs)
    assert put_resp.status_code == 200
    updated = put_resp.json()
    assert updated["cost_per_gpu_hour"]["A100-80GB"] == 2.50
