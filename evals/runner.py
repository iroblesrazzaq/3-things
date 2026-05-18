"""Eval runner. Loads voice_extraction_cases.json, runs the proxy model N times per
transcript variant, scores against the spec, writes a JSON report.

Usage:
    python runner.py --prompt prompts/v0_swift_baseline.txt --runs 5 --out reports/v0.json
    python runner.py --prompt prompts/v0_swift_baseline.txt --runs 5 --cases literal_one_email overflow_four_clean
    python runner.py --prompt prompts/v1_strict.txt --runs 5 --subset diagnostic --concurrency 8
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import pathlib
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from extractor import Extractor, ExtractorConfig
from scorer import AttemptScore, Draft, FailureReason, score

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"

HALLUCINATION_CODES = {
    FailureReason.INVENTED_SELECTED.value,
    FailureReason.INVENTED_EXTRA.value,
    FailureReason.OVER_SPECIFIC_REWRITE.value,
    FailureReason.NO_TASK_FALSE_POSITIVE.value,
}

# Diagnostic subset: one representative case from each major failure mode.
# Use for fast iteration; expand to full fixture only at the end.
DIAGNOSTIC_SUBSET = [
    "literal_three_store_park_food",  # baseline
    "overflow_four_clean",             # overflow detection
    "correction_never_mind_single",    # correction handling
    "no_task_testing",                 # false-positive guard
    "inference_store_only",            # inference trap
    "duplicate_email_sam",             # dedup
    "vague_taxes",                     # preserve vague
]

# Expanded subset: 12 cases hitting every category at least once (5 extra cases
# beyond diagnostic). Use as the second checkpoint between diagnostic and full fixture.
EXPANDED_SUBSET = DIAGNOSTIC_SUBSET + [
    "overflow_six_messy",                # 6-task overflow
    "correction_replace_call_with_text", # replacement correction
    "substeps_launch_email",             # substep -> parent collapse
    "future_tomorrow_exclude",           # future-day exclusion
    "negative_no_twitter",               # negative commitment
]

# Edge cases added for multi-step live eval + SFT dataset (beyond expanded).
EDGE_CASE_SUBSET = [
    "correction_forget_everything",
    "correction_park_to_store_direct",
    "overflow_then_drop_fourth",
    "no_task_then_one_task",
    "duplicate_pay_rent_thrice",
    "literal_exactly_three_no_overflow",
    "negative_plus_positive",
    "inference_doctor_ramble",
    "substeps_incremental_launch",
    "vague_taxes_not_specific",
    "future_intraday_correction",
]

FULL_LIVE_SUBSET = sorted(set(EXPANDED_SUBSET + EDGE_CASE_SUBSET))

# Cases where per-step fragment signal matters most (corrections / mid-utterance edits).
CORRECTION_ABLATION_SUBSET = [
    "correction_never_mind_single",
    "correction_replace_call_with_text",
    "correction_remove_one_keep_others",
    "correction_park_to_store_direct",
    "correction_forget_everything",
    "overflow_then_drop_fourth",
    "future_intraday_correction",
]

# Representative subset for overnight autoresearch (variant 0, avg@2).
AUTORESEARCH_SUBSET = [
    "literal_three_store_park_food",
    "overflow_four_clean",
    "correction_never_mind_single",
    "correction_replace_call_with_text",
    "correction_park_to_store_direct",
    "no_task_testing",
    "duplicate_email_sam",
    "overflow_then_drop_fourth",
]


@dataclass
class RunOutcome:
    passed: bool
    reasons: list[str]
    selected_tasks: list[str]
    extra_candidates: list[str]
    detected_more_than_three: bool
    error: str | None


@dataclass
class VariantReport:
    case_id: str
    category: str
    transcript_index: int
    transcript: str
    runs: list[RunOutcome]
    pass_rate: float
    first_pass: bool
    hallucination_run_count: int


def _outcome(draft: Draft | None, err: str | None, attempt: AttemptScore) -> RunOutcome:
    return RunOutcome(
        passed=attempt.passed,
        reasons=[r.value for r in attempt.reasons],
        selected_tasks=draft.selected_tasks if draft else [],
        extra_candidates=draft.extra_candidates if draft else [],
        detected_more_than_three=draft.detected_more_than_three if draft else False,
        error=err,
    )


def _run_one(extractor: Extractor, case: dict, transcript: str) -> RunOutcome:
    draft, err = extractor.extract(transcript)
    attempt = score(case, draft, err)
    return _outcome(draft, err, attempt)


def run_eval(
    *,
    prompt_path: pathlib.Path,
    runs_per_transcript: int,
    case_filter: set[str] | None,
    model: str,
    temperature: float,
    concurrency: int = 8,
    variants_per_case: int | None = None,
) -> dict:
    prompt_template = prompt_path.read_text()
    fixture = json.loads(FIXTURE.read_text())
    cases = fixture["cases"]
    if case_filter:
        cases = [c for c in cases if c["id"] in case_filter]
        if not cases:
            print(f"No cases match {case_filter}", file=sys.stderr)
            sys.exit(2)
    if variants_per_case is not None:
        # Take the first N variants of each case (variants 0 = clean wording, 1 = filler, etc.)
        cases = [
            {**c, "transcriptVariants": c["transcriptVariants"][:variants_per_case]}
            for c in cases
        ]

    extractor = Extractor(
        prompt_template,
        ExtractorConfig(model=model, temperature=temperature, repair=getattr(run_eval, "_repair", False)),
    )

    # Flatten all jobs so we can stream them through one thread pool.
    jobs: list[tuple[int, dict, int, str, int]] = []  # (global_idx, case, ti, transcript, run_idx)
    job_keys: dict[int, tuple[str, int, int]] = {}
    idx = 0
    for case in cases:
        for ti, transcript in enumerate(case["transcriptVariants"]):
            for r in range(runs_per_transcript):
                jobs.append((idx, case, ti, transcript, r))
                job_keys[idx] = (case["id"], ti, r)
                idx += 1
    total = len(jobs)

    results: dict[tuple[str, int, int], RunOutcome] = {}
    started = time.time()
    done_counter = {"n": 0}

    def tick(label: str) -> None:
        done_counter["n"] += 1
        elapsed = time.time() - started
        pct = done_counter["n"] / total * 100 if total else 0
        rate = done_counter["n"] / elapsed if elapsed > 0 else 0
        print(f"  [{done_counter['n']:>4}/{total} {pct:5.1f}%  {rate:5.1f}/s]  {label}", file=sys.stderr)

    partial_path = pathlib.Path(getattr(run_eval, "_partial_path", "reports/_partial.json"))
    partial_path.parent.mkdir(parents=True, exist_ok=True)

    def _dump_partial() -> None:
        payload = {
            "in_progress": True,
            "completed": len(results),
            "total": total,
            "runs_per_transcript": runs_per_transcript,
            "results": {
                f"{cid}|v{ti}|r{ri}": asdict(o) for (cid, ti, ri), o in results.items()
            },
        }
        partial_path.write_text(json.dumps(payload, indent=2))

    with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(_run_one, extractor, j[1], j[3]): j for j in jobs}
        for fut in cf.as_completed(futures):
            j = futures[fut]
            try:
                out = fut.result()
            except Exception as e:  # noqa: BLE001
                out = RunOutcome(passed=False, reasons=["runner_error"], selected_tasks=[], extra_candidates=[], detected_more_than_three=False, error=f"{type(e).__name__}:{e}")
            results[(j[1]["id"], j[2], j[4])] = out
            tick(f"{j[1]['id']} v{j[2] + 1} r{j[4] + 1}")
            if len(results) % 30 == 0:
                _dump_partial()

    variants: list[VariantReport] = []
    for case in cases:
        for ti, transcript in enumerate(case["transcriptVariants"]):
            outcomes = [results[(case["id"], ti, r)] for r in range(runs_per_transcript)]
            passes = sum(1 for o in outcomes if o.passed)
            hall_runs = sum(1 for o in outcomes if any(r in HALLUCINATION_CODES for r in o.reasons))
            variants.append(
                VariantReport(
                    case_id=case["id"],
                    category=case["category"],
                    transcript_index=ti,
                    transcript=transcript,
                    runs=outcomes,
                    pass_rate=passes / runs_per_transcript,
                    first_pass=outcomes[0].passed if outcomes else False,
                    hallucination_run_count=hall_runs,
                )
            )

    # Per-case aggregate: avg passRate@N across variants of that case.
    case_summaries = []
    case_ids = []
    seen_case = set()
    for v in variants:
        if v.case_id not in seen_case:
            case_ids.append(v.case_id)
            seen_case.add(v.case_id)
    for cid in case_ids:
        vs = [v for v in variants if v.case_id == cid]
        avg = sum(v.pass_rate for v in vs) / len(vs)
        first_pass = sum(1 for v in vs if v.first_pass) / len(vs)
        # avg@5 in user's terms: average passes-out-of-N across the 5 variants.
        avg_at_n = avg * runs_per_transcript
        case_summaries.append(
            {
                "case_id": cid,
                "category": vs[0].category,
                "variants": len(vs),
                "pass_rate": round(avg, 3),
                f"avg_at_{runs_per_transcript}": round(avg_at_n, 2),
                "first_pass_rate": round(first_pass, 3),
                "hallucination_runs": sum(v.hallucination_run_count for v in vs),
            }
        )
    case_summaries.sort(key=lambda s: s["pass_rate"])

    categories = sorted({v.category for v in variants})
    cat_summaries = []
    for cat in categories:
        vs = [v for v in variants if v.category == cat]
        mean = sum(v.pass_rate for v in vs) / len(vs)
        cat_summaries.append(
            {
                "category": cat,
                "variant_count": len(vs),
                "mean_pass_rate": round(mean, 3),
                f"mean_at_{runs_per_transcript}": round(mean * runs_per_transcript, 2),
                "first_pass_rate": round(sum(1 for v in vs if v.first_pass) / len(vs), 3),
                "hallucination_runs": sum(v.hallucination_run_count for v in vs),
            }
        )

    overall = sum(v.pass_rate for v in variants) / len(variants) if variants else 0.0

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_path": str(prompt_path),
        "model": model,
        "temperature": temperature,
        "runs_per_transcript": runs_per_transcript,
        "total_variants": len(variants),
        "mean_pass_rate": round(overall, 3),
        f"mean_at_{runs_per_transcript}": round(overall * runs_per_transcript, 2),
        "case_summaries": case_summaries,
        "category_summaries": cat_summaries,
        "variants": [
            {
                "case_id": v.case_id,
                "category": v.category,
                "transcript_index": v.transcript_index,
                "transcript": v.transcript,
                "pass_rate": v.pass_rate,
                "first_pass": v.first_pass,
                "hallucination_run_count": v.hallucination_run_count,
                "runs": [asdict(r) for r in v.runs],
            }
            for v in variants
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", type=pathlib.Path, required=True)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--out", type=pathlib.Path)
    ap.add_argument("--cases", nargs="*", default=None, help="Filter to specific case IDs")
    ap.add_argument("--subset", choices=["diagnostic", "expanded", "full"], default="full")
    ap.add_argument("--model", default="llama-3.1-8b-instant")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--variants", type=int, default=None, help="Limit to first N variants per case")
    ap.add_argument("--repair", action="store_true", help="Apply repair.py post-processing")
    args = ap.parse_args()
    run_eval._repair = args.repair  # type: ignore[attr-defined]
    if args.out:
        run_eval._partial_path = str(args.out).replace(".json", "_partial.json")  # type: ignore[attr-defined]

    case_filter: set[str] | None
    if args.cases:
        case_filter = set(args.cases)
    elif args.subset == "diagnostic":
        case_filter = set(DIAGNOSTIC_SUBSET)
    elif args.subset == "expanded":
        case_filter = set(EXPANDED_SUBSET)
    else:
        case_filter = None

    report = run_eval(
        prompt_path=args.prompt,
        runs_per_transcript=args.runs,
        case_filter=case_filter,
        model=args.model,
        temperature=args.temperature,
        concurrency=args.concurrency,
        variants_per_case=args.variants,
    )

    out_path = args.out
    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = REPO_ROOT / "evals" / "reports" / f"{args.prompt.stem}_{stamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    print()
    print(f"Report: {out_path}")
    print(f"Model: {report['model']}  Temp: {report['temperature']}  Runs/variant: {report['runs_per_transcript']}")
    print(f"Overall mean@{args.runs}: {report[f'mean_at_{args.runs}']} / {args.runs}  ({report['mean_pass_rate'] * 100:.1f}%)")
    print()
    print("Cases (worst → best):")
    print(f"  {'case_id':<35} {'cat':<14} {'avg@N':<8} {'first':<6} {'hall':<5}")
    for s in report["case_summaries"]:
        marker = "FAIL" if s["pass_rate"] < 0.7 else ("WARN" if s["pass_rate"] < 0.9 else "  ok")
        print(
            f"  [{marker}] {s['case_id']:<33} {s['category']:<14} "
            f"{s[f'avg_at_{args.runs}']:<8} {s['first_pass_rate']:<6} {s['hallucination_runs']:<5}"
        )


if __name__ == "__main__":
    main()
