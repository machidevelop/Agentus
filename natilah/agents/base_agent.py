"""Agent abstraction. Agents observe, propose counterfactuals, and never execute."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from natilah.models.domain import Finding, TimeRange
from natilah.safety.guards import SafetyGuard


class InfrastructureAgent(ABC):
    """Base class for Natilah intelligence agents.

    Workflow:
    1. Observe the decision the existing infrastructure actually made (X)
    2. Reconstruct cluster context around that decision
    3. Identify credible alternative decisions (Y) — the agent's job
    4. Validate that Y was operationally feasible at that moment
    5. Compare X vs Y and calculate the economic difference

    Agents do not schedule, pack, or apply changes. Algorithms such as
    bin-packing may be invoked as tools; they do not define the agent.
    """

    name: str
    domain: str

    def __init__(self):
        self.safety = SafetyGuard()

    @abstractmethod
    async def analyze(self, session: AsyncSession, time_range: TimeRange | None = None) -> list[Finding]:
        ...
