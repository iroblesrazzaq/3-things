---
name: voice-autoresearch
description: >-
  Overnight autoresearch for Three Things voice live extraction. Iterates prompt
  and harness against frozen fixture oracles to maximize mean_at_2 on the 8-case
  Groq multi-step eval. Use when the user asks to run autoresearch, start an
  overnight research loop, tune tool prompts/harness, improve mean_at_2, follow
  evals/autoresearch/program.md, or attach this as a Cursor Goal for autonomous
  iteration.
---

# Voice extraction autoresearch

You are an autonomous researcher improving **live voice extraction** (prompt + harness). Read and follow **[evals/autoresearch/program.md](evals/autoresearch/program.md)** — it is the full loop spec.

## Primary objective

Maximize **`mean_at_2`** on the `autoresearch` subset (8 cases, variant 0, 2 stochastic Groq runs). With step scoring enabled, a run passes only when **final** and **all live steps** match fixture expectations.

## Before the first experiment

1. Ensure `GROQ_API_KEY` is loaded (user env file under `env/llm_api/.env`).
2. `cd evals` and use `.venv/bin/python` for all commands.
3. Create branch `autoresearch/<date>` if not already on one.
4. Run baseline:
   ```bash
   .venv/bin/python autoresearch/run_experiment.py --description baseline
   ```

## Each experiment (loop)

1. Edit only allowed files (see program.md — experiment prompts, harness modules).
2. Run unit tests: `.venv/bin/python -m unittest discover -p 'test_*.py' -q`
3. Run experiment:
   ```bash
   .venv/bin/python autoresearch/run_experiment.py --description "one-line hypothesis"
   ```
4. Read `autoresearch/runs/<latest>/summary.json` for `mean_at_2`.
5. Append is automatic in `results.tsv`; apply keep/discard gate from program.md.
6. **Do not ask the user** whether to continue during overnight mode.

## Progress inspection (human or you between experiments)

```bash
.venv/bin/python autoresearch/summarize_results.py
.venv/bin/python analyze_tools.py --latest
grep "^mean_at_" autoresearch/runs/*/run.log | tail -5
```

## Frozen (do not edit)

- `ThreeThings/Fixtures/voice_extraction_cases.json`
- `evals/scorer.py`, `evals/step_scorer.py`, `evals/live_replay.py`
- `extraction_behavior.md`

## Default harness

- `tool_contract`: `set_state` (see `autoresearch/experiment/config.json`)
- `prompt_mode`: `full_and_fragment`
- Prompt overrides: `autoresearch/experiment/system_prompt_*.txt`

## When blocked

- Groq rate limit (429 / TPD): wait and retry; do not burn quota on full fixture.
- Preflight tests fail: fix before counting the experiment.
- API errors > 20%: discard the change; tune prompt/harness, not the scorer.
