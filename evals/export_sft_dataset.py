"""Export multi-step voice extraction examples for SFT / fine-tuning.

Each record is one model round: system prompt, user context (full + fragment + session),
and a target assistant message (ideal tool calls and/or target session state).

Usage:
    python export_sft_dataset.py --out datasets/voice_tools_sft.jsonl
    python export_sft_dataset.py --from-traces traces/ --out datasets/voice_tools_sft_golden.jsonl
"""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

from live_replay import live_steps_for_case
from step_expectation_builder import build_step_expectations
from tool_schemas import TOOL_INSTRUCTIONS
from tool_session import SessionState, apply_tool_calls

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"


def _user_message(step, session: SessionState | None) -> str:
    selected = ", ".join(session.selected_tasks) if session and session.selected_tasks else "(none)"
    extras = ", ".join(session.extra_candidates) if session and session.extra_candidates else "(none)"
    fragment = step.new_fragment or "(empty)"
    return (
        f"Full transcript:\n{step.full_transcript}\n"
        f"New fragment (since last applied position):\n{fragment}\n"
        f"User finished speaking: {'yes' if step.user_finished_speaking else 'no'}\n"
        f"Current selected (order preserved): {selected}\n"
        f"Current extras (overflow): {extras}\n"
        "Apply tools so the draft matches the transcript. If there are still no actionable tasks, call no_action."
    )


def _ideal_calls_from_state(
    before: SessionState,
    after_selected: list[str],
    after_extras: list[str],
    *,
    expects_no_draft: bool,
) -> list[dict]:
    """Heuristic tool sequence for SFT labels (clear + add when state changes)."""
    if expects_no_draft and not after_selected and not after_extras:
        if before.selected_tasks or before.extra_candidates:
            return [{"tool": "clear_draft"}]
        return [{"tool": "no_action", "reason": "no_actionable"}]

    before_sel = list(before.selected_tasks)
    before_ex = list(before.extra_candidates)
    if before_sel == list(after_selected) and before_ex == list(after_extras):
        return [{"tool": "no_action", "reason": "unchanged"}]

    calls: list[dict] = []
    if before_sel or before_ex:
        calls.append({"tool": "clear_draft"})
    for text in after_selected:
        calls.append({"tool": "add_task", "text": text})
    for text in after_extras:
        if text not in after_selected:
            calls.append({"tool": "add_task", "text": text})
    return calls or [{"tool": "no_action", "reason": "unchanged"}]


def _record_from_step(
    case: dict,
    step_index: int,
    step,
    session_before: SessionState,
    step_exp: dict,
) -> dict[str, Any]:
    target_sel = list(step_exp.get("selectedMeanings", []))
    target_ex = list(step_exp.get("extraMeanings", []))
    expects_no = bool(step_exp.get("expectsNoDraft", False))
    ideal_calls = _ideal_calls_from_state(
        session_before,
        target_sel,
        target_ex,
        expects_no_draft=expects_no,
    )
    round_result = apply_tool_calls(session_before, step, ideal_calls)
    session_after = round_result.session or session_before

    return {
        "id": f"{case['id']}:v0:step{step_index}",
        "case_id": case["id"],
        "category": case.get("category", ""),
        "step_index": step_index,
        "variant_index": 0,
        "messages": [
            {"role": "system", "content": TOOL_INSTRUCTIONS},
            {"role": "user", "content": _user_message(step, session_before)},
        ],
        "ideal_tool_calls": ideal_calls,
        "target_state": {
            "selected_tasks": target_sel,
            "extra_candidates": target_ex,
            "detected_more_than_three": bool(step_exp.get("expectedOverflow", False)),
        },
        "reconstructed_state": {
            "selected_tasks": list(session_after.selected_tasks),
            "extra_candidates": list(session_after.extra_candidates),
        },
        "metadata": {
            "full_transcript": step.full_transcript,
            "new_fragment": step.new_fragment,
            "user_finished_speaking": step.user_finished_speaking,
        },
    }


def export_from_fixture(fixture_path: pathlib.Path, *, case_ids: list[str] | None = None) -> list[dict]:
    data = json.loads(fixture_path.read_text())
    cases = {c["id"]: c for c in data["cases"]}
    ids = case_ids or sorted(cases.keys())
    records: list[dict] = []

    for case_id in ids:
        case = cases[case_id]
        snapshots = case.get("liveSnapshots") or []
        if not snapshots:
            continue
        expectations = case.get("liveStepExpectations") or build_step_expectations(case, snapshots)
        steps = live_steps_for_case(case, variant_index=0)
        session = SessionState()
        for i, (step, step_exp) in enumerate(zip(steps, expectations)):
            rec = _record_from_step(case, i, step, session, step_exp)
            records.append(rec)
            session = apply_tool_calls(session, step, rec["ideal_tool_calls"]).session or session
    return records


def export_from_traces(trace_dir: pathlib.Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(trace_dir.rglob("*.json")):
        payload = json.loads(path.read_text())
        case_id = payload.get("case_id", path.stem)
        for i, step in enumerate(payload.get("trace") or payload.get("steps") or []):
            calls = step.get("calls") or []
            if not calls:
                continue
            records.append(
                {
                    "id": f"{case_id}:trace:step{i}",
                    "case_id": case_id,
                    "step_index": i,
                    "source": "trace",
                    "messages": [
                        {"role": "system", "content": TOOL_INSTRUCTIONS},
                        {
                            "role": "user",
                            "content": (
                                f"Full transcript:\n{step.get('full', '')}\n"
                                f"New fragment:\n{step.get('fragment', '')}\n"
                            ),
                        },
                    ],
                    "ideal_tool_calls": calls,
                    "metadata": step,
                }
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=pathlib.Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--from-traces", type=pathlib.Path, default=None)
    parser.add_argument("--out", type=pathlib.Path, default=REPO / "evals" / "datasets" / "voice_tools_sft.jsonl")
    parser.add_argument("--cases", nargs="*", default=None)
    args = parser.parse_args()

    if args.from_traces:
        records = export_from_traces(args.from_traces)
    else:
        records = export_from_fixture(args.fixture, case_ids=args.cases)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
