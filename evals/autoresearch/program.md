# autoresearch — voice live extraction

Autonomous overnight iteration on **prompt and harness** for multi-step Groq tool eval. Adapted from [Karpathy autoresearch](https://github.com/karpathy/autoresearch).

## Goal

Maximize **mean_at_2** on the `autoresearch` subset (8 representative cases, variant 0, 2 stochastic runs per case). With `--score-steps`, a run passes only when **final** and **every live step** pass fixture expectations.

Secondary metrics (log only unless tie-breaking): `mean_step_pass_rate`, `tool_warning_rate`, `api_error_rate`.

## Setup (once per campaign)

1. **Run tag**: e.g. `2026-05-19`. Branch: `git checkout -b autoresearch/2026-05-19`.
2. **Environment**: `GROQ_API_KEY` in shell (see repo `evals` venv).
3. **Read**:
   - `evals/autoresearch/README.md`
   - `extraction_behavior.md` (product rules)
   - `evals/autoresearch/experiment/config.json`
4. **Baseline**:
   ```bash
   cd evals
   .venv/bin/python autoresearch/run_experiment.py --description baseline
   ```
5. **Initialize tracking**: `results.tsv` is created automatically. Do not commit it.

## What you CAN edit

- `evals/autoresearch/experiment/config.json` — subset, runs, tool_contract, temperature
- `evals/autoresearch/experiment/system_prompt_set_state.txt`
- `evals/autoresearch/experiment/system_prompt_mutation.txt`
- `evals/autoresearch/experiment/user_message_rules.txt`
- Harness (with tests): `evals/tool_policy.py`, `evals/tool_session.py`, `evals/tool_extractor.py`, `evals/tool_runner.py`

Default contract: **`set_state`** (usually stronger than mutation on diagnostic).

## What you CANNOT edit

- `ThreeThings/Fixtures/voice_extraction_cases.json` (oracle)
- `evals/scorer.py`, `evals/step_scorer.py`, `evals/live_replay.py`
- `extraction_behavior.md` (unless user explicitly changes product spec)
- Do not install new packages

## Run one experiment

```bash
cd evals
.venv/bin/python autoresearch/run_experiment.py --description "your idea in one line"
```

Output (under `evals/autoresearch/runs/<timestamp>/`):

- `run.log` — progress
- `report.json` — full eval payload
- `summary.json` — mean_at_2 and secondary metrics
- `manifest.json` — git sha, config hash, paths

Grep metric from log:

```bash
grep "^mean_at_" autoresearch/runs/*/run.log | tail -1
```

## results.tsv

Tab-separated (do not commit):

```
commit	mean_at_2	step_pass_rate	tool_warning_rate	api_error_rate	status	description
```

## Keep / discard gate

After each experiment:

1. Read `summary.json` → `mean_at_2`
2. Compare to best row in `results.tsv` (or baseline)
3. **Keep** (advance branch) if:
   - `mean_at_2` improves by ≥ **0.05**, OR
   - `mean_at_2` ties (±0.02) AND `tool_warning_rate` drops meaningfully without new case regressions in `report.json` case_summaries
4. **Discard**: `git reset --hard` to previous keep commit
5. **Crash**: log `status=crash`, `mean_at_2=0`, fix obvious typos once; otherwise skip

**Simplicity**: Prefer prompt edits over large harness diffs. Deleting rules that help is a win.

## Promotion (not every loop)

Before claiming a real win:

- Re-run on `--subset expanded` or `full_live` with `--runs 2` (manual `run_tool_eval.py`)
- Do not overfit the 8-case autoresearch subset alone

## The experiment loop

Dedicated branch `autoresearch/<tag>`.

LOOP until interrupted:

1. Note current commit and best `mean_at_2`
2. Edit only allowed files; one focused hypothesis
3. `git add` + `git commit -m "autoresearch: …"`
4. Run:
   ```bash
   .venv/bin/python autoresearch/run_experiment.py --description "…" > /dev/null 2>&1
   ```
   (or redirect to `run.log` inside the run dir — script writes its own log)
5. Read `autoresearch/runs/<latest>/summary.json` or `grep mean_at_` on run.log
6. Append `results.tsv` (script does this on success)
7. Keep or `git reset --hard`
8. Inspect failures: `.venv/bin/python analyze_tools.py --latest`

**Budget**: ~48–80 Groq calls per experiment on default subset. If rate-limited, wait and retry; do not burn the daily cap on huge subsets.

**Timeout**: If a run exceeds **15 minutes**, kill and treat as crash.

**NEVER STOP** to ask the human during overnight mode. If stuck, try: shorter prompts, stronger clear_draft ban, set_state wording, harness block on `clear_draft`, tool_policy strict mode in config.

## Progress commands (human morning review)

```bash
.venv/bin/python autoresearch/summarize_results.py
.venv/bin/python analyze_tools.py --latest
tail -20 autoresearch/results.tsv
```

## Edge cases

| Situation | Action |
|-----------|--------|
| Groq 429 / TPD limit | Stop loop; log crash; resume after quota reset |
| `tool_use_failed` in report | Prompt/harness issue; check `variants[].runs[].error` |
| Tests fail preflight | Fix before counting experiment |
| API errors > 20% | Discard; do not tune scorer |
| Harness edit | Run full `unittest discover` |

## Path to production

When a candidate wins on expanded/full_live:

1. Copy winning `system_prompt_*.txt` → Swift tool extractor instructions
2. Port harness rules → `VoiceDraftSessionLogic` / post-processor
3. Run on-device `VoiceExtractionEvalRunner`
