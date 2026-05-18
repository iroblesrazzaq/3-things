"""Parity between Python live_replay and committed fixture liveSnapshots."""
from __future__ import annotations

import json
import pathlib
import unittest

from generate_live_snapshots import HAND_SNAPSHOTS, snapshots_from_partials
from live_replay import live_steps_from_snapshots
from runner import DIAGNOSTIC_SUBSET, FIXTURE

MULTI_STEP_CASES = frozenset(HAND_SNAPSHOTS.keys())

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"


class LiveReplayParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = {c["id"]: c for c in json.loads(FIXTURE_PATH.read_text())["cases"]}

    def test_diagnostic_cases_have_live_snapshots(self) -> None:
        for case_id in DIAGNOSTIC_SUBSET:
            case = self.cases[case_id]
            self.assertIn("liveSnapshots", case, case_id)
            self.assertGreaterEqual(len(case["liveSnapshots"]), 1, case_id)

    def test_multi_step_cases_have_at_least_two_snapshots(self) -> None:
        for case_id in MULTI_STEP_CASES:
            case = self.cases[case_id]
            self.assertGreaterEqual(len(case["liveSnapshots"]), 2, case_id)

    def test_snapshots_regenerate_from_partials(self) -> None:
        for case_id in DIAGNOSTIC_SUBSET:
            if case_id in HAND_SNAPSHOTS:
                continue
            case = self.cases[case_id]
            partials = case.get("livePartials")
            if not partials:
                continue
            expected = case["liveSnapshots"]
            actual = snapshots_from_partials(partials)
            self.assertEqual(actual, expected, case_id)

    def test_live_steps_have_monotonic_full_text(self) -> None:
        for case_id in DIAGNOSTIC_SUBSET:
            steps = live_steps_from_snapshots(self.cases[case_id]["liveSnapshots"])
            prev_len = 0
            for step in steps:
                self.assertGreaterEqual(len(step.full_transcript), prev_len, case_id)
                prev_len = len(step.full_transcript)
            self.assertTrue(steps[-1].user_finished_speaking, case_id)


if __name__ == "__main__":
    unittest.main()
