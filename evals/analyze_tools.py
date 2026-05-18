"""Analyze multi-step tool eval / autoresearch reports."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def analyze_report(data: dict, *, min_avg: float = 1.0) -> None:
    runs = data.get("runs_per_variant") or data.get("runs_per_transcript") or 2
    metric_key = f"mean_at_{runs}"
    mean_at = data.get(metric_key)
    if mean_at is None:
        mean_at = (data.get("mean_pass_rate") or 0) * runs

    print(f"Report model: {data.get('model')}  contract: {data.get('tool_contract')}")
    print(f"Subset: {data.get('subset')}  score_steps: {data.get('score_steps')}")
    print(f"Overall {metric_key}: {mean_at:.3f} / {runs}")
    print(f"mean_pass_rate: {data.get('mean_pass_rate')}")
    print(f"mean_step_pass_rate: {data.get('mean_step_pass_rate')}")
    print(f"tool_warning_rate: {data.get('tool_warning_rate')}")
    print(f"api_error_rate: {data.get('api_error_rate')}")
    print()

    summaries = data.get("case_summaries") or []
    if not summaries:
        variants = data.get("variants") or []
        print(f"Variants: {len(variants)} (no case_summaries; legacy report)")
        for v in variants[:10]:
            mark = "OK" if v.get("first_pass") else "FAIL"
            print(f"  [{mark}] {v.get('case_id')} pass_rate={v.get('pass_rate')}")
        return

    passing = [s for s in summaries if s.get(metric_key, 0) >= min_avg]
    print(f"Goal avg@{runs} >= {min_avg}: {len(passing)}/{len(summaries)} cases")
    print(f"  {'case_id':<36} {'cat':<14} {metric_key:<8} pass_rate")
    for s in summaries:
        mark = "FAIL" if s.get(metric_key, 0) < min_avg else "  ok"
        print(
            f"  [{mark}] {s['case_id']:<33} {s['category']:<14} "
            f"{s.get(metric_key, 0):<8} {s.get('pass_rate')}"
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=pathlib.Path, nargs="?", default=None)
    ap.add_argument("--min", type=float, default=1.0, help="Min avg@N per case to count as passing")
    ap.add_argument("--latest", action="store_true", help="Use latest autoresearch/runs/*/report.json")
    args = ap.parse_args()

    path = args.report
    if args.latest:
        runs = pathlib.Path(__file__).resolve().parent / "autoresearch" / "runs"
        candidates = sorted(runs.glob("*/report.json"))
        if not candidates:
            print("No autoresearch runs found", file=sys.stderr)
            raise SystemExit(1)
        path = candidates[-1]

    if path is None or not path.exists():
        print("Report path required", file=sys.stderr)
        raise SystemExit(2)

    data = json.loads(path.read_text())
    print(f"Report: {path}\n")
    analyze_report(data, min_avg=args.min)


if __name__ == "__main__":
    main()
