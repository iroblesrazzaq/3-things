"""Tests for set_draft tool contract application."""
from __future__ import annotations

import unittest

from live_replay import LiveStep
from tool_runner import ToolTraceExecutor
from tool_session import SessionState, apply_tool_calls


class SetDraftTests(unittest.TestCase):
    def test_apply_set_draft_replaces_state(self) -> None:
        session = SessionState(selected_tasks=["Go to the park"])
        step = LiveStep(
            full_transcript="Go to the store.",
            new_fragment="Go to the store.",
            user_finished_speaking=True,
        )
        calls = [
            {
                "tool": "set_draft",
                "selected_tasks": ["Go to the store"],
                "extra_candidates": [],
                "contains_actionable_tasks": True,
            }
        ]
        result = apply_tool_calls(session, step, calls)
        self.assertEqual(result.session.selected_tasks, ["Go to the store"])

    def test_executor_set_draft_clears_when_not_actionable(self) -> None:
        ex = ToolTraceExecutor()
        ex.selected = ["a", "b"]
        r = ex.apply_set_draft(
            {
                "tool": "set_draft",
                "selected_tasks": [],
                "extra_candidates": [],
                "contains_actionable_tasks": False,
            }
        )
        self.assertEqual(r, "no_actionable")
        self.assertEqual(ex.selected, [])


if __name__ == "__main__":
    unittest.main()
