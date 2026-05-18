"""Tests for partial (fragment + session) eval harness."""
from __future__ import annotations

import json
import pathlib
import unittest
from unittest.mock import MagicMock, patch

from live_replay import LiveStep, build_request, live_steps_for_case, live_steps_from_snapshots
from partial_harness import (
    ScriptedModelRound,
    TRACES_DIR,
    assert_partial_invariants,
    load_cases,
    run_offline_case,
    walk_case,
    walk_steps,
)
from scorer import score
from step_scorer import expectations_for_case, score_step
from tool_extractor import GroqToolExtractor
from tool_session import run_live_steps_with_results

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"


class PartialHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases()

    def test_correction_two_step_fragments(self) -> None:
        views = walk_case("correction_never_mind_single")
        self.assertEqual(len(views), 2)
        self.assertEqual(views[0].fragment, "Go to the park")
        self.assertTrue(views[0].fragment)
        self.assertNotEqual(views[1].fragment, views[1].full)
        self.assertIn("store", views[1].fragment)

    def test_literal_three_incremental_fragments(self) -> None:
        views = walk_case("literal_three_store_park_food")
        self.assertEqual(len(views), 3)
        self.assertEqual(views[0].fragment, views[0].full)
        self.assertIn("park", views[1].fragment)
        self.assertIn("eat food", views[2].fragment)
        self.assertNotEqual(views[2].fragment, views[2].full)

    def test_session_reset_non_prefix(self) -> None:
        session = {
            "selectedTasks": ["old"],
            "processedTranscriptCharacterCount": 10,
            "lastFullTranscript": "completely different",
        }
        step = build_request("new transcript entirely", False, session)
        self.assertEqual(step.new_fragment, "new transcript entirely")

    def test_client_skip_mid_sequence(self) -> None:
        full = "one, two, three, four, five, six, seven, eight"
        session_dict = {
            "selectedTasks": ["task"],
            "processedTranscriptCharacterCount": len(full),
            "lastFullTranscript": full,
        }
        step2 = build_request(full, False, session_dict)
        self.assertFalse(step2.new_fragment.strip())
        from live_replay import should_skip_model_round

        self.assertTrue(should_skip_model_round(step2))
        steps = [
            LiveStep(full_transcript=full, new_fragment=full, user_finished_speaking=False),
            LiveStep(full_transcript=full, new_fragment="", user_finished_speaking=False),
        ]
        views = walk_steps(steps)
        self.assertFalse(views[0].skip)
        self.assertTrue(views[1].skip)

    def test_scripted_trace_scores(self) -> None:
        case = self.cases["correction_never_mind_single"]
        _, trace, (draft, err) = run_offline_case(
            case, TRACES_DIR / "correction_never_mind_single.json"
        )
        attempt = score(case, draft, err)
        self.assertTrue(attempt.passed, [r.value for r in attempt.reasons])
        self.assertEqual(len(trace), 2)

    def test_walk_matches_live_steps_for_case(self) -> None:
        case = self.cases["correction_never_mind_single"]
        steps = live_steps_for_case(case)
        views = walk_case("correction_never_mind_single")
        self.assertEqual(len(views), len(steps))
        for v, s in zip(views, steps):
            self.assertEqual(v.full, s.full_transcript)
            self.assertEqual(v.fragment, s.new_fragment)
            self.assertEqual(v.finished, s.user_finished_speaking)

    def test_groq_prompt_shape(self) -> None:
        step = LiveStep(
            full_transcript="Go to the park",
            new_fragment="Go to the park",
            user_finished_speaking=False,
        )
        extractor = GroqToolExtractor()
        captured: list[str] = []

        def fake_create(**kwargs):
            captured.append(kwargs["messages"][1]["content"])
            msg = MagicMock()
            msg.tool_calls = [
                MagicMock(
                    function=MagicMock(
                        name="no_action",
                        arguments='{"reason": "incomplete"}',
                    )
                )
            ]
            choice = MagicMock()
            choice.message = msg
            resp = MagicMock()
            resp.choices = [choice]
            return resp

        extractor.client = MagicMock()
        extractor.client.chat.completions.create = fake_create
        extractor.apply_round(step, None)
        self.assertEqual(len(captured), 1)
        body = captured[0]
        self.assertIn("Full transcript:", body)
        self.assertIn("New fragment:", body)
        self.assertIn("Current selected:", body)
        self.assertIn("Go to the park", body)

    def test_scripted_trace_step_and_final_scoring(self) -> None:
        case = self.cases["correction_never_mind_single"]
        trace_path = TRACES_DIR / "correction_never_mind_single.json"
        data = json.loads(trace_path.read_text())
        steps = live_steps_for_case(case)
        from partial_harness import ScriptedModelRound

        scripted = ScriptedModelRound(data["steps"])
        _, live_results = run_live_steps_with_results(
            steps, initial=None, model_round=scripted
        )
        step_exps = expectations_for_case(case)
        for i, (lr, exp) in enumerate(zip(live_results, step_exps)):
            sess = lr.session
            sr = score_step(
                exp,
                selected=list(sess.selected_tasks) if sess else [],
                extras=list(sess.extra_candidates) if sess else [],
                calls=lr.calls,
            )
            self.assertTrue(sr.passed, f"step {i}: {sr.reasons}")
        _, _, (draft, err) = run_offline_case(case, trace_path)
        attempt = score(case, draft, err)
        self.assertTrue(attempt.passed)

    def test_scripted_model_round_full_mismatch_raises(self) -> None:
        steps = live_steps_for_case(self.cases["correction_never_mind_single"])
        scripted = ScriptedModelRound(
            [{"full": "wrong text", "calls": [{"tool": "no_action", "reason": "unchanged"}]}]
        )
        with self.assertRaises(AssertionError):
            scripted(steps[0], None)


if __name__ == "__main__":
    unittest.main()
