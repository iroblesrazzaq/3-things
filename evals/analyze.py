"""Quick analyzer for a single report: scores vs the 3.5/5 goal, drilling into worst variants.

Usage:
    python analyze.py reports/v7_repair_expanded.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=pathlib.Path)
    ap.add_argument("--min", type=float, default=3.5, help="Goal: cases must be ≥ this avg@N")
    ap.add_argument("--show-failures", type=int, default=2, help="How many failing runs to show per failing case")
    args = ap.parse_args()

    r = json.loads(args.report.read_text())
    runs = r["runs_per_transcript"]
    metric = f"avg_at_{runs}"
    print(f"Report: {args.report}")
    print(f"Model: {r['model']}  Temp: {r['temperature']}  Runs/variant: {runs}")
    print(f"Overall mean@{runs}: {r[f'mean_at_{runs}']:.2f} / {runs}  ({r['mean_pass_rate'] * 100:.1f}%)")
    print()

    below = [s for s in r["case_summaries"] if s[metric] < args.min]
    above = [s for s in r["case_summaries"] if s[metric] >= args.min]

    print(f"Goal: ≥ {args.min}/{runs}.  Passing: {len(above)}/{len(r['case_summaries'])}.  Below: {len(below)}")
    print()
    print("Cases (worst -> best):")
    print(f"  {'case_id':<36} {'category':<14} {'avg@N':<7} {'first':<6} {'hall':<5}")
    for s in r["case_summaries"]:
        mark = "FAIL" if s[metric] < args.min else "  ok"
        print(f"  [{mark}] {s['case_id']:<33} {s['category']:<14} {s[metric]:<6} {s['first_pass_rate']:<6} {s['hallucination_runs']:<5}")

    if below and args.show_failures > 0:
        print()
        print("=" * 70)
        print("Failing-case detail:")
        for s in below:
            cid = s["case_id"]
            print()
            print(f"--- {cid}  ({s['category']})  avg@{runs}={s[metric]} ---")
            variants = [v for v in r["variants"] if v["case_id"] == cid]
            for v in variants:
                fails = [run for run in v["runs"] if not run["passed"]]
                if not fails:
                    continue
                print(f"  v{v['transcript_index'] + 1}  pass_rate={v['pass_rate']:.2f}  transcript={v['transcript']!r}")
                for run in fails[: args.show_failures]:
                    print(f"     sel={run['selected_tasks']}  ext={run['extra_candidates']}  ovf={run['detected_more_than_three']}")
                    print(f"     reasons={run['reasons']}  err={run['error']}")


if __name__ == "__main__":
    main()
