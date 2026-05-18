"""Tests for SFT dataset export."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from export_sft_dataset import export_from_fixture

REPO = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"


class ExportSftTests(unittest.TestCase):
    def test_export_produces_records(self) -> None:
        records = export_from_fixture(FIXTURE, case_ids=["literal_one_email", "correction_never_mind_single"])
        self.assertGreaterEqual(len(records), 3)
        for rec in records:
            self.assertIn("messages", rec)
            self.assertEqual(rec["messages"][0]["role"], "system")
            self.assertIn("ideal_tool_calls", rec)
            self.assertIn("target_state", rec)

    def test_write_jsonl(self) -> None:
        records = export_from_fixture(FIXTURE, case_ids=["no_task_testing"])
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out.jsonl"
            out.write_text("\n".join(json.dumps(r) for r in records) + "\n")
            lines = out.read_text().strip().splitlines()
            self.assertGreaterEqual(len(lines), 1)
            parsed = json.loads(lines[0])
            self.assertEqual(parsed["case_id"], "no_task_testing")


if __name__ == "__main__":
    unittest.main()
