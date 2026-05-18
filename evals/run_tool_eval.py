"""Multi-step Groq tool-calling eval using liveSnapshots replay."""
from __future__ import annotations

import argparse
import json
import pathlib
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from live_replay import LiveStep, live_steps_for_case
from runner import (
    AUTORESEARCH_SUBSET,
    DIAGNOSTIC_SUBSET,
    EDGE_CASE_SUBSET,
    EXPANDED_SUBSET,
    FULL_LIVE_SUBSET,
    FIXTURE,
    RunOutcome,
    _outcome,
)
from scorer import score
from step_scorer import expectations_for_case, score_step
from tool_eval_aggregate import aggregate_tool_reports
from tool_extractor import GroqToolExtractor, ToolExtractorConfig
from tool_schemas import ToolContract
from tool_runner import build_draft
from tool_session import SessionState, run_live_steps_with_results

REPO = pathlib.Path(__file__).resolve().parent


@dataclass
class StepResultReport:
    index: int
    passed: bool
    full: str
    fragment: str
    finished: bool
    skipped: bool
    selected_tasks: list[str]
    extra_candidates: list[str]
    calls: list[dict]
    reasons: list[str]
    tool_warnings: list[str] = field(default_factory=list)


@dataclass
class ToolVariantReport:
    case_id: str
    category: str
    variant_index: int
    replay_mode: str
    steps: int
    tool_rounds: int
    runs: list[RunOutcome]
    pass_rate: float
    first_pass: bool
    trace: list[dict] | None = None
    step_results: list[StepResultReport] | None = None
    all_steps_passed: bool | None = None
    final_passed: bool | None = None
    step_pass_rate: float | None = None
    tool_warning_count: int = 0
    api_error_count: int = 0


def _session_final_draft(session: SessionState | None, transcript: str):
    if session is None or (not session.selected_tasks and not session.extra_candidates):
        return None, "empty_model_output"
    try:
        draft = build_draft(
            session.selected_tasks,
            session.extra_candidates,
            len(session.selected_tasks) + len(session.extra_candidates) > 3,
            contains_actionable_tasks=True,
            cleaned_transcript=transcript,
        )
        return draft, None
    except ValueError:
        return None, "empty_model_output"


def _score_steps_for_case(
    case: dict,
    live_results: list,
    *,
    strict_tools: bool,
) -> list[StepResultReport]:
    step_exps = expectations_for_case(case)
    reports: list[StepResultReport] = []
    for i, (lr, step_exp) in enumerate(zip(live_results, step_exps)):
        sess = lr.session
        selected = list(sess.selected_tasks) if sess else []
        extras = list(sess.extra_candidates) if sess else []
        step_score = score_step(
            step_exp,
            selected=selected,
            extras=extras,
            calls=lr.calls,
            strict_tools=strict_tools,
            full_transcript=lr.step.full_transcript,
            new_fragment=lr.step.new_fragment,
        )
        reports.append(
            StepResultReport(
                index=i,
                passed=step_score.passed,
                full=lr.step.full_transcript,
                fragment=lr.step.new_fragment,
                finished=lr.step.user_finished_speaking,
                skipped=lr.skipped,
                selected_tasks=selected,
                extra_candidates=extras,
                calls=lr.calls,
                reasons=step_score.reasons,
                tool_warnings=step_score.tool_warnings,
            )
        )
    return reports


def run_one_pass(
    case: dict,
    *,
    variant_index: int,
    extractor: GroqToolExtractor,
    capture_trace: bool,
    score_steps: bool,
    strict_tools: bool,
) -> tuple[RunOutcome, list[StepResultReport] | None, bool | None, str, int, int]:
    """Single stochastic pass; returns outcome, step results, replay mode, tool rounds, warnings."""
    steps = live_steps_for_case(case, variant_index=variant_index)
    replay_mode = "fixture_snapshots" if case.get("liveSnapshots") else "synthetic"

    def model_round(step: LiveStep, sess: SessionState | None) -> list[dict]:
        return extractor.apply_round(step, sess)

    session, live_results = run_live_steps_with_results(
        steps, initial=None, model_round=model_round
    )

    step_results: list[StepResultReport] | None = None
    all_steps_passed: bool | None = None
    warning_count = 0
    if score_steps:
        step_results = _score_steps_for_case(case, live_results, strict_tools=strict_tools)
        all_steps_passed = all(s.passed for s in step_results) if step_results else True
        warning_count = sum(len(s.tool_warnings) for s in step_results)

    final_transcript = steps[-1].full_transcript if steps else ""
    draft, err = _session_final_draft(session, final_transcript)
    attempt = score(case, draft, err)
    outcome = _outcome(draft, err, attempt)
    final_passed = outcome.passed

    first_pass = final_passed
    if score_steps and all_steps_passed is not None:
        first_pass = final_passed and all_steps_passed

    trace = None
    if capture_trace:
        trace = [
            {
                "full": r.step.full_transcript,
                "fragment": r.step.new_fragment,
                "finished": r.step.user_finished_speaking,
                "calls": r.calls,
            }
            for r in live_results
        ]

    tool_rounds = sum(1 for r in live_results if not r.skipped)
    return (
        RunOutcome(
            passed=first_pass,
            reasons=outcome.reasons,
            selected_tasks=outcome.selected_tasks,
            extra_candidates=outcome.extra_candidates,
            detected_more_than_three=outcome.detected_more_than_three,
            error=outcome.error,
        ),
        step_results,
        all_steps_passed,
        replay_mode,
        tool_rounds,
        warning_count,
        trace,
        final_passed,
    )


