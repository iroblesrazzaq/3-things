"""Compare Groq scores with vs without the new-fragment line in the user prompt.

Runs the same liveSnapshots twice per case (full+fragment vs omit_fragment) and
optionally blank_fragment. Intended for correction-heavy subsets.

Usage:
    python run_fragment_ablation.py --score-steps --out reports/fragment_ablation.json
    python run_fragment_ablation.py --modes full_and_fragment omit_fragment --cases correction_never_mind_single
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time
from datetime import datetime, timezone

from runner import CORRECTION_ABLATION_SUBSET, FIXTURE
from run_tool_eval import ToolVariantReport, run_one_case
from tool_extractor import GroqToolExtractor, PromptMode, ToolExtractorConfig
from tool_schemas import ToolContract

REPO = pathlib.Path(__file__).resolve().parent
DEFAULT_MODES: list[PromptMode] = ["full_and_fragment", "omit_fragment"]


def _summary_row(report: ToolVariantReport, *, prompt_mode: str) -> dict:
    step_passed = None
    step_failed_at = None
    if report.step_results:
        step_passed = [s.passed for s in report.step_results]
        for s in report.step_results:
            if not s.passed:
                step_failed_at = s.index
                break
    return {
        "prompt_mode": prompt_mode,
        "first_pass": report.first_pass,
        "final_passed": report.final_passed,
        "all_steps_passed": report.all_steps_passed,
        "step_passed": step_passed,
        "first_failed_step": step_failed_at,
        "final_selected": report.runs[0].selected_tasks if report.runs else [],
        "final_reasons": report.runs[0].reasons if report.runs else [],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fragment prompt ablation on correction cases")
    ap.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help="Case ids (default: CORRECTION_ABLATION_SUBSET)",
    )
    ap.add_argument(
        "--modes",
        nargs="*",
        choices=["full_and_fragment", "omit_fragment", "blank_fragment"],
        default=DEFAULT_MODES,
    )
    ap.add_argument("--variants", type=int, default=1)
    ap.add_argument("--model", default="llama-3.1-8b-instant")
    ap.add_argument(
        "--tool-contract",
        choices=["mutation", "set_state"],
        default="mutation",
    )
    ap.add_argument("--score-steps", action="store_true")
    ap.add_argument("--strict-tools", action="store_true")
    ap.add_argument(
        "--out",
        type=pathlib.Path,
        default=REPO / "reports" / "fragment_ablation.json",
    )
    args = ap.parse_args()

    data = json.loads(FIXTURE.read_text())
    want_ids = set(args.cases or CORRECTION_ABLATION_SUBSET)
    cases = [c for c in data["cases"] if c["id"] in want_ids]
    missing = want_ids - {c["id"] for c in cases}
    if missing:
        raise SystemExit(f"unknown cases: {sorted(missing)}")

    comparisons: list[dict] = []
    for case in cases:
        for vi in range(min(args.variants, len(case["transcriptVariants"]))):
            runs_by_mode: dict[str, dict] = {}
            for mode in args.modes:
                print(f"Running {case['id']} v{vi} [{mode}]...", flush=True)
                extractor = GroqToolExtractor(
                    ToolExtractorConfig(
                        model=args.model,
                        prompt_mode=mode,
                        tool_contract=args.tool_contract,
                    )
                )
                report = run_one_case(
                    case,
                    variant_index=vi,
                    extractor=extractor,
                    capture_trace=args.score_steps,
                    score_steps=args.score_steps,
                    strict_tools=args.strict_tools,
                )
                runs_by_mode[mode] = _summary_row(report, prompt_mode=mode)
                time.sleep(2.0)

            baseline = runs_by_mode.get("full_and_fragment")
            omit = runs_by_mode.get("omit_fragment")
            delta = None
            if baseline and omit:
                delta = {
                    "first_pass_improved_with_fragment": (
                        baseline["first_pass"] and not omit["first_pass"]
                    ),
                    "first_pass_same": baseline["first_pass"] == omit["first_pass"],
                    "omit_worse": baseline["first_pass"] and not omit["first_pass"],
                    "omit_better": omit["first_pass"] and not baseline["first_pass"],
                }

            comparisons.append(
                {
                    "case_id": case["id"],
                    "category": case["category"],
                    "variant_index": vi,
                    "modes": runs_by_mode,
                    "delta_full_vs_omit": delta,
                }
            )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "score_steps": args.score_steps,
        "tool_contract": args.tool_contract,
        "modes": args.modes,
        "case_ids": sorted(want_ids),
        "comparisons": comparisons,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    improved = sum(
        1
        for c in comparisons
        if c.get("delta_full_vs_omit", {}).get("omit_worse")
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "cases": len(comparisons),
                "omit_worse_than_full": improved,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
