"""Compatibility entry point for the V1 single-agent pipeline.

V1 had one agent covering every kind of waste. That agent is now four
specialized agents plus a coordination layer, and this class simply drives
them so existing callers (scripts, API routes, tests) keep working.

New code should use `AgentCoordinator` directly: it returns the coordination
report alongside the findings.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.agents.base_agent import InfrastructureAgent
from natilah.agents.coordinator import AgentCoordinator
from natilah.engine.value_calculator import ValueCalculator
from natilah.models.domain import CoordinationReport, Finding, TimeRange


class GPUAllocationAgent(InfrastructureAgent):
    name = "gpu_allocation"
    domain = "gpu_allocation"

    def __init__(self, economic: ValueCalculator | None = None, top_n: int = 10):
        super().__init__()
        self.coordinator = AgentCoordinator(top_n=top_n)
        if economic is not None:
            for agent in self.coordinator.agents:
                agent.value_calculator = economic
        self.report: CoordinationReport | None = None

    async def analyze(
        self,
        session: AsyncSession,
        time_range: TimeRange | None = None,
    ) -> list[Finding]:
        findings, report = await self.coordinator.run(session, time_range=time_range)
        self.report = report
        return sorted(findings, key=lambda f: f.value.estimated_monthly_value, reverse=True)

    def top_actions(self, findings: list[Finding], limit: int | None = None) -> list[Finding]:
        return self.coordinator.top_actions(findings, limit)