def run_one_variant(
    case: dict,
    *,
    variant_index: int,
    extractor: GroqToolExtractor,
    capture_trace: bool,
    score_steps: bool,
    strict_tools: bool,
    runs: int,
) -> ToolVariantReport:
    outcomes: list[RunOutcome] = []
    last_step_results: list[StepResultReport] | None = None
    last_all_steps: bool | None = None
    replay_mode = "fixture_snapshots"
    tool_rounds = 0
    total_warnings = 0
    api_errors = 0
    last_trace: list[dict] | None = None
    steps_count = len(live_steps_for_case(case, variant_index=variant_index))

    for run_idx in range(runs):
        try:
            (
                outcome,
                step_results,
                all_steps_passed,
                replay_mode,
                tool_rounds,
                warning_count,
                trace,
                final_passed,
            ) = run_one_pass(
                case,
                variant_index=variant_index,
                extractor=extractor,
                capture_trace=capture_trace and run_idx == runs - 1,
                score_steps=score_steps,
                strict_tools=strict_tools,
            )
            outcomes.append(outcome)
            last_step_results = step_results
            last_all_steps = all_steps_passed
            total_warnings += warning_count
            last_trace = trace
            if outcome.error:
                api_errors += 1
        except Exception as e:  # noqa: BLE001
            attempt = score(case, None, f"runner_error:{type(e).__name__}:{e}")
            err_outcome = _outcome(None, str(e), attempt)
            outcomes.append(
                RunOutcome(
                    passed=False,
                    reasons=err_outcome.reasons,
                    selected_tasks=[],
                    extra_candidates=[],
                    detected_more_than_three=False,
                    error=str(e),
                )
            )
            api_errors += 1
            replay_mode = "error"
        if run_idx + 1 < runs:
            time.sleep(0.25)

    passes = sum(1 for o in outcomes if o.passed)
    pass_rate = passes / runs if runs else 0.0
    first_pass = outcomes[0].passed if outcomes else False

    step_pass_rate = None
    if last_step_results:
        scored = [s for s in last_step_results if not s.skipped]
        if scored:
            step_pass_rate = sum(1 for s in scored if s.passed) / len(scored)

    return ToolVariantReport(
        case_id=case["id"],
        category=case["category"],
        variant_index=variant_index,
        replay_mode=replay_mode,
        steps=steps_count,
        tool_rounds=tool_rounds,
        runs=outcomes,
        pass_rate=pass_rate,
        first_pass=first_pass,
        trace=last_trace,
        step_results=last_step_results,
        all_steps_passed=last_all_steps,
        final_passed=outcomes[-1].passed if outcomes else False,
        step_pass_rate=step_pass_rate,
        tool_warning_count=total_warnings,
        api_error_count=api_errors,
    )


def run_one_case(
    case: dict,
    *,
    variant_index: int,
    extractor: GroqToolExtractor,
    capture_trace: bool,
    score_steps: bool,
    strict_tools: bool,
) -> ToolVariantReport:
    """Single-run wrapper for fragment ablation and legacy callers."""
    return run_one_variant(
        case,
        variant_index=variant_index,
        extractor=extractor,
        capture_trace=capture_trace,
        score_steps=score_steps,
        strict_tools=strict_tools,
        runs=1,
    )


