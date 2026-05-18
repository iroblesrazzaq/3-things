# Voice extraction autoresearch

Overnight prompt/harness iteration for live multi-step Groq eval. Read `program.md` before starting a campaign.

## Cursor Goal / skill

Use the project skill **voice-autoresearch** (`.cursor/skills/voice-autoresearch/SKILL.md`) as the Cursor Goal, or invoke with `/voice-autoresearch` in Agent chat. The skill points here and to `program.md`.

Shell entry point:

```bash
cd evals
./autoresearch/run_goal.sh --description baseline
./autoresearch/run_goal.sh --dry-run
```

## Quick start

```bash
cd evals
set -a && . /path/to/llm_api/.env && set +a

# Dry run (preflight only)
.venv/bin/python autoresearch/run_experiment.py --dry-run

# Baseline experiment
.venv/bin/python autoresearch/run_experiment.py --description baseline

# Inspect progress
tail -f autoresearch/runs/<latest>/run.log
cat autoresearch/results.tsv
.venv/bin/python analyze_tools.py autoresearch/runs/<latest>/report.json
```

## Editable (search space)

- `autoresearch/experiment/config.json`
- `autoresearch/experiment/system_prompt_*.txt`
- `autoresearch/experiment/user_message_rules.txt`
- `tool_policy.py`, `tool_session.py`, `tool_extractor.py` (harness; run tests after edits)

## Frozen (product oracle)

- `ThreeThings/Fixtures/voice_extraction_cases.json`
- `scorer.py`, `step_scorer.py`, `live_replay.py`
- `extraction_behavior.md`
