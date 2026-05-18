"""Offline tests for autoresearch harness (config hash, loader, dry-run)."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

EVALS = pathlib.Path(__file__).resolve().parent
AUTORESEARCH = EVALS / "autoresearch"


class TestExperimentLoader(unittest.TestCase):
    def test_load_default_config(self):
        from experiment_loader import load_experiment_config, set_experiment_dir

        set_experiment_dir(AUTORESEARCH / "experiment")
        cfg = load_experiment_config(AUTORESEARCH / "experiment")
        self.assertEqual(cfg["runs"], 2)
        self.assertEqual(cfg["tool_contract"], "set_state")

    def test_prompt_override(self):
        from experiment_loader import set_experiment_dir, system_prompt_override

        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "system_prompt_set_state.txt").write_text("CUSTOM PROMPT")
            set_experiment_dir(d)
            self.assertEqual(system_prompt_override("set_state"), "CUSTOM PROMPT")


class TestAutoresearchDryRun(unittest.TestCase):
    def test_dry_run_exits_zero(self):
        proc = subprocess.run(
            [
                sys.executable,
                str(AUTORESEARCH / "run_experiment.py"),
                "--dry-run",
                "--skip-tests",
            ],
            cwd=EVALS,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out.get("dry_run"))


class TestConfigHash(unittest.TestCase):
    def test_hash_changes_with_prompt(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "ar_run", AUTORESEARCH / "run_experiment.py"
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        _config_hash = mod._config_hash

        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "config.json").write_text("{}")
            (d / "system_prompt_set_state.txt").write_text("a")
            h1 = _config_hash(d)
            (d / "system_prompt_set_state.txt").write_text("b")
            h2 = _config_hash(d)
            self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