def build_report_payload(
    reports: list[ToolVariantReport],
    *,
    model: str,
    subset: str,
    score_steps: bool,
    prompt_mode: str,
    tool_contract: str,
    runs_per_variant: int,
    temperature: float,
) -> dict:
    agg = aggregate_tool_reports(reports, runs_per_variant=runs_per_variant)
    passed = sum(1 for r in reports if r.pass_rate >= 1.0)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "temperature": temperature,
        "subset": subset,
        "score_steps": score_steps,
        "prompt_mode": prompt_mode,
        "tool_contract": tool_contract,
        "replay_mode": "fixture_snapshots",
        "runs_per_variant": runs_per_variant,
        "total_variants": agg["total_variants"],
        "mean_pass_rate": agg["mean_pass_rate"],
        f"mean_at_{runs_per_variant}": agg[f"mean_at_{runs_per_variant}"],
        "mean_step_pass_rate": agg["mean_step_pass_rate"],
        "tool_warning_rate": agg["tool_warning_rate"],
        "api_error_rate": agg["api_error_rate"],
        "case_summaries": agg["case_summaries"],
        "category_summaries": agg["category_summaries"],
        "variants": [asdict(r) for r in reports],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--subset",
        choices=["diagnostic", "expanded", "edge", "full_live", "full", "autoresearch"],
        default="diagnostic",
    )
    ap.add_argument("--cases", nargs="*", default=None)
    ap.add_argument("--variants", type=int, default=1)
    ap.add_argument("--runs", type=int, default=1, help="Stochastic repeats per variant (avg@N)")
    ap.add_argument("--out", type=pathlib.Path, default=REPO / "reports" / "tools_diagnostic.json")
    ap.add_argument("--model", default="llama-3.1-8b-instant")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--capture-trace", action="store_true")
    ap.add_argument(
        "--score-steps",
        action="store_true",
        help="Score each live step against liveStepExpectations",
    )
    ap.add_argument(
        "--strict-tools",
        action="store_true",
        help="Fail steps when tool_warnings are present (default: advisory only)",
    )
    ap.add_argument(
        "--prompt-mode",
        choices=["full_and_fragment", "omit_fragment", "blank_fragment"],
        default="full_and_fragment",
        help="Ablation: include new fragment line, omit it, or send (empty)",
    )
    ap.add_argument(
        "--tool-contract",
        choices=["mutation", "set_state"],
        default="mutation",
        help="mutation tools (add/revise/delete) or set_draft target state",
    )
    args = ap.parse_args()

    data = json.loads(FIXTURE.read_text())
    cases = data["cases"]
    if args.subset == "diagnostic":
        ids = set(DIAGNOSTIC_SUBSET)
        cases = [c for c in cases if c["id"] in ids]
    elif args.subset == "expanded":
        ids = set(EXPANDED_SUBSET)
        cases = [c for c in cases if c["id"] in ids]
    elif args.subset == "edge":
        ids = set(EDGE_CASE_SUBSET)
        cases = [c for c in cases if c["id"] in ids]
    elif args.subset == "full_live":
        ids = set(FULL_LIVE_SUBSET)
        cases = [c for c in cases if c["id"] in ids]
    elif args.subset == "autoresearch":
        ids = set(AUTORESEARCH_SUBSET)
        cases = [c for c in cases if c["id"] in ids]
    if args.cases:
        want = set(args.cases)
        cases = [c for c in cases if c["id"] in want]

    tool_contract: ToolContract = args.tool_contract
    extractor = GroqToolExtractor(
        ToolExtractorConfig(
            model=args.model,
            temperature=args.temperature,
            prompt_mode=args.prompt_mode,
            tool_contract=tool_contract,
        )
    )
    reports: list[ToolVariantReport] = []
    for case in cases:
        for vi in range(min(args.variants, len(case["transcriptVariants"]))):
            label = f"{case['id']} v{vi}"
            if args.runs > 1:
                label += f" ({args.runs} runs)"
            print(f"Running {label}...", flush=True)
            reports.append(
                run_one_variant(
                    case,
                    variant_index=vi,
                    extractor=extractor,
                    capture_trace=args.capture_trace or args.score_steps,
                    score_steps=args.score_steps,
                    strict_tools=args.strict_tools,
                    runs=max(1, args.runs),
                )
            )
            time.sleep(0.5)

    payload = build_report_payload(
        reports,
        model=args.model,
        subset=args.subset,
        score_steps=args.score_steps,
        prompt_mode=args.prompt_mode,
        tool_contract=args.tool_contract,
        runs_per_variant=max(1, args.runs),
        temperature=args.temperature,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    mean_key = f"mean_at_{max(1, args.runs)}"
    mean_at = payload[mean_key]
    print(f"mean_at_{max(1, args.runs)}: {mean_at}")
    print(f"mean_pass_rate: {payload['mean_pass_rate']}")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "passed": sum(1 for r in reports if r.pass_rate >= 1.0),
                "total": len(reports),
                mean_key: mean_at,
            },
            indent=2,
        )
    )
    all_passed = all(r.pass_rate >= 1.0 for r in reports)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
