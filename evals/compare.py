"""Compare multiple eval reports head-to-head. Spots regressions per-case.

Usage:
    python compare.py reports/v0.json reports/v1.json reports/v2.json
    python compare.py reports/*.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("reports", nargs="+", type=pathlib.Path)
    ap.add_argument("--metric", default="pass_rate", choices=["pass_rate", "first_pass_rate", "hallucination_runs"])
    args = ap.parse_args()

    reports = []
    for p in args.reports:
        if not p.exists():
            print(f"missing: {p}", file=sys.stderr)
            sys.exit(2)
        r = load(p)
        r["_label"] = p.stem
        reports.append(r)

    # Collect all case IDs across reports.
    all_ids: list[str] = []
    seen: set[str] = set()
    for r in reports:
        for s in r["case_summaries"]:
            if s["case_id"] not in seen:
                all_ids.append(s["case_id"])
                seen.add(s["case_id"])

    # Build matrix
    runs_per = reports[0]["runs_per_transcript"]
    metric_label = f"avg_at_{runs_per}" if args.metric == "pass_rate" else args.metric

    print(f"\nMetric: {metric_label} (higher better, except hallucination_runs which is lower better)\n")
    header = f"  {'case_id':<35} " + " ".join(f"{r['_label'][:14]:<14}" for r in reports) + "  best"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for cid in all_ids:
        row_vals: list[float | None] = []
        for r in reports:
            s = next((x for x in r["case_summaries"] if x["case_id"] == cid), None)
            if s is None:
                row_vals.append(None)
            else:
                if args.metric == "pass_rate":
                    row_vals.append(float(s[f"avg_at_{runs_per}"]))
                else:
                    row_vals.append(float(s[args.metric]))
        valid = [v for v in row_vals if v is not None]
        if not valid:
            continue
        if args.metric == "hallucination_runs":
            best_val = min(valid)
        else:
            best_val = max(valid)
        best_idx = row_vals.index(best_val)
        cells = []
        for i, v in enumerate(row_vals):
            if v is None:
                cells.append(f"{'-':<14}")
            else:
                marker = "*" if i == best_idx and len(set(valid)) > 1 else " "
                cells.append(f"{marker}{v:<13.2f}")
        print(f"  {cid:<35} " + " ".join(cells) + f"  {reports[best_idx]['_label']}")

    # Overall row
    overall_vals: list[float] = []
    for r in reports:
        if args.metric == "pass_rate":
            overall_vals.append(float(r[f"mean_at_{runs_per}"]))
        elif args.metric == "first_pass_rate":
            # compute from variants
            vs = r["variants"]
            overall_vals.append(sum(1 for v in vs if v["first_pass"]) / len(vs))
        else:
            vs = r["variants"]
            overall_vals.append(sum(v["hallucination_run_count"] for v in vs))
    best = min(overall_vals) if args.metric == "hallucination_runs" else max(overall_vals)
    best_idx = overall_vals.index(best)
    print()
    print(f"  {'OVERALL':<35} " + " ".join(
        f"{'*' if i == best_idx and len(set(overall_vals)) > 1 else ' '}{v:<13.2f}"
        for i, v in enumerate(overall_vals)
    ))


if __name__ == "__main__":
    main()
