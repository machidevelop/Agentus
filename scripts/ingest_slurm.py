#!/usr/bin/env python3
"""Ingest Slurm cluster data into Natilah.

File-based (recommended — works off-cluster):
    python scripts/ingest_slurm.py --sacct sacct.txt --sinfo sinfo.txt [--run-analysis]

Live (runs sacct/sinfo directly on the cluster):
    python scripts/ingest_slurm.py --live --start 2026-08-22 --end 2026-08-29 [--run-analysis]

With Prometheus/DCGM telemetry:
    python scripts/ingest_slurm.py --sacct sacct.txt --sinfo sinfo.txt \
        --prometheus http://prometheus:9090 --start 2026-08-22 --end 2026-08-29
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from natilah.config import settings
from natilah.ingestion.slurm import SACCT_FORMAT, SINFO_FORMAT, SlurmDataSource
from natilah.models.database import get_session_factory, init_db


def run_sacct(start: str, end: str) -> str:
    cmd = [
        "sacct",
        f"--starttime={start}",
        f"--endtime={end}",
        f"--format={SACCT_FORMAT}",
        "--parsable2",
        "--allusers",
        "--allocations",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def run_sinfo() -> str:
    cmd = ["sinfo", f"--format={SINFO_FORMAT}", "--Node", "--noheader"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Slurm cluster data into Natilah.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="Run sacct/sinfo directly")
    group.add_argument("--sacct", type=str, help="Path to sacct --parsable2 output file")

    parser.add_argument("--sinfo", type=str, help="Path to sinfo output file")
    parser.add_argument("--squeue-dir", type=str, help="Directory of squeue snapshot files")
    parser.add_argument("--prometheus", type=str, help="Prometheus URL for DCGM telemetry")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--gpu-type", type=str, help="Override GPU type (e.g. A100-80GB)")
    parser.add_argument("--step", type=int, default=300, help="Prometheus query step in seconds")
    parser.add_argument("--run-analysis", action="store_true", help="Run analysis after ingestion")

    args = parser.parse_args()

    if args.live:
        if not args.start or not args.end:
            parser.error("--live requires --start and --end")
        print(f"Running sacct for {args.start} to {args.end}...")
        sacct_text = run_sacct(args.start, args.end)
        print("Running sinfo...")
        sinfo_text = run_sinfo()
    else:
        sacct_text = Path(args.sacct).read_text(encoding="utf-8")
        sinfo_text = Path(args.sinfo).read_text(encoding="utf-8") if args.sinfo else ""

    prom_start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc) if args.start else None
    prom_end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end else None

    source = SlurmDataSource(
        sacct_text=sacct_text,
        sinfo_text=sinfo_text,
        squeue_dir=args.squeue_dir,
        prometheus_url=args.prometheus,
        prometheus_start=prom_start,
        prometheus_end=prom_end,
        prometheus_step=args.step,
        gpu_type_override=args.gpu_type,
    )

    print(f"Initializing database: {settings.database_url}")
    await init_db()

    factory = get_session_factory()
    async with factory() as session:
        result = await source.ingest(session)

    print(f"\n[OK] Slurm ingestion complete!")
    print(f"  Nodes:       {result.nodes}")
    print(f"  GPUs:        {result.gpus}")
    print(f"  Jobs:        {result.jobs}")
    print(f"  Allocations: {result.allocations}")
    print(f"  Telemetry:   {result.samples} samples")
    print(f"  Decisions:   {result.decisions}")

    if args.run_analysis:
        print("\nRunning analysis pipeline...")
        from natilah.agents.gpu_allocation_agent import GPUAllocationAgent

        async with factory() as session:
            findings = await GPUAllocationAgent().analyze(session)
        print(f"\nFound {len(findings)} counterfactual opportunities.")
        print("=" * 80)
        for f in findings:
            conf = f"{f.confidence.level.value.upper()} ({f.confidence.score:.2f})"
            print(f"  {f.title:<34} {conf:<14} ${f.value.estimated_monthly_value:,.2f}/mo")
        print("=" * 80)
        print("Safety Mode: READ-ONLY (Production changes made: 0)")


if __name__ == "__main__":
    asyncio.run(main())
