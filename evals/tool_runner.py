"""Replay JSON tool-call traces against a Python executor that mirrors Swift
`VoiceDraftToolEnvironment` + `VoiceDraftPostProcessor.buildDraft`.

Use when a model (e.g. Groq) emits a list of tool calls instead of Apple `Tool` types.
Swift remains canonical; extend this file when Swift invariants change.

Trace file format (JSON object):
  {
    "transcript": "optional cleaned transcript for final draft",
    "calls": [
      {"tool": "add_task", "text": "call mom"},
      {"tool": "revise_task", "pool": "selected", "slot": 0, "new_text": "call dad"},
      {"tool": "delete_task", "pool": "extra", "slot": 0},
      {"tool": "clear_draft"},
      {"tool": "no_action", "reason": "incomplete"}
    ]
  }

`pool` is \"selected\" or \"extra\". Slot is 0-based.

Usage:
    python tool_runner.py path/to/trace.json
    python tool_runner.py path/to/trace.json --json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import unicodedata

from scorer import Draft

_CAP = 100
_STOP = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "of",
    "and",
    "or",
    "with",
    "on",
    "in",
    "at",
    "by",
    "is",
    "am",
    "are",
    "be",
}


def _meaning_tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    lowered = folded.lower()
    scrubbed = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return {w for w in scrubbed.split() if len(w) > 1 and w not in _STOP}


def _normalized_tokens(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    lowered = folded.lower()
    scrubbed = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return " ".join(w for w in scrubbed.split() if w)


def semantic_duplicate(a: str, b: str) -> bool:
    ta, tb = _meaning_tokens(a), _meaning_tokens(b)
    if len(ta) < 2 or len(tb) < 2:
        return _normalized_tokens(a) == _normalized_tokens(b)
    inter = ta & tb
    if len(inter) < 2:
        return False
    union = ta | tb
    return len(inter) / len(union) >= 0.55


def build_draft(
    selected_tasks: list[str],
    extra_candidates: list[str],
    detected_more_than_three: bool,
    *,
    contains_actionable_tasks: bool = True,
    cleaned_transcript: str,
) -> Draft:
    """Mirror of Swift `VoiceDraftPostProcessor.buildDraft` (throws there → ValueError here)."""
    cleaned = cleaned_transcript.strip()
    if not contains_actionable_tasks:
        raise ValueError("empty_model_output")

    selected: list[str] = []
    seen_lower: set[str] = set()
    for raw in selected_tasks:
        text = raw[:_CAP].strip()
        if not text:
            continue
        key = text.lower()
        if key in seen_lower:
            continue
        if any(semantic_duplicate(s, text) for s in selected):
            continue
        seen_lower.add(key)
        selected.append(text)

    extras: list[str] = []
    for raw in extra_candidates:
        text = raw[:_CAP].strip()
        if not text:
            continue
        key = text.lower()
        if key in seen_lower:
            continue
        if any(semantic_duplicate(s, text) for s in selected):
            continue
        if any(semantic_duplicate(e, text) for e in extras):
            continue
        seen_lower.add(key)
        extras.append(text)

    while len(selected) < 3 and extras:
        candidate = extras.pop(0)
        if any(semantic_duplicate(s, candidate) for s in selected):
            continue
        selected.append(candidate)

    if len(selected) > 3:
        overflow_items = selected[3:]
        selected = selected[:3]
        extras = overflow_items + extras

    overflow = bool(extras)
    raw_nonempty = sum(1 for t in selected_tasks if t.strip())
    if raw_nonempty > 3:
        overflow = True
    if detected_more_than_three and extras:
        overflow = True

    if not selected:
        raise ValueError("empty_model_output")

    return Draft(
        selected_tasks=selected,
        extra_candidates=extras,
        detected_more_than_three=overflow,
        contains_actionable_tasks=True,
    )


class ToolTraceExecutor:
    """Mutable draft state; same operation order as Swift `VoiceDraftToolEnvironment`."""

    def __init__(self) -> None:
        self.selected: list[str] = []
        self.extras: list[str] = []
        self.messages: list[str] = []

    def add_task(self, raw: str) -> None:
        text = raw[:_CAP].strip()
        if not text:
            self.messages.append("Skipped empty task.")
            return
        if any(semantic_duplicate(t, text) for t in self.selected):
            self.messages.append("Skipped duplicate of a selected task.")
            return
        if any(semantic_duplicate(t, text) for t in self.extras):
            self.messages.append("Skipped duplicate of an extra.")
            return
        if len(self.selected) < 3:
            self.selected.append(text)
            self.messages.append("Added to selected.")
        else:
            self.extras.append(text)
            self.messages.append("Added to extras (overflow).")

    def delete_task(self, pool: str, slot: int) -> None:
        if pool == "selected":
            if 0 <= slot < len(self.selected):
                self.selected.pop(slot)
                self.messages.append("Removed selected task.")
            else:
                self.messages.append("Ignored delete: invalid selected index.")
        elif pool == "extra":
            if 0 <= slot < len(self.extras):
                self.extras.pop(slot)
                self.messages.append("Removed extra.")
            else:
                self.messages.append("Ignored delete: invalid extra index.")
        else:
            self.messages.append("Ignored delete: unknown pool.")

    def revise_task(self, pool: str, slot: int, raw: str) -> None:
        new_text = raw[:_CAP].strip()
        if not new_text:
            self.messages.append("Ignored revise: empty text.")
            return
        if pool == "selected":
            if 0 <= slot < len(self.selected):
                self.selected[slot] = new_text
                self.messages.append("Revised selected task.")
            else:
                self.messages.append("Ignored revise: invalid selected index.")
        elif pool == "extra":
            if 0 <= slot < len(self.extras):
                self.extras[slot] = new_text
                self.messages.append("Revised extra.")
            else:
                self.messages.append("Ignored revise: invalid extra index.")
        else:
            self.messages.append("Ignored revise: unknown pool.")

    def clear_draft(self) -> None:
        self.selected.clear()
        self.extras.clear()
        self.messages.append("Cleared all tasks.")

    def apply_set_draft(self, call: dict) -> str | None:
        """Replace entire draft from set_draft tool output."""
        if not call.get("contains_actionable_tasks", True):
            self.selected.clear()
            self.extras.clear()
            self.messages.append("set_draft: no actionable tasks.")
            return "no_actionable"
        self.selected = [str(t)[:_CAP].strip() for t in call.get("selected_tasks") or [] if str(t).strip()]
        self.extras = [str(t)[:_CAP].strip() for t in call.get("extra_candidates") or [] if str(t).strip()]
        self.messages.append("set_draft: applied target state.")
        return None

    def apply_call(self, call: dict) -> str | None:
        """Returns `no_action` reason string if present, else None."""
        tool = call.get("tool")
        if tool == "set_draft":
            return self.apply_set_draft(call)
        if tool == "add_task":
            self.add_task(str(call.get("text", "")))
        elif tool == "delete_task":
            self.delete_task(str(call.get("pool", "selected")), int(call.get("slot", -1)))
        elif tool == "revise_task":
            self.revise_task(
                str(call.get("pool", "selected")),
                int(call.get("slot", -1)),
                str(call.get("new_text", "")),
            )
        elif tool == "clear_draft":
            self.clear_draft()
        elif tool == "no_action":
            return str(call.get("reason", "unknown"))
        else:
            self.messages.append(f"Unknown tool: {tool}")
        return None

    def finalize_draft(self, transcript: str) -> Draft:
        detected = len(self.selected) + len(self.extras) > 3
        return build_draft(
            list(self.selected),
            list(self.extras),
            detected,
            contains_actionable_tasks=bool(self.selected),
            cleaned_transcript=transcript,
        )


def run_trace(data: dict) -> tuple[Draft | None, list[str], str | None]:
    """Apply all calls; return (draft or None on empty), tool messages, no_action reason."""
    ex = ToolTraceExecutor()
    no_action_reason: str | None = None
    for call in data.get("calls", []):
        r = ex.apply_call(call)
        if r is not None:
            no_action_reason = r
    transcript = str(data.get("transcript", "")).strip()
    # `no_action` alone (no tasks accumulated) → no draft; if tools already added tasks, finalize.
    if no_action_reason and not ex.selected and not ex.extras:
        return None, ex.messages, no_action_reason
    try:
        return ex.finalize_draft(transcript or " "), ex.messages, None
    except ValueError:
        return None, ex.messages, no_action_reason


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay JSON tool traces (Groq / offline parity).")
    p.add_argument("trace", type=pathlib.Path, help="JSON trace file")
    p.add_argument("--json", action="store_true", help="Print Draft as JSON")
    args = p.parse_args(argv)
    data = json.loads(args.trace.read_text())
    draft, messages, no_action = run_trace(data)
    out: dict = {"messages": messages, "no_action": no_action}
    if draft:
        out["draft"] = {
            "selected_tasks": draft.selected_tasks,
            "extra_candidates": draft.extra_candidates,
            "detected_more_than_three": draft.detected_more_than_three,
        }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
