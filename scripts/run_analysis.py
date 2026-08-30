#!/usr/bin/env python3
"""Run the coordinated multi-agent analysis and print the top actions."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from natilah.agents.coordinator import AgentCoordinator
from natilah.config import settings
from natilah.models.database import get_session_factory, init_db


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run Natilah counterfactual analysis agents.")
    parser.add_argument("--top", type=int, default=10, help="How many ranked actions to print")
    parser.add_argument("--no-llm", action="store_true", help="Deterministic candidates only")
    args = parser.parse_args()

    print(f"Connecting to database: {settings.database_url}")
    await init_db()

    coordinator = AgentCoordinator(top_n=args.top, use_llm=False if args.no_llm else None)
    print("Running specialized agents: " + ", ".join(a.name for a in coordinator.agents))

    factory = get_session_factory()
    async with factory() as session:
        findings, report = await coordinator.run(session)

    print("\nPER-AGENT")
    print("-" * 108)
    print(
        f"{'AGENT':<32} | {'OBS':>5} | {'CAND':>5} | {'REJECTED':>8} | {'FINDINGS':>8} | "
        f"{'GPU-HOURS':>10} | {'MONTHLY $':>12}"
    )
    for summary in report.agents:
        rejected = summary.candidates_rejected_infeasible + summary.candidates_rejected_no_gain
        print(
            f"{summary.agent_name:<32} | {summary.observations:>5} | {summary.candidates_generated:>5} | "
            f"{rejected:>8} | {summary.findings:>8} | {summary.claimed_gpu_hours:>10.1f} | "
            f"${summary.claimed_monthly_value:>11,.0f}"
        )

    print("\nCOORDINATION")
    print("-" * 108)
    print(f"Findings from agents:       {report.total_findings}")
    print(f"Conflicts resolved:         {report.conflicts_resolved}")
    print(f"Suppressed (dup/conflict):  {report.suppressed_findings}")
    print(f"Duplicate GPU-hours removed:{report.duplicate_gpu_hours_removed:>12,.1f}")
    print(
        f"GPU-hours claimed -> credited: {report.claimed_gpu_hours:,.1f} -> "
        f"{report.attributed_gpu_hours:,.1f}"
    )
    print(
        f"Monthly value claimed -> credited: ${report.claimed_monthly_value:,.0f} -> "
        f"${report.attributed_monthly_value:,.0f}"
    )
    print(f"Annual value credited:      ${report.attributed_annual_value:,.0f}")

    print(f"\nTOP {args.top} ACTIONS (each independently validated)")
    print("=" * 108)
    for finding in coordinator.top_actions(findings, args.top):
        attribution = finding.attribution
        print(f"\n#{attribution.rank}  [{finding.agent_name}]  {finding.title}")
        print(f"  Observed:    {finding.description}")
        print(f"  Alternative: {finding.alternative.description}")
        print(f"  Action:      {finding.recommended_action}")
        print(
            f"  Return:      {attribution.attributed_gpu_hours:,.1f} GPU-h credited "
            f"({attribution.claimed_gpu_hours:,.1f} claimed) | "
            f"${attribution.attributed_monthly_value:,.0f}/mo | "
            f"${attribution.attributed_annual_value:,.0f}/yr"
        )
        print(
            f"  Confidence:  {finding.confidence.level.value} ({finding.confidence.score:.2f}) | "
            f"candidates evaluated: {len(finding.candidates_considered)} | "
            f"resolution: {attribution.resolution.value}"
        )

    print("\n" + "=" * 108)
    print("Safety mode: READ-ONLY. Production changes made: 0. Execution stays human-approved.")


if __name__ == "__main__":
    asyncio.run(main())
