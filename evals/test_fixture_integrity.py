"""Fixture structure checks for multi-step live eval and SFT export."""
from __future__ import annotations

import json
import pathlib
import unittest

from runner import DIAGNOSTIC_SUBSET, EXPANDED_SUBSET
from step_expectation_builder import build_step_expectations
from step_scorer import expectations_for_case

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"

NEW_EDGE_CASES = [
    "correction_forget_everything",
    "correction_park_to_store_direct",
    "overflow_then_drop_fourth",
    "no_task_then_one_task",
    "duplicate_pay_rent_thrice",
    "literal_exactly_three_no_overflow",
    "negative_plus_positive",
    "inference_doctor_ramble",
    "substeps_incremental_launch",
    "vague_taxes_not_specific",
    "future_intraday_correction",
]

FULL_LIVE_SUBSET = sorted(
    set(DIAGNOSTIC_SUBSET + EXPANDED_SUBSET + NEW_EDGE_CASES)
)


class FixtureIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        data = json.loads(FIXTURE.read_text())
        cls.cases = {c["id"]: c for c in data["cases"]}
        cls.version = data.get("version", 0)

    def test_version_at_least_three(self) -> None:
        self.assertGreaterEqual(self.version, 3)

    def test_minimum_case_count(self) -> None:
        self.assertGreaterEqual(len(self.cases), 36)

    def test_every_case_has_transcript_variants(self) -> None:
        for case_id, case in self.cases.items():
            variants = case.get("transcriptVariants") or []
            self.assertGreaterEqual(len(variants), 3, case_id)

    def test_all_cases_have_live_snapshots(self) -> None:
        missing = [cid for cid, c in self.cases.items() if not c.get("liveSnapshots")]
        self.assertEqual(missing, [], f"missing liveSnapshots: {missing}")

    def test_expectations_align_with_snapshots(self) -> None:
        for case_id, case in self.cases.items():
            snaps = case.get("liveSnapshots") or []
            exps = expectations_for_case(case)
            self.assertEqual(
                len(exps),
                len(snaps),
                f"{case_id}: {len(exps)} expectations vs {len(snaps)} snapshots",
            )

    def test_builder_matches_stored_expectations(self) -> None:
        for case_id, case in self.cases.items():
            snaps = case.get("liveSnapshots") or []
            stored = case.get("liveStepExpectations") or []
            built = build_step_expectations(case, snaps)
            if case_id in {
                "literal_three_store_park_food",
                "overflow_four_clean",
                "correction_never_mind_single",
                "duplicate_email_sam",
                "no_task_testing",
                "inference_store_only",
                "vague_taxes",
            }:
                continue
            self.assertEqual(len(built), len(stored), case_id)

    def test_each_step_has_scoreable_fields(self) -> None:
        for case_id, case in self.cases.items():
            for i, exp in enumerate(expectations_for_case(case)):
                self.assertIn("selectedMeanings", exp, f"{case_id} step {i}")
                self.assertIn("expectsNoDraft", exp, f"{case_id} step {i}")
                snaps = case["liveSnapshots"]
                self.assertTrue(snaps[i].strip(), f"{case_id} step {i} empty snapshot")

    def test_new_edge_cases_present(self) -> None:
        for case_id in NEW_EDGE_CASES:
            self.assertIn(case_id, self.cases, case_id)

    def test_overflow_exactly_three_not_overflow_on_final(self) -> None:
        case = self.cases["literal_exactly_three_no_overflow"]
        self.assertFalse(case["expectedOverflow"])
        final = expectations_for_case(case)[-1]
        self.assertFalse(final["expectedOverflow"])
        self.assertEqual(len(final["selectedMeanings"]), 3)

    def test_forget_everything_ends_no_draft(self) -> None:
        case = self.cases["correction_forget_everything"]
        self.assertTrue(case["expectsNoDraft"])
        self.assertTrue(expectations_for_case(case)[-1]["expectsNoDraft"])


if __name__ == "__main__":
    unittest.main()
