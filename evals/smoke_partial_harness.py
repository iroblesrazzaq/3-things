"""Smoke test: offline partial harness + Groq multi-step correction case."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

from partial_harness import (
    TRACES_DIR,
    assert_partial_invariants,
    load_cases,
    run_offline_case,
    walk_case,
)
from scorer import score

REPO = pathlib.Path(__file__).resolve().parent
CASE_ID = "correction_never_mind_single"
REPORT_PATH = REPO / "reports" / "smoke_partial.json"


def offline_smoke() -> None:
    views = walk_case(CASE_ID)
    assert len(views) >= 2, f"expected >=2 steps, got {len(views)}"
    assert views[0].fragment == views[0].full
    assert views[0].fragment == "Go to the park"
    assert not views[0].skip
    assert views[1].fragment
    assert views[1].fragment != views[1].full
    assert not views[1].skip

    steps = __import__("live_replay", fromlist=["live_steps_for_case"]).live_steps_for_case(
        load_cases()[CASE_ID]
    )
    assert_partial_invariants(steps)

    case = load_cases()[CASE_ID]
    trace_path = TRACES_DIR / f"{CASE_ID}.json"
    _, _, (draft, err) = run_offline_case(case, trace_path)
    attempt = score(case, draft, err)
    assert attempt.passed, f"offline trace score failed: {[r.value for r in attempt.reasons]}"
    print("offline_smoke: OK")


def groq_smoke() -> None:
    if not os.environ.get("GROQ_API_KEY"):
        print("GROQ_API_KEY not set; skipping Groq smoke", file=sys.stderr)
        sys.exit(1)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(REPO / "run_tool_eval.py"),
        "--cases",
        CASE_ID,
        "--variants",
        "1",
        "--capture-trace",
        "--out",
        str(REPORT_PATH),
    ]
    subprocess.run(cmd, cwd=REPO, check=True)

    payload = json.loads(REPORT_PATH.read_text())
    variants = payload.get("variants") or []
    assert variants, "no variants in report"
    report = variants[0]
    assert report["steps"] >= 2, f"expected >=2 steps, got {report['steps']}"
    assert report["tool_rounds"] >= 2, f"expected >=2 tool rounds, got {report['tool_rounds']}"
    assert report["first_pass"], f"Groq case failed: {report}"

    walk_views = walk_case(CASE_ID)
    trace = report.get("trace") or []
    assert len(trace) == len(walk_views), f"trace len {len(trace)} vs walk {len(walk_views)}"
    for i, (t, w) in enumerate(zip(trace, walk_views)):
        assert t["fragment"] == w.fragment, f"round {i} fragment mismatch: {t['fragment']!r} vs {w.fragment!r}"
        assert t["full"] == w.full, f"round {i} full mismatch"

    print("groq_smoke: OK")


def main() -> int:
    offline_smoke()
    groq_smoke()
    print(json.dumps({"status": "pass", "case": CASE_ID, "report": str(REPORT_PATH)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as e:
        print(f"smoke failed: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    except AssertionError as e:
        print(f"smoke failed: {e}", file=sys.stderr)
        raise SystemExit(1) from e
