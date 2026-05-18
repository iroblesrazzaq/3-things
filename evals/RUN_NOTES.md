# Voice extraction eval — iteration notes

Proxy model: `llama-3.1-8b-instant` via Groq (free tier, 6000 TPM cap is the bottleneck).
Goal: avg@5 ≥ 3.5/5 (ideally 4.5/5) on every case in `extraction_behavior.md`.

## Diagnostic results (7 cases × 5 variants × 5 runs = 175 calls)

| version | overall avg@5 | notes |
|---|---|---|
| v0 baseline (Swift prompt) | 2.21/3 fast | corrections 0/3, dup 1.5/3, overflow 2/3 |
| v1 strict 11-rule list | 2.29/3 fast | corrections improved, duplicates regressed |
| v2 concise | 2.00/3 fast | too terse, lost overflow |
| v3 chain-of-thought | 2.14/3 fast | nailed overflow but broke corrections/dup |
| v4 few-shot | 2.36/3 fast | best fast, but literal regressed from poisoned examples |
| v5 extras-as-overflow-only | 0.86/3 fast | "think before writing" leaked reasoning into output |
| v6 strict + neutral examples | 2.57/3 fast | corrections perfect, dup still off |
| v7 v6 + more correction examples | 2.93/3 fast | only 1 correction variant still flunked |
| **v7 + repair.py** | **4.69/5 (175 calls)** | corrections/dup/literal/no_task/inference all ≥4.6; vague_taxes 3.4 (scorer rigidity) |

After stemmer fix (`tax`/`taxes`, `email`/`emails`, etc.) in scorer.py, expected vague_taxes to clear 4.5+.

## Key learnings

1. The model treats `extraCandidates` as a "I'm unsure" dumping ground. Reframe as overflow-only.
2. Cancellation handling needs explicit "the cancelled task is GONE — not in any field."
3. Few-shot examples poison the model toward putting examples' words in output ("park"→correction trigger). Use NEUTRAL terms in examples.
4. Deterministic post-processing (`repair.py`) crushes the rest: dedup, promote extras→selected when room, recompute overflow.

## Current run

`v7 + repair` on **expanded subset** (12 cases × 5 × 5 = 300 calls). Hits all 11 categories.

## Next steps

Once expanded run lands:

1. If every case ≥ 3.5/5: run full fixture (25 cases × 5 × 5 = 625 calls, ~60-90 min).
2. If 1-2 gaps: surgically add an example to v7 for that category, re-test on the failing case only, then redo expanded.
3. Lock prompt into `FoundationModelsVoiceDraftExtractor.swift` and port `repair.py` semantics into Swift `VoiceDraftPostProcessor`.

## Commands

```bash
# Fast iteration (42 calls, ~5 min):
python runner.py --prompt prompts/v7_more_correction_examples.txt --runs 3 --subset diagnostic --variants 2 --concurrency 2 --repair --out reports/dev.json

# Mid (expanded, 300 calls, ~45 min):
python runner.py --prompt prompts/v7_more_correction_examples.txt --runs 5 --subset expanded --concurrency 2 --repair --out reports/v7_repair_expanded.json

# Full fixture (625 calls, ~90 min):
python runner.py --prompt prompts/v7_more_correction_examples.txt --runs 5 --subset full --concurrency 2 --repair --out reports/v7_repair_full.json

# Analyze:
python analyze.py reports/<report>.json

# Tool-calling live replay (multi-step Groq; uses fixture liveSnapshots):
cd evals && .venv/bin/python run_tool_eval.py --subset diagnostic --variants 1 --concurrency 1 --out reports/tools_diagnostic.json

# Regenerate liveSnapshots from livePartials after editing partial scripts:
.venv/bin/python generate_live_snapshots.py --fixture ../ThreeThings/Fixtures/voice_extraction_cases.json --write

# Offline trace replay (ideal traces + captured multi-step):
.venv/bin/python run_tool_traces.py

# Partial harness (fragment + session state per round):
.venv/bin/python partial_harness.py walk --case correction_never_mind_single
.venv/bin/python -m unittest test_partial_harness test_live_replay_parity -q

# Smoke: offline invariants + scripted trace + Groq multi-step (needs GROQ_API_KEY):
.venv/bin/python smoke_partial_harness.py

# Multi-step Groq eval with per-step + final scoring:
.venv/bin/python run_tool_eval.py --subset diagnostic --variants 1 --score-steps --capture-trace --out reports/tools_steps_diagnostic.json

# Enrich fixture with liveSnapshots + liveStepExpectations (36 cases):
.venv/bin/python enrich_fixture_live.py --fixture ../ThreeThings/Fixtures/voice_extraction_cases.json

# Full live subset (expanded + 11 edge cases, ~23 cases):
.venv/bin/python run_tool_eval.py --subset full_live --variants 1 --score-steps --out reports/tools_full_live.json

# Edge-case subset only:
.venv/bin/python run_tool_eval.py --subset edge --variants 1 --score-steps --out reports/tools_edge.json

# Export SFT JSONL (76 multi-step rounds from fixture labels):
.venv/bin/python export_sft_dataset.py --out datasets/voice_tools_sft.jsonl

# Merge golden traces from passing Groq runs:
.venv/bin/python export_sft_dataset.py --from-traces traces/ --out datasets/voice_tools_sft_traces.jsonl

# All offline tests (fixture integrity, step scorer, SFT export):
.venv/bin/python -m unittest discover -q -p 'test_*.py'

# Walk live rounds: full + fragment per step (offline, no API):
.venv/bin/python partial_harness.py walk --case correction_never_mind_single
.venv/bin/python partial_harness.py walk --case correction_never_mind_single --show-prompt
.venv/bin/python partial_harness.py compare-prompts --case correction_never_mind_single

# Fragment ablation: full+fragment vs omit line (correction subset, needs GROQ_API_KEY):
.venv/bin/python run_fragment_ablation.py --score-steps --out reports/fragment_ablation.json
.venv/bin/python run_tool_eval.py --cases correction_never_mind_single --prompt-mode omit_fragment --score-steps

# Multi-step avg@2 (stochastic repeats per variant):
.venv/bin/python run_tool_eval.py --subset autoresearch --variants 1 --runs 2 --score-steps --tool-contract set_state --out reports/tools_autoresearch.json

# Overnight autoresearch (prompt + harness; see autoresearch/program.md):
set -a && . /path/to/llm_api/.env && set +a
.venv/bin/python autoresearch/run_experiment.py --dry-run
.venv/bin/python autoresearch/run_experiment.py --description baseline
.venv/bin/python autoresearch/summarize_results.py
.venv/bin/python analyze_tools.py --latest
```
