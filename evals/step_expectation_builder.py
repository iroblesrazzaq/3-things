"""Build liveStepExpectations from case metadata and liveSnapshots."""
from __future__ import annotations

from copy import deepcopy


def _forbidden_not_yet(
    case: dict,
    *,
    selected: list[str],
    extras: list[str],
) -> list[str]:
    """Forbidden meanings for tasks not yet stated at this step."""
    all_expected = list(case.get("expectedSelectedMeanings", [])) + list(
        case.get("expectedExtraMeanings", [])
    )
    pending = [m for m in all_expected if m not in selected and m not in extras]
    base = list(case.get("forbiddenMeanings", []))
    return sorted(set(base + pending))


def _step(
    *,
    selected: list[str],
    extras: list[str],
    forbidden: list[str],
    overflow: bool,
    no_draft: bool,
    category: str = "",
    **extra: object,
) -> dict:
    out: dict = {
        "selectedMeanings": selected,
        "extraMeanings": extras,
        "forbiddenMeanings": forbidden,
        "expectedOverflow": overflow,
        "expectsNoDraft": no_draft,
    }
    if category:
        out["category"] = category
    out.update(extra)
    return out


def build_accumulating_steps(case: dict, snapshots: list[str]) -> list[dict]:
    """Each snapshot adds the next explicit selected meaning (literal / separate tasks)."""
    expected = list(case.get("expectedSelectedMeanings", []))
    steps: list[dict] = []
    for i, _snap in enumerate(snapshots):
        sel = expected[: i + 1]
        steps.append(
            _step(
                selected=sel,
                extras=[],
                forbidden=_forbidden_not_yet(case, selected=sel, extras=[]),
                overflow=False,
                no_draft=False,
            )
        )
    return steps


def build_overflow_steps(case: dict, snapshots: list[str]) -> list[dict]:
    """Cumulative tasks; overflow once more than three explicit tasks appear."""
    all_tasks = list(case.get("expectedSelectedMeanings", [])) + list(
        case.get("expectedExtraMeanings", [])
    )
    final_sel = list(case.get("expectedSelectedMeanings", []))
    final_extras = list(case.get("expectedExtraMeanings", []))
    steps: list[dict] = []
    for i, _snap in enumerate(snapshots):
        stated = all_tasks[: i + 1]
        if len(stated) <= 3:
            sel, extras = stated, []
            overflow = False
        else:
            sel, extras = stated[:3], stated[3:]
            overflow = True
        is_final = i == len(snapshots) - 1
        if is_final:
            sel, extras = final_sel, final_extras
            overflow = bool(case.get("expectedOverflow", False))
        forbidden = _forbidden_not_yet(case, selected=sel, extras=extras)
        steps.append(
            _step(
                selected=sel,
                extras=extras,
                forbidden=forbidden,
                overflow=overflow,
                no_draft=False,
            )
        )
    return steps


def build_single_step(case: dict) -> list[dict]:
    if case.get("expectsNoDraft", False):
        return [
            _step(
                selected=[],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=True,
            )
        ]
    return [
        _step(
            selected=list(case.get("expectedSelectedMeanings", [])),
            extras=list(case.get("expectedExtraMeanings", [])),
            forbidden=list(case.get("forbiddenMeanings", [])),
            overflow=bool(case.get("expectedOverflow", False)),
            no_draft=False,
            category=str(case.get("category", "")),
        )
    ]


def build_step_expectations(case: dict, snapshots: list[str]) -> list[dict]:
    """Return liveStepExpectations aligned with snapshots (hand-tuned overrides first)."""
    if not snapshots:
        return []

    override = case.get("_builderOverride")
    if override == "hand":
        explicit = case.get("liveStepExpectations")
        if explicit is None:
            raise ValueError(f"{case['id']}: _builderOverride=hand but no liveStepExpectations")
        return deepcopy(explicit)

    case_id = case.get("id", "")
    if case_id == "no_task_then_one_task":
        return [
            _step(
                selected=[],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])) + ["email Sam"],
                overflow=False,
                no_draft=True,
            ),
            _step(
                selected=["email Sam"],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
            ),
        ]
    if case_id == "vague_taxes_not_specific":
        return [
            _step(
                selected=["taxes"],
                extras=[],
                forbidden=["file tax return", "call accountant"],
                overflow=False,
                no_draft=False,
                category="vague",
            ),
            _step(
                selected=["taxes"],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
                category="vague",
            ),
        ]
    if case_id == "future_intraday_correction":
        return [
            _step(
                selected=[],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])) + ["call Sam"],
                overflow=False,
                no_draft=True,
            ),
            _step(
                selected=["call Sam"],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
                category="future",
            ),
        ]
    if case_id == "substeps_incremental_launch":
        return [
            _step(
                selected=["finish launch email"],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
                category="subtasks",
            ),
            _step(
                selected=["finish launch email"],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
                category="subtasks",
            ),
            _step(
                selected=list(case.get("expectedSelectedMeanings", [])),
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
                category="subtasks",
            ),
        ]
    if case_id == "duplicate_pay_rent_thrice":
        return [
            _step(
                selected=["pay rent"],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=["pay rent"],
                extras=[],
                forbidden=list(case.get("forbiddenMeanings", [])),
                overflow=False,
                no_draft=False,
            ),
        ]

    category = case.get("category", "")
    if category == "overflow":
        return build_overflow_steps(case, snapshots)
    if category in ("literal", "ramble", "subtasks") and len(snapshots) > 1:
        expected_n = len(case.get("expectedSelectedMeanings", []))
        if expected_n > 1 and len(snapshots) == expected_n:
            return build_accumulating_steps(case, snapshots)
    if category == "correction" and len(snapshots) > 1:
        return _build_correction_steps(case, snapshots)
    if category == "duplicate" and len(snapshots) > 1:
        return _build_duplicate_steps(case, snapshots)
    if category == "future" and len(snapshots) > 1:
        return _build_future_steps(case, snapshots)
    if category == "no_task" and case.get("expectsNoDraft"):
        return build_single_step(case)
    if len(snapshots) == 1:
        return build_single_step(case)

    # Multi-snapshot fallback: final-only expectations on last step, empty before.
    steps: list[dict] = []
    for i in range(len(snapshots)):
        if i == len(snapshots) - 1:
            steps.extend(build_single_step(case))
        else:
            steps.append(
                _step(
                    selected=[],
                    extras=[],
                    forbidden=list(case.get("forbiddenMeanings", [])),
                    overflow=False,
                    no_draft=bool(case.get("expectsNoDraft", False)),
                )
            )
    return steps


