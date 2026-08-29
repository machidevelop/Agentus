#!/usr/bin/env python3
"""Ingest Kubernetes cluster data into Natilah.

Snapshot mode (recommended — works off-cluster):
    python scripts/ingest_kubernetes.py --snapshot-dir ./k8s-data/ [--run-analysis]

    Expected files in snapshot dir:
        nodes.json       — kubectl get nodes -o json
        pods.json        — kubectl get pods -A -o json
        events.json      — kubectl get events -A -o json
        kueue_workloads.json — kubectl get workloads.kueue.x-k8s.io -A -o json (optional)

Live mode (reads from cluster via kubeconfig):
    python scripts/ingest_kubernetes.py --live [--namespace gpu-workloads] [--run-analysis]

With Prometheus/DCGM telemetry:
    python scripts/ingest_kubernetes.py --snapshot-dir ./k8s-data/ \
        --prometheus http://prometheus:9090 --start 2026-08-22 --end 2026-08-29
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from natilah.config import settings
from natilah.ingestion.kubernetes import KubernetesDataSource
from natilah.models.database import get_session_factory, init_db


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Kubernetes cluster data into Natilah.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="Read from live cluster via kubeconfig")
    group.add_argument("--snapshot-dir", type=str, help="Directory with kubectl JSON dumps")

    parser.add_argument("--kubeconfig", type=str, help="Path to kubeconfig file")
    parser.add_argument("--context", type=str, help="Kubernetes context name")
    parser.add_argument("--namespace", type=str, help="Filter to specific namespace")
    parser.add_argument("--prometheus", type=str, help="Prometheus URL for DCGM telemetry")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--gpu-type", type=str, help="Override GPU type (e.g. A100-80GB)")
    parser.add_argument("--step", type=int, default=300, help="Prometheus query step in seconds")
    parser.add_argument("--run-analysis", action="store_true", help="Run analysis after ingestion")

    args = parser.parse_args()

    prom_start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc) if args.start else None
    prom_end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end else None

    if args.live:
        print("Connecting to Kubernetes cluster...")
        source = await KubernetesDataSource.from_live_cluster(
            kubeconfig=args.kubeconfig,
            context=args.context,
            namespace=args.namespace,
            prometheus_url=args.prometheus,
            prometheus_start=prom_start,
            prometheus_end=prom_end,
            prometheus_step=args.step,
            gpu_type_override=args.gpu_type,
        )
    else:
        print(f"Loading snapshots from {args.snapshot_dir}...")
        source = KubernetesDataSource.from_snapshot_dir(
            args.snapshot_dir,
            prometheus_url=args.prometheus,
            prometheus_start=prom_start,
            prometheus_end=prom_end,
            prometheus_step=args.step,
            gpu_type_override=args.gpu_type,
            namespace_filter=args.namespace,
        )

    print(f"Initializing database: {settings.database_url}")
    await init_db()

    factory = get_session_factory()
    async with factory() as session:
        result = await source.ingest(session)

    print(f"\n[OK] Kubernetes ingestion complete!")
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
