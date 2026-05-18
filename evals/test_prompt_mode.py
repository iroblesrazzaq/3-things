"""Tests for fragment prompt ablation formatting."""
from __future__ import annotations

import unittest

from live_replay import LiveStep
from tool_extractor import format_user_message
from tool_session import SessionState


class PromptModeTests(unittest.TestCase):
    def test_full_and_fragment_includes_suffix(self) -> None:
        step = LiveStep(
            full_transcript="Go to the park, go to the store.",
            new_fragment=", go to the store.",
            user_finished_speaking=True,
        )
        msg = format_user_message(
            step,
            SessionState(selected_tasks=["Go to the park"]),
            prompt_mode="full_and_fragment",
        )
        self.assertIn("Full transcript:\nGo to the park, go to the store.", msg)
        self.assertIn("New fragment:\n, go to the store.", msg)

    def test_omit_fragment_drops_line(self) -> None:
        step = LiveStep(
            full_transcript="Go to the park, go to the store.",
            new_fragment=", go to the store.",
            user_finished_speaking=True,
        )
        msg = format_user_message(step, None, prompt_mode="omit_fragment")
        self.assertNotIn("New fragment", msg)
        self.assertIn("Full transcript:", msg)

    def test_blank_fragment_keeps_line_empty(self) -> None:
        step = LiveStep(
            full_transcript="Email Sam",
            new_fragment="Email Sam",
            user_finished_speaking=False,
        )
        msg = format_user_message(step, None, prompt_mode="blank_fragment")
        self.assertIn("New fragment:\n(empty)", msg)
        frag_section = msg.split("New fragment:", 1)[1].split("User finished", 1)[0]
        self.assertNotIn("Email Sam", frag_section)


if __name__ == "__main__":
    unittest.main()
