#!/usr/bin/env python3
"""CLI script to run Natilah AI agent analysis on the cluster dataset."""

from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from natilah.agents.gpu_allocation_agent import GPUAllocationAgent
from natilah.config import settings
from natilah.models.database import get_session_factory, init_db


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run Natilah counterfactual analysis agent.")
    args = parser.parse_args()

    print(f"Connecting to database: {settings.database_url}")
    await init_db()

    print("Running GPUAllocationAgent counterfactual intelligence pipeline...")
    agent = GPUAllocationAgent()

    factory = get_session_factory()
    async with factory() as session:
        findings = await agent.analyze(session)

    print(f"\n[OK] Analysis complete! Found {len(findings)} counterfactual opportunities.")
    print("=" * 80)
    print(f"{'TITLE':<32} | {'CONFIDENCE':<12} | {'MONTHLY VALUE':<14} | {'ANNUAL VALUE':<14}")
    print("-" * 80)

    total_monthly = 0.0
    total_annual = 0.0
    for f in findings:
        conf_str = f"{f.confidence.level.value.upper()} ({f.confidence.score:.2f})"
        monthly = f"${f.value.estimated_monthly_value:,.2f}"
        annual = f"${f.value.estimated_annual_value:,.2f}"
        total_monthly += f.value.estimated_monthly_value
        total_annual += f.value.estimated_annual_value

        title = f.title[:30] + ".." if len(f.title) > 30 else f.title
        print(f"{title:<32} | {conf_str:<12} | {monthly:<14} | {annual:<14}")

    print("-" * 80)
    print(f"{'TOTAL POTENTIAL VALUE DISCOVERED':<32} | {'':<12} | {f'${total_monthly:,.2f}':<14} | {f'${total_annual:,.2f}':<14}")
    print("=" * 80)
    print("\nSafety Mode: READ-ONLY (Production changes made: 0)")


if __name__ == "__main__":
    asyncio.run(main())
