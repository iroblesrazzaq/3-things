"""Re-score an existing report file using the current scorer.py logic.
No new API calls. Useful when scorer rules change.

Usage:
    python rescore.py reports/v7_repair_expanded.json reports/v7_repair_expanded_rescored.json
"""
from __future__ import annotations

import argparse
import json
import pathlib

from scorer import Draft, FailureReason, score

HALLUCINATION_CODES = {
    FailureReason.INVENTED_SELECTED.value,
    FailureReason.INVENTED_EXTRA.value,
    FailureReason.OVER_SPECIFIC_REWRITE.value,
    FailureReason.NO_TASK_FALSE_POSITIVE.value,
}

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=pathlib.Path)
    ap.add_argument("output", type=pathlib.Path)
    args = ap.parse_args()

    fixture = {c["id"]: c for c in json.loads(FIXTURE.read_text())["cases"]}
    r = json.loads(args.input.read_text())
    runs_per = r["runs_per_transcript"]

    for v in r["variants"]:
        case = fixture.get(v["case_id"])
        if case is None:
            continue
        new_runs = []
        for run in v["runs"]:
            draft = None
            if run["selected_tasks"] or run["extra_candidates"]:
                draft = Draft(
                    selected_tasks=run["selected_tasks"],
                    extra_candidates=run["extra_candidates"],
                    detected_more_than_three=run["detected_more_than_three"],
                    contains_actionable_tasks=True,
                )
            err = run.get("error")
            s = score(case, draft, err)
            run["passed"] = s.passed
            run["reasons"] = [r.value for r in s.reasons]
            new_runs.append(run)
        v["runs"] = new_runs
        passes = sum(1 for run in new_runs if run["passed"])
        v["pass_rate"] = passes / runs_per
        v["first_pass"] = new_runs[0]["passed"] if new_runs else False
        v["hallucination_run_count"] = sum(
            1 for run in new_runs if any(rs in HALLUCINATION_CODES for rs in run["reasons"])
        )

    # Recompute case summaries
    case_ids = []
    seen = set()
    for v in r["variants"]:
        if v["case_id"] not in seen:
            case_ids.append(v["case_id"])
            seen.add(v["case_id"])
    new_summaries = []
    for cid in case_ids:
        vs = [v for v in r["variants"] if v["case_id"] == cid]
        avg = sum(v["pass_rate"] for v in vs) / len(vs)
        first_pass = sum(1 for v in vs if v["first_pass"]) / len(vs)
        new_summaries.append({
            "case_id": cid,
            "category": vs[0]["category"],
            "variants": len(vs),
            "pass_rate": round(avg, 3),
            f"avg_at_{runs_per}": round(avg * runs_per, 2),
            "first_pass_rate": round(first_pass, 3),
            "hallucination_runs": sum(v["hallucination_run_count"] for v in vs),
        })
    new_summaries.sort(key=lambda s: s["pass_rate"])
    r["case_summaries"] = new_summaries

    # Recompute category summaries
    cats = sorted({v["category"] for v in r["variants"]})
    new_cats = []
    for cat in cats:
        vs = [v for v in r["variants"] if v["category"] == cat]
        mean = sum(v["pass_rate"] for v in vs) / len(vs)
        new_cats.append({
            "category": cat,
            "variant_count": len(vs),
            "mean_pass_rate": round(mean, 3),
            f"mean_at_{runs_per}": round(mean * runs_per, 2),
            "first_pass_rate": round(sum(1 for v in vs if v["first_pass"]) / len(vs), 3),
            "hallucination_runs": sum(v["hallucination_run_count"] for v in vs),
        })
    r["category_summaries"] = new_cats

    overall = sum(v["pass_rate"] for v in r["variants"]) / len(r["variants"])
    r["mean_pass_rate"] = round(overall, 3)
    r[f"mean_at_{runs_per}"] = round(overall * runs_per, 2)

    args.output.write_text(json.dumps(r, indent=2))
    print(f"Re-scored {len(r['variants'])} variants.")
    print(f"Overall mean@{runs_per}: {r[f'mean_at_{runs_per}']:.2f} / {runs_per}  ({r['mean_pass_rate'] * 100:.1f}%)")


if __name__ == "__main__":
    main()
