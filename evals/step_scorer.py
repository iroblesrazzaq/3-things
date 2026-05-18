"""Per-step scoring for multi-step Groq tool eval."""
from __future__ import annotations

from dataclasses import dataclass, field

from scorer import Draft, meaning_matches, normalize, score
from tool_policy import check_tool_policy


@dataclass
class StepScoreResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    tool_warnings: list[str] = field(default_factory=list)


def _step_case_from_expectation(step_exp: dict) -> dict:
    """Build a mini case dict for semantic scoring at one live step."""
    return {
        "expectedSelectedMeanings": step_exp.get("selectedMeanings", []),
        "expectedExtraMeanings": step_exp.get("extraMeanings", []),
        "forbiddenMeanings": step_exp.get("forbiddenMeanings", []),
        "expectedOverflow": step_exp.get("expectedOverflow", False),
        "expectsNoDraft": step_exp.get("expectsNoDraft", False),
        "category": step_exp.get("category", ""),
    }


def session_to_draft(
    selected: list[str],
    extras: list[str],
    *,
    full_transcript: str,
) -> Draft | None:
    if not selected and not extras:
        return None
    total = len(selected) + len(extras)
    return Draft(
        selected_tasks=list(selected),
        extra_candidates=list(extras),
        detected_more_than_three=total > 3,
        contains_actionable_tasks=True,
    )


def _strict_meaning_matches(expected: str, output: str) -> bool:
    """Stricter than scorer.meaning_matches for per-step state (avoids park≈store)."""
    e = normalize(expected)
    o = normalize(output)
    if not e or not o:
        return False
    if e == o:
        return True
    if e in o or o in e:
        return True
    exp = {t for t in e.split() if len(t) > 1}
    cand = {t for t in o.split() if len(t) > 1}
    if not exp:
        return False
    return (len(exp & cand) / len(exp)) >= 0.85


def _step_semantic_reasons(step_exp: dict, selected: list[str], extras: list[str]) -> list[str]:
    """Extra checks so similar tasks (park vs store) do not false-pass at a step."""
    reasons: list[str] = []
    expected_selected = step_exp.get("selectedMeanings", [])
    expected_extras = step_exp.get("extraMeanings", [])
    forbidden = step_exp.get("forbiddenMeanings", [])
    category = step_exp.get("category", "")

    used_selected: set[int] = set()
    for expected in expected_selected:
        found = None
        for idx, out in enumerate(selected):
            if idx in used_selected:
                continue
            if _strict_meaning_matches(expected, out):
                found = idx
                break
        if found is None:
            reasons.append("missing_task")
        else:
            used_selected.add(found)

    for idx, sel in enumerate(selected):
        if idx in used_selected:
            continue
        if any(_strict_meaning_matches(e, sel) for e in expected_selected):
            continue
        if category == "correction" or category.startswith("correction"):
            reasons.append("ignored_correction")
        else:
            reasons.append("invented_selected")

    for forbidden_meaning in forbidden:
        for sel in selected:
            if not meaning_matches(forbidden_meaning, sel):
                continue
            if any(_strict_meaning_matches(e, sel) for e in expected_selected):
                continue
            reasons.append("invented_selected")
            break

    used_extras: set[int] = set()
    for expected in expected_extras:
        found = None
        for idx, ex in enumerate(extras):
            if idx in used_extras:
                continue
            if _strict_meaning_matches(expected, ex):
                found = idx
                break
        if found is None:
            reasons.append("missing_task")
        else:
            used_extras.add(found)

    for idx, ex in enumerate(extras):
        if idx in used_extras:
            continue
        if not any(_strict_meaning_matches(e, ex) for e in expected_extras):
            reasons.append("invented_extra")

    return sorted(set(reasons))


def _check_tools(calls: list[dict], step_exp: dict) -> list[str]:
    warnings: list[str] = []
    tools_used = [str(c.get("tool", "")) for c in calls]
    allowed = step_exp.get("allowedTools")
    if allowed is not None:
        for t in tools_used:
            if t and t not in allowed and t != "no_action":
                warnings.append(f"tool_not_in_allowed:{t}")
    required_any = step_exp.get("requiredToolsAny")
    if required_any and tools_used:
        if not any(t in required_any for t in tools_used):
            warnings.append(f"missing_required_any:{required_any}")
    forbidden = step_exp.get("forbiddenTools") or []
    for t in tools_used:
        if t in forbidden:
            warnings.append(f"forbidden_tool:{t}")
    return warnings


def score_step(
    step_exp: dict,
    *,
    selected: list[str],
    extras: list[str],
    calls: list[dict],
    strict_tools: bool = False,
    full_transcript: str = "",
    new_fragment: str = "",
) -> StepScoreResult:
    """Score session state after one live round; tool checks are advisory unless strict_tools."""
    mini = _step_case_from_expectation(step_exp)
    draft = session_to_draft(selected, extras, full_transcript="")
    attempt = score(mini, draft, None if draft else "empty_model_output")

    tool_warnings = _check_tools(calls, step_exp)
    tool_warnings.extend(
        check_tool_policy(
            calls,
            full_transcript=full_transcript,
            new_fragment=new_fragment,
        )
    )
    tool_warnings = sorted(set(tool_warnings))
    reasons = [r.value for r in attempt.reasons]
    reasons.extend(_step_semantic_reasons(step_exp, selected, extras))
    reasons = sorted(set(reasons))

    if strict_tools and tool_warnings:
        reasons.extend(tool_warnings)

    passed = not reasons
    return StepScoreResult(passed=passed, reasons=reasons, tool_warnings=tool_warnings)


def expectations_for_case(case: dict) -> list[dict]:
    """Return liveStepExpectations aligned with liveSnapshots, or synthesize from final case."""
    explicit = case.get("liveStepExpectations")
    snapshots = case.get("liveSnapshots") or []
    if explicit is not None:
        if len(explicit) != len(snapshots):
            raise ValueError(
                f"{case['id']}: liveStepExpectations length {len(explicit)} "
                f"!= liveSnapshots {len(snapshots)}"
            )
        return explicit

    if not snapshots:
        return []

    n = len(snapshots)
    if n == 1:
        return [
            {
                "selectedMeanings": case.get("expectedSelectedMeanings", []),
                "extraMeanings": case.get("expectedExtraMeanings", []),
                "forbiddenMeanings": case.get("forbiddenMeanings", []),
                "expectedOverflow": case.get("expectedOverflow", False),
                "expectsNoDraft": case.get("expectsNoDraft", False),
                "category": case.get("category", ""),
            }
        ]

    # Multi-step without explicit expectations: only final step gets full expectations.
    out: list[dict] = []
    for i in range(n):
        if i == n - 1:
            out.append(
                {
                    "selectedMeanings": case.get("expectedSelectedMeanings", []),
                    "extraMeanings": case.get("expectedExtraMeanings", []),
                    "forbiddenMeanings": case.get("forbiddenMeanings", []),
                    "expectedOverflow": case.get("expectedOverflow", False),
                    "expectsNoDraft": case.get("expectsNoDraft", False),
                    "category": case.get("category", ""),
                }
            )
        else:
            out.append(
                {
                    "selectedMeanings": [],
                    "extraMeanings": [],
                    "forbiddenMeanings": case.get("forbiddenMeanings", []),
                    "expectedOverflow": False,
                    "expectsNoDraft": True,
                    "category": case.get("category", ""),
                }
            )
    return out
