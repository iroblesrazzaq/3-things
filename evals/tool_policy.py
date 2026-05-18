"""Tool-call policy checks for live extraction harness (advisory warnings)."""
from __future__ import annotations

import re

# Phrases that are cancellations, not tasks.
_CANCELLATION_PHRASES = (
    "forget both",
    "forget everything",
    "cancel everything",
    "start over",
    "scratch that",
    "never mind",
    "nevermind",
    "no action",
)

_CANCEL_ALL_PATTERNS = re.compile(
    r"\b(forget both|forget everything|cancel everything|start over|scratch (that|everything)|"
    r"none of that|cancel all|forget all)\b",
    re.I,
)

# Heuristic: multiple task clauses in one string (comma/and between verb phrases).
_BLOB_SEP = re.compile(
    r",\s*(?:and\s+)?(?=[a-z])",
    re.I,
)


def _normalize_task_text(text: str) -> str:
    return " ".join(text.lower().split())


def looks_like_cancellation_task(text: str) -> bool:
    n = _normalize_task_text(text)
    if not n:
        return False
    for phrase in _CANCELLATION_PHRASES:
        if phrase in n or n == phrase:
            return True
    if n.startswith("forget ") and len(n.split()) <= 4:
        return True
    return False


def looks_like_multi_task_blob(text: str) -> bool:
    """True if text likely bundles multiple distinct tasks."""
    t = text.strip()
    if not t:
        return False
    parts = _BLOB_SEP.split(t)
    if len(parts) < 2:
        return False
    # Require each segment to have some substance (not just "and X").
    substantive = [p.strip() for p in parts if len(p.strip()) > 3]
    return len(substantive) >= 2


def transcript_has_cancel_all(full_transcript: str, new_fragment: str) -> bool:
    combined = f"{full_transcript} {new_fragment}"
    return bool(_CANCEL_ALL_PATTERNS.search(combined))


def check_tool_policy(
    calls: list[dict],
    *,
    full_transcript: str,
    new_fragment: str,
) -> list[str]:
    """Return advisory warning codes for tool-call sequences."""
    warnings: list[str] = []
    has_clear = any(c.get("tool") == "clear_draft" for c in calls)

    if has_clear and not transcript_has_cancel_all(full_transcript, new_fragment):
        warnings.append("clear_draft_without_cancel_all")

    for call in calls:
        tool = call.get("tool")
        if tool == "add_task":
            text = str(call.get("text", ""))
            if looks_like_multi_task_blob(text):
                warnings.append(f"blob_task:add_task:{text[:40]}")
            if looks_like_cancellation_task(text):
                warnings.append(f"cancellation_as_task:add_task:{text[:40]}")
        elif tool == "revise_task":
            text = str(call.get("new_text", ""))
            if looks_like_multi_task_blob(text):
                warnings.append(f"blob_task:revise_task:{text[:40]}")
            if looks_like_cancellation_task(text):
                warnings.append(f"cancellation_as_task:revise_task:{text[:40]}")
        elif tool == "set_draft":
            for t in call.get("selected_tasks") or []:
                if looks_like_multi_task_blob(str(t)):
                    warnings.append(f"blob_task:set_draft_selected:{str(t)[:40]}")
                if looks_like_cancellation_task(str(t)):
                    warnings.append(f"cancellation_as_task:set_draft:{str(t)[:40]}")
            for t in call.get("extra_candidates") or []:
                if looks_like_multi_task_blob(str(t)):
                    warnings.append(f"blob_task:set_draft_extra:{str(t)[:40]}")

    return warnings
