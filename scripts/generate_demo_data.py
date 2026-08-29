#!/usr/bin/env python3
"""CLI script to generate synthetic GPU cluster dataset and persist into Natilah database."""

from __future__ import annotations

import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from natilah.config import settings
from natilah.ingestion.synthetic import SyntheticDataGenerator
from natilah.models.database import get_session_factory, init_db


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic GPU cluster dataset for Natilah V1.")
    parser.add_argument("--nodes", type=int, default=64, help="Number of nodes in cluster (default: 64)")
    parser.add_argument("--gpus-per-node", type=int, default=8, help="GPUs per node (default: 8)")
    parser.add_argument("--jobs", type=int, default=500, help="Total jobs over time window (default: 500)")
    parser.add_argument("--hours", type=int, default=24, help="Time window in hours (default: 24)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")

    args = parser.parse_args()

    print(f"Initializing database at: {settings.database_url}")
    await init_db()

    print(f"Generating dataset: {args.nodes} nodes, {args.gpus_per_node} GPUs/node, {args.jobs} jobs over {args.hours}h...")
    generator = SyntheticDataGenerator(
        num_nodes=args.nodes,
        gpus_per_node=args.gpus_per_node,
        num_jobs=args.jobs,
        time_window_hours=args.hours,
        seed=args.seed,
    )

    factory = get_session_factory()
    async with factory() as session:
        result = await generator.ingest(session)

    print("\n[OK] Ingestion complete!")
    print(f"  • Nodes:       {result.nodes}")
    print(f"  • GPUs:        {result.gpus}")
    print(f"  • Jobs:        {result.jobs}")
    print(f"  • Allocations: {result.allocations}")
    print(f"  • Telemetry:   {result.samples} utilization samples")
    print(f"  • Decisions:   {result.decisions} scheduler decisions")


if __name__ == "__main__":
    asyncio.run(main())
