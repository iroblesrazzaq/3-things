"""Summarize harness iteration matrix reports."""
from __future__ import annotations

import argparse
import json
import pathlib


def _load(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def summarize_tool_eval(data: dict, label: str) -> None:
    variants = data.get("variants") or []
    passed = sum(1 for v in variants if v.get("first_pass"))
    print(f"\n## {label}")
    print(f"passed {passed}/{len(variants)} mean_pass_rate={data.get('mean_pass_rate')}")
    print(f"prompt_mode={data.get('prompt_mode')} tool_contract={data.get('tool_contract')}")
    for v in variants:
        steps = v.get("step_results") or []
        step_ok = "".join("P" if s.get("passed") else "F" for s in steps) or "-"
        mark = "OK" if v.get("first_pass") else "FAIL"
        print(
            f"  [{mark}] {v['case_id']:<35} steps={step_ok} "
            f"final={v.get('final_passed')} reasons={v.get('runs', [{}])[0].get('reasons')}"
        )


def summarize_ablation(data: dict, label: str) -> None:
    print(f"\n## {label}")
    comparisons = data.get("comparisons") or []
    worse = sum(
        1 for c in comparisons if (c.get("delta_full_vs_omit") or {}).get("omit_worse")
    )
    print(f"omit_worse_than_full: {worse}/{len(comparisons)}")
    for c in comparisons:
        d = c.get("delta_full_vs_omit") or {}
        full = c["modes"].get("full_and_fragment", {})
        omit = c["modes"].get("omit_fragment", {})
        print(
            f"  {c['case_id']:<35} full={full.get('first_pass')} "
            f"omit={omit.get('first_pass')} omit_worse={d.get('omit_worse')}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports-dir", type=pathlib.Path, default=pathlib.Path("reports"))
    args = ap.parse_args()
    d = args.reports_dir

    files = [
        ("tools_prompt_v2_diagnostic_mutation.json", summarize_tool_eval),
        ("tools_prompt_v2_edge_mutation.json", summarize_tool_eval),
        ("tools_prompt_v2_diagnostic_set_state.json", summarize_tool_eval),
        ("fragment_ablation_prompt_v2.json", summarize_ablation),
    ]
    for name, fn in files:
        data = _load(d / name)
        if data:
            fn(data, name)
        else:
            print(f"\n## {name}\n(missing)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