def _build_correction_steps(case: dict, snapshots: list[str]) -> list[dict]:
    """Default two-phase correction: first snapshot keeps pre-cancel task, final keeps corrected."""
    case_id = case.get("id", "")
    final_sel = list(case.get("expectedSelectedMeanings", []))
    forbidden = list(case.get("forbiddenMeanings", []))

    if case_id == "correction_never_mind_single":
        return [
            _step(
                selected=["go to the park"],
                extras=[],
                forbidden=["go to the store", "buy groceries"],
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
                category="correction",
                requiredToolsAny=["delete_task", "revise_task", "add_task", "clear_draft"],
            ),
        ]

    if case_id == "correction_replace_call_with_text":
        return [
            _step(
                selected=["call Alex"],
                extras=[],
                forbidden=["text Alex", "schedule with Alex"],
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
                category="correction",
            ),
        ]

    if case_id == "correction_remove_one_keep_others":
        return [
            _step(
                selected=["email Sam"],
                extras=[],
                forbidden=["go to gym", "pay rent"],
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=["email Sam", "go to gym"],
                extras=[],
                forbidden=["pay rent"],
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
                category="correction",
            ),
        ]

    if case_id == "correction_forget_everything":
        return [
            _step(
                selected=["email Sam"],
                extras=[],
                forbidden=["pay rent"],
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=["email Sam", "pay rent"],
                extras=[],
                forbidden=[],
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=[],
                extras=[],
                forbidden=forbidden + final_sel,
                overflow=False,
                no_draft=True,
                category="correction",
            ),
        ]

    if case_id == "correction_park_to_store_direct":
        return [
            _step(
                selected=["go to the park"],
                extras=[],
                forbidden=["go to the store"],
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
                category="correction",
            ),
        ]

    if case_id == "overflow_then_drop_fourth":
        all_four = ["email Sam", "pay rent", "buy milk", "call mom"]
        base_forbidden = list(case.get("forbiddenMeanings", []))
        return [
            _step(
                selected=[all_four[0]],
                extras=[],
                forbidden=all_four[1:] + base_forbidden,
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=all_four[:2],
                extras=[],
                forbidden=all_four[2:] + base_forbidden,
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=all_four[:3],
                extras=[],
                forbidden=all_four[3:] + base_forbidden,
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=all_four[:3],
                extras=[all_four[3]],
                forbidden=base_forbidden,
                overflow=True,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
                category="correction",
            ),
        ]

    # Generic: accumulate then final
    if len(snapshots) == 2:
        pre = [m for m in forbidden if m not in final_sel]
        return [
            _step(
                selected=pre[:1] if pre else [],
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=not pre,
            ),
            _step(
                selected=final_sel,
                extras=list(case.get("expectedExtraMeanings", [])),
                forbidden=forbidden,
                overflow=bool(case.get("expectedOverflow", False)),
                no_draft=False,
                category="correction",
            ),
        ]
    return build_single_step(case)


def _build_duplicate_steps(case: dict, snapshots: list[str]) -> list[dict]:
    case_id = case.get("id", "")
    final_sel = list(case.get("expectedSelectedMeanings", []))
    forbidden = list(case.get("forbiddenMeanings", []))

    if case_id == "duplicate_email_sam":
        return [
            _step(
                selected=["email Sam"],
                extras=[],
                forbidden=["pay rent"] + forbidden,
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
            ),
        ]

    if len(snapshots) == 2 and len(final_sel) == 2:
        return [
            _step(
                selected=[final_sel[0]],
                extras=[],
                forbidden=[final_sel[1]] + forbidden,
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
            ),
        ]

    return build_single_step(case)


def _build_future_steps(case: dict, snapshots: list[str]) -> list[dict]:
    case_id = case.get("id", "")
    final_sel = list(case.get("expectedSelectedMeanings", []))
    forbidden = list(case.get("forbiddenMeanings", []))

    if case_id == "future_tomorrow_exclude":
        return [
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
            ),
            _step(
                selected=final_sel,
                extras=[],
                forbidden=forbidden,
                overflow=False,
                no_draft=False,
                category="future",
            ),
        ]

    return build_single_step(case)
