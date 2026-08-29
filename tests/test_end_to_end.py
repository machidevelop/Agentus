from __future__ import annotations

import pytest

from natilah.agents.gpu_allocation_agent import GPUAllocationAgent
from natilah.models.database import load_findings


@pytest.mark.asyncio
async def test_end_to_end_pipeline(populated_session):
    agent = GPUAllocationAgent()
    findings = await agent.analyze(populated_session)

    assert isinstance(findings, list)
    assert len(findings) > 0

    # Ensure findings are sorted by economic value descending
    for i in range(len(findings) - 1):
        assert findings[i].value.estimated_monthly_value >= findings[i + 1].value.estimated_monthly_value

    # Verify findings persisted in DB
    db_findings = await load_findings(populated_session)
    assert len(db_findings) == len(findings)

    first = findings[0]
    assert first.opportunity_id is not None
    assert first.alternative.description is not None
    assert first.value.estimated_monthly_value >= 0.0
    assert first.confidence.score >= 0.0
