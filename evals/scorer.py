"""Python port of ThreeThings/Services/Extraction/Eval/VoiceExtractionEvalScorer.swift.

Keeps the same semantics so off-device prompt iteration is judged the same way as
the on-device eval. If you change scoring rules here, mirror them in the Swift file.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class FailureReason(str, Enum):
    INVENTED_SELECTED = "invented_selected"
    INVENTED_EXTRA = "invented_extra"
    MISSING_TASK = "missing_task"
    WRONG_OVERFLOW = "wrong_overflow"
    IGNORED_CORRECTION = "ignored_correction"
    DUPLICATE_NOT_COLLAPSED = "duplicate_not_collapsed"
    OVER_SPECIFIC_REWRITE = "over_specific_rewrite"
    NO_TASK_FALSE_POSITIVE = "no_task_false_positive"
    BAD_GROUPING = "bad_grouping"


@dataclass
class AttemptScore:
    passed: bool
    reasons: list[FailureReason] = field(default_factory=list)


@dataclass
class Draft:
    selected_tasks: list[str]
    extra_candidates: list[str]
    detected_more_than_three: bool
    contains_actionable_tasks: bool = True


STOP_WORDS = {"a", "an", "the"}


def _stem(word: str) -> str:
    """Very light stemmer for common English morphology. Conservative:
    strips final 's', 'es', 'ing', 'ed' only when stem is still >=3 chars.
    Mirrors what a 3B model considers semantically equivalent.
    """
    if len(word) >= 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) >= 5 and word.endswith("ed"):
        return word[:-2]
    if len(word) >= 4 and word.endswith("es"):
        return word[:-2]
    if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    lowered = folded.lower()
    scrubbed = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    parts = [_stem(p) for p in scrubbed.split() if p and p not in STOP_WORDS]
    return " ".join(parts)


def _token_coverage(expected_norm: str, candidate_norm: str, min_coverage: float) -> bool:
    exp = {t for t in expected_norm.split() if len(t) > 1}
    cand = {t for t in candidate_norm.split() if len(t) > 1}
    if not exp:
        return False
    inter = exp & cand
    return (len(inter) / len(exp)) >= min_coverage


def meaning_matches(expected: str, output: str) -> bool:
    e = normalize(expected)
    o = normalize(output)
    if not e or not o:
        return False
    if e in o or o in e:
        return True
    return _token_coverage(e, o, 0.5)


def _has_duplicate_pair(a: str, b: str) -> bool:
    ta = {t for t in normalize(a).split() if len(t) > 1}
    tb = {t for t in normalize(b).split() if len(t) > 1}
    if len(ta) < 2 or len(tb) < 2:
        return meaning_matches(a, b) and normalize(a) == normalize(b)
    inter = ta & tb
    union = ta | tb
    if len(inter) < 2:
        return False
    return (len(inter) / len(union)) >= 0.55


def _has_semantic_duplicates(tasks: list[str]) -> bool:
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            if _has_duplicate_pair(tasks[i], tasks[j]):
                return True
    return False


def _check_forbidden(case: dict, selected: list[str], extras: list[str]) -> list[FailureReason]:
    """Forbidden meanings are concepts the model should NOT output. Match if the
    output's normalized form contains the forbidden meaning (forbidden is a "more
    general" concept the model added). But: skip the match if the output ALSO
    matches an expected meaning — then the substring overlap is incidental
    (e.g. forbidden 'grocery shopping beyond buy milk' shares 'buy milk' with the
    valid expected meaning).
    """
    out: list[FailureReason] = []
    fields_list = selected + extras
    expected = case.get("expectedSelectedMeanings", []) + case.get("expectedExtraMeanings", [])
    for forbidden in case.get("forbiddenMeanings", []):
        f = normalize(forbidden)
        if not f:
            continue
        for idx, field_val in enumerate(fields_list):
            n = normalize(field_val)
            if not n:
                continue
            if not (f in n or n in f):
                continue
            # Skip if output more closely matches a valid expected meaning than the forbidden one.
            if any(meaning_matches(e, field_val) for e in expected):
                continue
            in_selected = idx < len(selected)
            out.append(FailureReason.INVENTED_SELECTED if in_selected else FailureReason.INVENTED_EXTRA)
    return out


def _dedup_score(reasons: list[FailureReason]) -> AttemptScore:
    uniq = sorted({r for r in reasons}, key=lambda r: r.value)
    return AttemptScore(passed=not uniq, reasons=uniq)


def score(case: dict, draft: Draft | None, error: str | None) -> AttemptScore:
    if case.get("expectsNoDraft", False):
        return _score_no_draft(case, draft, error)
    return _score_draft_expected(case, draft, error)


def _score_no_draft(case: dict, draft: Draft | None, error: str | None) -> AttemptScore:
    reasons: list[FailureReason] = []
    if draft and (draft.selected_tasks or draft.extra_candidates):
        reasons.append(FailureReason.NO_TASK_FALSE_POSITIVE)
        reasons += _check_forbidden(case, draft.selected_tasks, draft.extra_candidates)
        return _dedup_score(reasons)
    # No draft (either by error or by `contains_actionable_tasks=False`) is a pass.
    if error in (None, "empty_model_output", "empty_transcript"):
        return AttemptScore(passed=True)
    # Any other extraction error on a no-task transcript counts as a false positive (model misbehaved).
    return _dedup_score([FailureReason.NO_TASK_FALSE_POSITIVE])


def _score_draft_expected(case: dict, draft: Draft | None, error: str | None) -> AttemptScore:
    reasons: list[FailureReason] = []
    if draft is None:
        reasons.append(FailureReason.MISSING_TASK)
        return _dedup_score(reasons)

    expected_overflow = case.get("expectedOverflow", False)
    if draft.detected_more_than_three != expected_overflow:
        reasons.append(FailureReason.WRONG_OVERFLOW)

    reasons += _check_forbidden(case, draft.selected_tasks, draft.extra_candidates)

    used_selected: set[int] = set()
    for expected in case.get("expectedSelectedMeanings", []):
        found = None
        for idx, out in enumerate(draft.selected_tasks):
            if idx in used_selected:
                continue
            if meaning_matches(expected, out):
                found = idx
                break
        if found is None:
            reasons.append(FailureReason.MISSING_TASK)
        else:
            used_selected.add(found)

    for idx, sel in enumerate(draft.selected_tasks):
        if idx in used_selected:
            continue
        matches_expected = any(meaning_matches(e, sel) for e in case.get("expectedSelectedMeanings", []))
        if not matches_expected:
            if case.get("category", "").startswith("correction"):
                reasons.append(FailureReason.IGNORED_CORRECTION)
            else:
                reasons.append(FailureReason.INVENTED_SELECTED)

    expected_extras = case.get("expectedExtraMeanings", [])
    if not expected_extras and draft.extra_candidates:
        reasons.append(FailureReason.INVENTED_EXTRA)

    used_extras: set[int] = set()
    for expected in expected_extras:
        found = None
        for idx, ex in enumerate(draft.extra_candidates):
            if idx in used_extras:
                continue
            if meaning_matches(expected, ex):
                found = idx
                break
        if found is None:
            reasons.append(FailureReason.MISSING_TASK)
        else:
            used_extras.add(found)

    for idx, ex in enumerate(draft.extra_candidates):
        if idx in used_extras:
            continue
        ok = any(meaning_matches(e, ex) for e in expected_extras)
        if not ok:
            reasons.append(FailureReason.INVENTED_EXTRA)

    if _has_semantic_duplicates(draft.selected_tasks):
        reasons.append(FailureReason.DUPLICATE_NOT_COLLAPSED)

    if case.get("category") == "inference_trap":
        for sel in draft.selected_tasks:
            for expected in case.get("expectedSelectedMeanings", []):
                if meaning_matches(expected, sel):
                    if len(normalize(sel)) > len(normalize(expected)) + 12:
                        reasons.append(FailureReason.OVER_SPECIFIC_REWRITE)

    return _dedup_score(reasons)
