"""Tests for prompt v2 indexed user message."""
from __future__ import annotations

import unittest

from live_replay import LiveStep
from tool_extractor import format_user_message
from tool_session import SessionState


class PromptV2Tests(unittest.TestCase):
    def test_indexed_state_and_prefix(self) -> None:
        step = LiveStep(
            full_transcript="Go to the park, go to the store.",
            new_fragment=", go to the store.",
            user_finished_speaking=True,
        )
        session = SessionState(
            selected_tasks=["Go to the park"],
            processed_transcript_character_count=14,
            last_full_transcript="Go to the park",
        )
        msg = format_user_message(step, session, prompt_mode="full_and_fragment")
        self.assertIn("[0] Go to the park", msg)
        self.assertIn("Processed prefix text:\nGo to the park", msg)
        self.assertIn("New fragment:\n, go to the store.", msg)
        self.assertNotIn("Current selected (order preserved):", msg)

    def test_set_state_instruction(self) -> None:
        step = LiveStep(
            full_transcript="Email Sam",
            new_fragment="Email Sam",
            user_finished_speaking=False,
        )
        msg = format_user_message(
            step, None, prompt_mode="full_and_fragment", tool_contract="set_state"
        )
        self.assertIn("set_draft", msg)
        self.assertNotIn("Apply tools so the draft", msg)


if __name__ == "__main__":
    unittest.main()
