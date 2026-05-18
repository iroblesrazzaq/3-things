"""Offline tests for tool eval aggregation (avg@N)."""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from runner import RunOutcome
from tool_eval_aggregate import aggregate_tool_reports


@dataclass
class FakeReport:
    case_id: str
    category: str
    variant_index: int = 0
    replay_mode: str = "fixture_snapshots"
    steps: int = 2
    tool_rounds: int = 2
    runs: list = None
    pass_rate: float = 0.0
    first_pass: bool = False
    step_results: list | None = None
    tool_warning_count: int = 0
    api_error_count: int = 0

    def __post_init__(self):
        if self.runs is None:
            self.runs = []


class TestToolEvalAggregate(unittest.TestCase):
    def test_mean_at_2_two_cases(self):
        reports = [
            FakeReport(
                case_id="a",
                category="literal",
                pass_rate=1.0,
                first_pass=True,
                runs=[
                    RunOutcome(True, [], [], [], False, None),
                    RunOutcome(True, [], [], [], False, None),
                ],
            ),
            FakeReport(
                case_id="b",
                category="correction",
                pass_rate=0.5,
                first_pass=False,
                runs=[
                    RunOutcome(True, [], [], [], False, None),
                    RunOutcome(False, ["missing_task"], [], [], False, None),
                ],
            ),
        ]
        agg = aggregate_tool_reports(reports, runs_per_variant=2)
        self.assertEqual(agg["total_variants"], 2)
        self.assertAlmostEqual(agg["mean_pass_rate"], 0.75)
        self.assertAlmostEqual(agg["mean_at_2"], 1.5)
        self.assertEqual(len(agg["case_summaries"]), 2)
        self.assertEqual(agg["case_summaries"][0]["case_id"], "b")

    def test_empty_reports(self):
        agg = aggregate_tool_reports([], runs_per_variant=2)
        self.assertEqual(agg["mean_at_2"], 0.0)


if __name__ == "__main__":
    unittest.main()
