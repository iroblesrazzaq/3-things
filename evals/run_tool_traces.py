"""Score diagnostic tool traces against voice_extraction_cases.json."""
from __future__ import annotations

import json
import pathlib
import sys

from live_replay import LiveStep
from scorer import score
from tool_runner import build_draft, run_trace
from tool_session import SessionState, run_live_steps

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"
TRACES_DIR = pathlib.Path(__file__).resolve().parent / "traces" / "diagnostic"


def main() -> int:
    cases = {c["id"]: c for c in json.loads(FIXTURE.read_text())["cases"]}
    traces = sorted(TRACES_DIR.glob("*.json"))
    if not traces:
        print(f"No traces in {TRACES_DIR}", file=sys.stderr)
        return 1

    passed = 0
    rows: list[dict] = []
    for path in traces:
        data = json.loads(path.read_text())
        case_id = data.get("case_id", path.stem)
        case = cases.get(case_id)
        if case is None:
            print(f"Unknown case_id {case_id} in {path.name}", file=sys.stderr)
            return 1
        draft, messages, no_action = replay_trace(data)
        err = None if draft else "empty_model_output"
        attempt = score(case, draft, err)
        if attempt.passed:
            passed += 1
        rows.append(
            {
                "case_id": case_id,
                "trace": path.name,
                "passed": attempt.passed,
                "reasons": [r.value for r in attempt.reasons],
                "no_action": no_action,
                "draft": None
                if draft is None
                else {
                    "selected_tasks": draft.selected_tasks,
                    "extra_candidates": draft.extra_candidates,
                    "detected_more_than_three": draft.detected_more_than_three,
                },
                "message_count": len(messages),
            }
        )

    report = {
        "traces_dir": str(TRACES_DIR),
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "results": rows,
    }
    print(json.dumps(report, indent=2))
    return 0 if passed == len(rows) else 1


def replay_trace(data: dict):
    steps_raw = data.get("steps")
    if not steps_raw:
        return run_trace(data)

    steps = [
        LiveStep(
            full_transcript=str(s["full"]),
            new_fragment=str(s.get("fragment", "")),
            user_finished_speaking=bool(s.get("finished", False)),
        )
        for s in steps_raw
    ]

    def model_round(step: LiveStep, _session: SessionState | None) -> list[dict]:
        for s in steps_raw:
            if str(s["full"]) == step.full_transcript:
                return list(s.get("calls", []))
        return []

    session, _ = run_live_steps(steps, initial=None, model_round=model_round)
    transcript = str(data.get("transcript", steps[-1].full_transcript if steps else "")).strip()
    if session is None or (not session.selected_tasks and not session.extra_candidates):
        return None, [], "no_actionable"
    try:
        draft = build_draft(
            session.selected_tasks,
            session.extra_candidates,
            len(session.selected_tasks) + len(session.extra_candidates) > 3,
            contains_actionable_tasks=True,
            cleaned_transcript=transcript,
        )
        return draft, [], None
    except ValueError:
        return None, [], "no_actionable"


if __name__ == "__main__":
    raise SystemExit(main())
