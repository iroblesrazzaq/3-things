"""Tests for automatic liveStepExpectations generation."""
from __future__ import annotations

import unittest

from step_expectation_builder import (
    build_accumulating_steps,
    build_overflow_steps,
    build_step_expectations,
)


class StepExpectationBuilderTests(unittest.TestCase):
    def _case(self, **kwargs: object) -> dict:
        base = {
            "id": "test",
            "category": "literal",
            "expectedSelectedMeanings": [],
            "expectedExtraMeanings": [],
            "expectedOverflow": False,
            "expectsNoDraft": False,
            "forbiddenMeanings": [],
        }
        base.update(kwargs)
        return base

    def test_accumulating_literal(self) -> None:
        case = self._case(
            id="literal_two",
            expectedSelectedMeanings=["call mom", "pay rent"],
            forbiddenMeanings=["visit mom"],
        )
        snaps = ["Call mom", "Call mom and pay rent."]
        steps = build_accumulating_steps(case, snaps)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["selectedMeanings"], ["call mom"])
        self.assertEqual(steps[1]["selectedMeanings"], ["call mom", "pay rent"])

    def test_overflow_four_steps(self) -> None:
        case = self._case(
            id="overflow_four_clean",
            category="overflow",
            expectedSelectedMeanings=["email Sam", "pay rent", "buy milk"],
            expectedExtraMeanings=["call mom"],
            expectedOverflow=True,
            forbiddenMeanings=["grocery shopping beyond milk"],
        )
        snaps = [
            "Email Sam",
            "Email Sam, pay rent",
            "Email Sam, pay rent, buy milk",
            "Email Sam, pay rent, buy milk, call mom",
        ]
        steps = build_overflow_steps(case, snaps)
        self.assertFalse(steps[0]["expectedOverflow"])
        self.assertFalse(steps[2]["expectedOverflow"])
        self.assertTrue(steps[3]["expectedOverflow"])
        self.assertEqual(steps[3]["extraMeanings"], ["call mom"])

    def test_no_task_then_task_two_steps(self) -> None:
        case = self._case(
            id="no_task_then_one_task",
            category="no_task",
            expectedSelectedMeanings=["email Sam"],
            expectsNoDraft=False,
            forbiddenMeanings=["call client"],
        )
        snaps = ["Testing", "Testing. Email Sam."]
        steps = build_step_expectations(case, snaps)
        self.assertTrue(steps[0]["expectsNoDraft"])
        self.assertEqual(steps[1]["selectedMeanings"], ["email Sam"])


if __name__ == "__main__":
    unittest.main()
