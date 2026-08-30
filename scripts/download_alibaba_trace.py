#!/usr/bin/env python3
"""Download Alibaba GPU Cluster Trace 2023 data.

Fetches the public PAI trace files from the alibaba/clusterdata repository
and extracts them into data/alibaba_trace_2023/.

Usage:
    python scripts/download_alibaba_trace.py [--output-dir DIR] [--year 2023]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

TRACE_URLS = {
    "2020": {
        "base": "https://raw.githubusercontent.com/alibaba/clusterdata/master/cluster-trace-gpu-v2020/data/",
        "files": [
            "pai_machine_spec.csv",
            "pai_job_table.header",
            "pai_instance_table.header",
            "pai_sensor_table.header",
            "pai_group_tag_table.header",
        ],
        "sharded": {
            "pai_job_table": 15,
            "pai_instance_table": 15,
            "pai_sensor_table": 15,
            "pai_group_tag_table": 15,
        },
        "note": (
            "The 2020 trace is sharded into numbered CSVs. Headers are separate files.\n"
            "After download, you may need to prepend headers to each shard."
        ),
    },
    "2023": {
        "base": "https://raw.githubusercontent.com/alibaba/clusterdata/master/cluster-trace-gpu-v2023/data/",
        "files": [
            "pai_machine_spec.csv",
            "pai_job_table.csv",
            "pai_instance_table.csv",
            "pai_sensor_table.csv",
            "pai_group_tag_table.csv",
        ],
        "sharded": {},
        "note": (
            "The 2023 trace may be hosted on Alibaba Cloud OSS or as GitHub releases.\n"
            "If direct download fails, check: https://github.com/alibaba/clusterdata\n"
            "for the latest links and download instructions.\n"
            "Alternative: download manually and place files in the output directory."
        ),
    },
}


def download_file(url: str, dest: Path, desc: str = "") -> bool:
    if dest.exists():
        print(f"  [skip] {desc or dest.name} (already exists)")
        return True
    print(f"  [download] {desc or dest.name} ...")
    try:
        urllib.request.urlretrieve(url, str(dest))
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  [ok] {dest.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"  [FAIL] {dest.name}: {e}")
        return False


def try_git_clone_sparse(year: str, output_dir: Path) -> bool:
    """Try sparse checkout of just the trace data directory."""
    repo_url = "https://github.com/alibaba/clusterdata.git"
    subdir = f"cluster-trace-gpu-v{year}/data"
    clone_dir = output_dir / ".clone_tmp"

    print(f"Attempting sparse checkout of {subdir} ...")
    try:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--sparse", repo_url, str(clone_dir)],
            check=True, capture_output=True, text=True, timeout=120,
        )
        subprocess.run(
            ["git", "sparse-checkout", "set", subdir],
            cwd=str(clone_dir), check=True, capture_output=True, text=True, timeout=60,
        )
        src = clone_dir / subdir
        if src.exists():
            for f in src.iterdir():
                dest = output_dir / f.name
                if not dest.exists():
                    f.rename(dest)
            print(f"[ok] Sparse checkout succeeded")
            return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"Sparse checkout failed: {e}")
    finally:
        import shutil
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Alibaba GPU Cluster Trace")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--year", type=str, default="2023", choices=["2020", "2023"])
    parser.add_argument("--method", type=str, default="auto", choices=["auto", "direct", "git"])
    args = parser.parse_args()

    year = args.year
    output_dir = Path(args.output_dir) if args.output_dir else Path(f"data/alibaba_trace_{year}")
    output_dir.mkdir(parents=True, exist_ok=True)

    trace = TRACE_URLS.get(year)
    if not trace:
        print(f"Unknown trace year: {year}")
        sys.exit(1)

    print(f"Alibaba GPU Cluster Trace {year}")
    print(f"Output: {output_dir.resolve()}")
    print(f"Note: {trace['note']}")
    print()

    if args.method in ("auto", "git"):
        if try_git_clone_sparse(year, output_dir):
            _verify(output_dir, year)
            return

    if args.method in ("auto", "direct"):
        base = trace["base"]
        ok = 0
        fail = 0
        for fname in trace["files"]:
            if download_file(base + fname, output_dir / fname, fname):
                ok += 1
            else:
                fail += 1

        for prefix, count in trace.get("sharded", {}).items():
            for i in range(count):
                fname = f"{prefix}_{i}.csv"
                if download_file(base + fname, output_dir / fname, fname):
                    ok += 1
                else:
                    fail += 1

        print(f"\nDownloaded {ok} files, {fail} failures")

    _verify(output_dir, year)


def _verify(output_dir: Path, year: str) -> None:
    print("\n--- Verification ---")
    expected = ["pai_machine_spec", "pai_job_table", "pai_instance_table"]
    for prefix in expected:
        matches = list(output_dir.glob(f"{prefix}*"))
        if matches:
            total_size = sum(f.stat().st_size for f in matches)
            print(f"  [ok] {prefix}: {len(matches)} file(s), {total_size / (1024*1024):.1f} MB total")
        else:
            print(f"  [MISSING] {prefix}: no files found")

    sensor = list(output_dir.glob("pai_sensor_table*"))
    if sensor:
        total_size = sum(f.stat().st_size for f in sensor)
        print(f"  [ok] pai_sensor_table: {len(sensor)} file(s), {total_size / (1024*1024):.1f} MB total")
    else:
        print(f"  [warn] pai_sensor_table: not found (will use synthetic utilization)")

    print(f"\nTrace directory ready: {output_dir.resolve()}")
    print(f"Run validation: python scripts/validate_alibaba.py --trace-dir {output_dir}")


if __name__ == "__main__":
    main()
