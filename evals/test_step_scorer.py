"""Tests for per-step multi-step scoring."""
from __future__ import annotations

import json
import pathlib
import unittest

from scorer import Draft
from step_scorer import expectations_for_case, score_step
from runner import DIAGNOSTIC_SUBSET

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"


class StepScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {c["id"]: c for c in json.loads(FIXTURE_PATH.read_text())["cases"]}

    def test_literal_accumulation_passes_step_by_step(self) -> None:
        exps = expectations_for_case(self.cases["literal_three_store_park_food"])
        self.assertEqual(len(exps), 3)
        r0 = score_step(exps[0], selected=["go to a store"], extras=[], calls=[{"tool": "add_task"}])
        self.assertTrue(r0.passed)
        r1 = score_step(
            exps[1],
            selected=["go to a store", "go to the park"],
            extras=[],
            calls=[{"tool": "add_task"}],
        )
        self.assertTrue(r1.passed)

    def test_correction_fails_if_park_remains(self) -> None:
        exps = expectations_for_case(self.cases["correction_never_mind_single"])
        r1 = score_step(
            exps[1],
            selected=["go to the park"],
            extras=[],
            calls=[{"tool": "add_task"}],
        )
        self.assertFalse(r1.passed)
        self.assertTrue(r1.reasons)

    def test_correction_passes_when_only_store(self) -> None:
        exps = expectations_for_case(self.cases["correction_never_mind_single"])
        r1 = score_step(
            exps[1],
            selected=["go to the store"],
            extras=[],
            calls=[{"tool": "delete_task"}, {"tool": "add_task"}],
        )
        self.assertTrue(r1.passed)

    def test_duplicate_step_fails_with_two_email_tasks(self) -> None:
        exps = expectations_for_case(self.cases["duplicate_email_sam"])
        r1 = score_step(
            exps[1],
            selected=["email Sam", "send Sam an email", "pay rent"],
            extras=[],
            calls=[],
        )
        self.assertFalse(r1.passed)

    def test_no_task_step_fails_if_tasks_present(self) -> None:
        exps = expectations_for_case(self.cases["no_task_testing"])
        r0 = score_step(
            exps[0],
            selected=["call client"],
            extras=[],
            calls=[{"tool": "add_task"}],
        )
        self.assertFalse(r0.passed)

    def test_tool_warnings_advisory_by_default(self) -> None:
        exps = expectations_for_case(self.cases["correction_never_mind_single"])
        step_exp = {**exps[1], "requiredToolsAny": ["delete_task", "revise_task"]}
        r1 = score_step(
            step_exp,
            selected=["go to the store"],
            extras=[],
            calls=[{"tool": "add_task"}],
            strict_tools=False,
        )
        self.assertTrue(r1.passed)
        self.assertTrue(r1.tool_warnings)
        self.assertTrue(any("missing_required_any" in w for w in r1.tool_warnings))

    def test_diagnostic_cases_have_step_expectations(self) -> None:
        for case_id in DIAGNOSTIC_SUBSET:
            case = self.cases[case_id]
            snaps = case.get("liveSnapshots") or []
            if not snaps:
                continue
            exps = expectations_for_case(case)
            self.assertEqual(len(exps), len(snaps), case_id)

    def test_forget_everything_final_step_no_draft(self) -> None:
        exps = expectations_for_case(self.cases["correction_forget_everything"])
        r = score_step(
            exps[-1],
            selected=[],
            extras=[],
            calls=[{"tool": "clear_draft"}],
        )
        self.assertTrue(r.passed)

    def test_exactly_three_no_overflow_flag(self) -> None:
        exps = expectations_for_case(self.cases["literal_exactly_three_no_overflow"])
        r = score_step(
            exps[-1],
            selected=["email Sam", "pay rent", "buy milk"],
            extras=[],
            calls=[],
        )
        self.assertTrue(r.passed)
        self.assertFalse(exps[-1]["expectedOverflow"])

    def test_no_task_then_task_step_zero_empty(self) -> None:
        exps = expectations_for_case(self.cases["no_task_then_one_task"])
        r0 = score_step(exps[0], selected=[], extras=[], calls=[{"tool": "no_action"}])
        self.assertTrue(r0.passed)
        r1 = score_step(
            exps[1],
            selected=["email Sam"],
            extras=[],
            calls=[{"tool": "add_task", "text": "Email Sam"}],
        )
        self.assertTrue(r1.passed)


if __name__ == "__main__":
    unittest.main()
