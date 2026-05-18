"""Tests for tool-call policy warnings."""
from __future__ import annotations

import unittest

from tool_policy import (
    check_tool_policy,
    looks_like_cancellation_task,
    looks_like_multi_task_blob,
    transcript_has_cancel_all,
)


class ToolPolicyTests(unittest.TestCase):
    def test_blob_detection(self) -> None:
        self.assertTrue(looks_like_multi_task_blob("Email Sam, pay rent, buy milk"))
        self.assertFalse(looks_like_multi_task_blob("go to the store"))

    def test_cancellation_task(self) -> None:
        self.assertTrue(looks_like_cancellation_task("forget both"))
        self.assertFalse(looks_like_cancellation_task("email Sam"))

    def test_clear_draft_without_cancel_all(self) -> None:
        warnings = check_tool_policy(
            [{"tool": "clear_draft"}],
            full_transcript="Go to a store, go to the park",
            new_fragment=", go to the park",
        )
        self.assertTrue(any("clear_draft_without_cancel_all" in w for w in warnings))

    def test_clear_draft_allowed_on_cancel_all(self) -> None:
        self.assertTrue(
            transcript_has_cancel_all(
                "Email Sam, pay rent, actually forget both.",
                ", actually forget both.",
            )
        )
        warnings = check_tool_policy(
            [{"tool": "clear_draft"}],
            full_transcript="Email Sam, pay rent, actually forget both.",
            new_fragment=", actually forget both.",
        )
        self.assertFalse(any("clear_draft_without_cancel_all" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
