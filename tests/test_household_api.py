"""The consumer API: stateless, read-only, and honest about its totals."""

from __future__ import annotations

import io
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from natilah.api.app import app
from natilah.api.routes.household import analyze_household
from natilah.ingestion.household import generate_household


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_demo_endpoint_returns_ranked_actions(client: AsyncClient):
    resp = await client.get("/api/household/demo")
    assert resp.status_code == 200
    body = resp.json()

    assert body["actions"], "the demo household should produce actions"
    assert body["execution"] == "recommendation_only"

    ranks = [a["rank"] for a in body["actions"]]
    assert ranks == sorted(ranks), "actions must arrive ranked"

    for action in body["actions"]:
        assert action["recommended_action"]
        assert action["meter"] in {"claim_dollars", "recurring_dollars"}
        assert 0.0 <= action["confidence"] <= 1.0
        assert action["constraints_checked"]


@pytest.mark.asyncio
async def test_one_time_and_recurring_money_are_never_added_together(client: AsyncClient):
    resp = await client.get("/api/household/demo")
    totals = resp.json()["totals"]

    assert totals["one_time_recoverable"] > 0
    assert totals["recurring_monthly"] > 0
    assert totals["recurring_annual"] == pytest.approx(totals["recurring_monthly"] * 12, abs=0.5)
    assert "never added together" in totals["deduplicated_note"]


@pytest.mark.asyncio
async def test_credited_totals_never_exceed_claimed(client: AsyncClient):
    """Deduplication may only ever reduce a headline, never inflate it."""
    totals = (await client.get("/api/household/demo")).json()["totals"]

    assert totals["one_time_recoverable"] <= totals["claimed_one_time"] + 0.01
    assert totals["recurring_monthly"] <= totals["claimed_recurring_monthly"] + 0.01


@pytest.mark.asyncio
async def test_upload_analyses_a_household_export(client: AsyncClient):
    raw = {
        "household_id": "h_upload",
        "as_of": "2026-09-01T00:00:00+00:00",
        "policies": [{"payer_id": "p1", "covered_codes": ["99213"], "internal_appeal_days": 180}],
        "plans": [
            {
                "member_id": "m1",
                "payer_id": "p1",
                "deductible": 1000.0,
                "deductible_met": 1000.0,
                "coinsurance_rate": 0.2,
                "out_of_pocket_max": 5000.0,
                "out_of_pocket_met": 1200.0,
            }
        ],
        "claims": [
            {
                "claim_id": "CLM1",
                "line_id": "1",
                "member_id": "m1",
                "payer_id": "p1",
                "network_status": "in_network",
                "service_date": "2026-07-01T00:00:00+00:00",
                "processed_date": "2026-07-15T00:00:00+00:00",
                "procedure_code": "99213",
                "billed_amount": 400.0,
                "allowed_amount": 118.0,
                "plan_paid": 0.0,
                "patient_responsibility": 400.0,
                "denial_code": "CO-197",
            }
        ],
        "charges": [],
    }
    payload = io.BytesIO(json.dumps(raw).encode("utf-8"))
    resp = await client.post(
        "/api/household/analyze",
        files={"file": ("export.json", payload, "application/json")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["household_id"] == "h_upload"
    assert body["actions"]
    assert body["totals"]["one_time_recoverable"] > 0


@pytest.mark.asyncio
async def test_malformed_upload_is_rejected_with_a_reason(client: AsyncClient):
    payload = io.BytesIO(b"not json at all")
    resp = await client.post(
        "/api/household/analyze",
        files={"file": ("export.json", payload, "application/json")},
    )
    assert resp.status_code == 422
    assert "could not read" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_empty_export_is_rejected(client: AsyncClient):
    payload = io.BytesIO(json.dumps({"claims": [], "charges": []}).encode("utf-8"))
    resp = await client.post(
        "/api/household/analyze",
        files={"file": ("export.json", payload, "application/json")},
    )
    assert resp.status_code == 422
    assert "no claims or charges" in resp.json()["detail"].lower()


def test_every_action_keeps_its_rejected_alternatives():
    """A finding that hides what it ruled out is not auditable."""
    result = analyze_household(generate_household(seed=3))
    assert result.actions
    assert any(a.alternatives_rejected for a in result.actions), (
        "at least some actions should record alternatives that were ruled out"
    )
    for action in result.actions:
        assert action.alternatives_considered >= 1
        for rejected in action.alternatives_rejected:
            assert rejected["reason"], "a rejected alternative must say why"


def test_analysis_is_deterministic():
    first = analyze_household(generate_household(seed=42))
    second = analyze_household(generate_household(seed=42))
    assert [a.recommended_action for a in first.actions] == [
        a.recommended_action for a in second.actions
    ]
    assert first.totals.one_time_recoverable == second.totals.one_time_recoverable
