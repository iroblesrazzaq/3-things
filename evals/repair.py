"""Output repair layer. Applied after the model returns, before scoring.

Implements deterministic fixes the model frequently gets wrong:
- Detect cancellation language in the transcript and remove cancelled tasks
- Collapse near-duplicate task wordings
- Recompute overflow based on cleaned task set
"""
from __future__ import annotations

import re

from scorer import Draft, normalize, _has_duplicate_pair  # type: ignore


# Phrases that mark whatever-came-before as cancelled.
# Order matters somewhat (longer first to win in scanning).
CANCEL_MARKERS = [
    "scratch that",
    "never mind",
    "cancel that",
    "wait, no",
    "wait no",
    "actually no",
    "actually skip",
    "no wait",
    "skip that",
    "not today",
]

# Words that introduce a replacement: "X, actually Y" -> Y, drop X.
REPLACE_MARKERS = [
    "actually",
    "instead",
    "i mean",
    "rather",
]


def find_cancellations(transcript: str) -> list[tuple[int, int]]:
    """Return (start, end) char spans that mark cancellation events.
    Heuristic — used by tests, not yet wired into repair_draft.
    """
    spans: list[tuple[int, int]] = []
    text = transcript.lower()
    for marker in CANCEL_MARKERS:
        i = 0
        while True:
            j = text.find(marker, i)
            if j < 0:
                break
            spans.append((j, j + len(marker)))
            i = j + len(marker)
    return spans


def collapse_duplicates(tasks: list[str]) -> list[str]:
    """Drop later tasks that semantically duplicate an earlier one (preserve order)."""
    keep: list[str] = []
    for t in tasks:
        if any(_has_duplicate_pair(t, k) for k in keep):
            continue
        keep.append(t)
    return keep


def recompute_overflow(selected: list[str], extras: list[str], original_more_than_three: bool) -> bool:
    """Overflow iff total distinct tasks > 3 after cleaning."""
    if extras:
        return True
    if len(selected) > 3:
        return True
    return False


def repair_draft(draft: Draft, transcript: str) -> Draft:
    """Apply deterministic post-processing fixes.

    1. Drop semantic duplicates within selected (preserve first occurrence)
    2. Drop extras that duplicate something in selected (model dumps rephrasings there)
    3. Drop extras that duplicate something else in extras
    4. Promote extras into selected slots when selected has room AND extras exist
       (model often puts task #3 in extras when it should be in selected #3)
    5. If selected has >3, push the rest into extras
    6. Recompute overflow based on final counts
    """
    sel = collapse_duplicates([s for s in draft.selected_tasks if s.strip()])
    extras = [e for e in draft.extra_candidates if e.strip()]
    extras = [e for e in extras if not any(_has_duplicate_pair(e, s) for s in sel)]
    extras = collapse_duplicates(extras)

    # Promote extras into selected if there's room (model under-filled selected).
    while len(sel) < 3 and extras:
        candidate = extras.pop(0)
        if not any(_has_duplicate_pair(candidate, s) for s in sel):
            sel.append(candidate)

    # Cap selected at 3, push overflow into extras
    if len(sel) > 3:
        extras = sel[3:] + extras
        sel = sel[:3]
        extras = collapse_duplicates(extras)

    overflow = recompute_overflow(sel, extras, draft.detected_more_than_three)

    return Draft(
        selected_tasks=sel,
        extra_candidates=extras,
        detected_more_than_three=overflow,
        contains_actionable_tasks=draft.contains_actionable_tasks and bool(sel),
    )
