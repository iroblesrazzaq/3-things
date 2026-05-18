"""Aggregate multi-step tool eval reports (avg@N, case/category summaries)."""
from __future__ import annotations

from runner import HALLUCINATION_CODES


def _hallucination_in_run(run) -> bool:
    return any(r in HALLUCINATION_CODES for r in (run.reasons or []))


def aggregate_tool_reports(
    reports: list,
    *,
    runs_per_variant: int,
) -> dict:
    """Build case_summaries, category_summaries, and top-level metrics."""
    if not reports:
        return {
            "runs_per_variant": runs_per_variant,
            "total_variants": 0,
            "mean_pass_rate": 0.0,
            f"mean_at_{runs_per_variant}": 0.0,
            "mean_step_pass_rate": 0.0,
            "tool_warning_rate": 0.0,
            "api_error_rate": 0.0,
            "case_summaries": [],
            "category_summaries": [],
        }

    total_steps_scored = 0
    total_steps_passed = 0
    total_warnings = 0
    total_api_errors = 0

    for r in reports:
        total_warnings += r.tool_warning_count
        for run in r.runs:
            if run.error:
                total_api_errors += 1
        if r.step_results:
            for s in r.step_results:
                total_steps_scored += 1
                if s.passed:
                    total_steps_passed += 1

    overall_pass = sum(r.pass_rate for r in reports) / len(reports)
    mean_at_n = overall_pass * runs_per_variant

    case_ids: list[str] = []
    seen: set[str] = set()
    for r in reports:
        if r.case_id not in seen:
            case_ids.append(r.case_id)
            seen.add(r.case_id)

    case_summaries = []
    for cid in case_ids:
        vs = [r for r in reports if r.case_id == cid]
        avg = sum(v.pass_rate for v in vs) / len(vs)
        first_pass = sum(1 for v in vs if v.first_pass) / len(vs)
        hall = sum(
            1
            for v in vs
            for run in v.runs
            if _hallucination_in_run(run)
        )
        case_summaries.append(
            {
                "case_id": cid,
                "category": vs[0].category,
                "variants": len(vs),
                "pass_rate": round(avg, 3),
                f"avg_at_{runs_per_variant}": round(avg * runs_per_variant, 2),
                "first_pass_rate": round(first_pass, 3),
                "hallucination_runs": hall,
            }
        )
    case_summaries.sort(key=lambda s: s["pass_rate"])

    categories = sorted({r.category for r in reports})
    category_summaries = []
    for cat in categories:
        vs = [r for r in reports if r.category == cat]
        mean = sum(v.pass_rate for v in vs) / len(vs)
        category_summaries.append(
            {
                "category": cat,
                "variant_count": len(vs),
                "mean_pass_rate": round(mean, 3),
                f"mean_at_{runs_per_variant}": round(mean * runs_per_variant, 2),
                "first_pass_rate": round(sum(1 for v in vs if v.first_pass) / len(vs), 3),
            }
        )

    step_mean = (
        total_steps_passed / total_steps_scored if total_steps_scored else 0.0
    )
    total_run_slots = sum(len(r.runs) for r in reports)
    warning_rate = (
        total_warnings / total_steps_scored if total_steps_scored else 0.0
    )
    api_error_rate = (
        total_api_errors / total_run_slots if total_run_slots else 0.0
    )

    return {
        "runs_per_variant": runs_per_variant,
        "total_variants": len(reports),
        "mean_pass_rate": round(overall_pass, 3),
        f"mean_at_{runs_per_variant}": round(mean_at_n, 3),
        "mean_step_pass_rate": round(step_mean, 3),
        "tool_warning_rate": round(warning_rate, 3),
        "api_error_rate": round(api_error_rate, 3),
        "case_summaries": case_summaries,
        "category_summaries": category_summaries,
    }
