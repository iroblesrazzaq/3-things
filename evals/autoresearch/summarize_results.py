#!/usr/bin/env python3
"""Print autoresearch progress from results.tsv and latest run summary."""
from __future__ import annotations

import argparse
import json
import pathlib

AUTORESEARCH = pathlib.Path(__file__).resolve().parent
RESULTS_TSV = AUTORESEARCH / "results.tsv"
RUNS_DIR = AUTORESEARCH / "runs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=20)
    args = ap.parse_args()

    if RESULTS_TSV.exists():
        lines = RESULTS_TSV.read_text().strip().splitlines()
        print("=== results.tsv (last entries) ===")
        for line in lines[:1] + lines[-args.tail :]:
            print(line)
        print()

    runs = sorted(RUNS_DIR.glob("*/summary.json"))
    if runs:
        latest = runs[-1]
        print(f"=== latest run: {latest.parent.name} ===")
        print(json.dumps(json.loads(latest.read_text()), indent=2))
    else:
        print("No runs yet under autoresearch/runs/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
