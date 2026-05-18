#!/usr/bin/env bash
# Entry point for Cursor Goals / voice-autoresearch skill.
set -euo pipefail
cd "$(dirname "$0")/.."
EVALS="$(pwd)"

if [[ -f "${GROQ_ENV_FILE:-}" ]]; then
  set -a && source "$GROQ_ENV_FILE" && set +a
elif [[ -f "$HOME/2_cs_projects/env/llm_api/.env" ]]; then
  set -a && source "$HOME/2_cs_projects/env/llm_api/.env" && set +a
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  exec .venv/bin/python autoresearch/run_experiment.py --dry-run "${@:2}"
fi

if [[ "${1:-}" == "--loop" ]]; then
  echo "Autoresearch loop: read evals/autoresearch/program.md and .cursor/skills/voice-autoresearch/SKILL.md"
  echo "Run experiments with: .venv/bin/python autoresearch/run_experiment.py --description '...'"
  exit 0
fi

exec .venv/bin/python autoresearch/run_experiment.py "$@"
