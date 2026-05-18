#!/usr/bin/env python3
"""Run one autoresearch experiment: preflight, avg@N eval, logs, results.tsv."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone

EVALS = pathlib.Path(__file__).resolve().parent.parent
REPO = EVALS.parent
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

from experiment_loader import (  # noqa: E402
    apply_config_to_extractor_kwargs,
    load_experiment_config,
    set_experiment_dir,
)
from run_tool_eval import (  # noqa: E402
    ToolVariantReport,
    build_report_payload,
    run_one_variant,
)
from runner import AUTORESEARCH_SUBSET, FIXTURE  # noqa: E402
from tool_extractor import GroqToolExtractor, ToolExtractorConfig  # noqa: E402

AUTORESEARCH = pathlib.Path(__file__).resolve().parent
RESULTS_TSV = AUTORESEARCH / "results.tsv"
RUNS_DIR = AUTORESEARCH / "runs"


def _git_short_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _config_hash(exp_dir: pathlib.Path) -> str:
    parts: list[str] = []
    for name in ("config.json", "system_prompt_set_state.txt", "system_prompt_mutation.txt", "user_message_rules.txt"):
        p = exp_dir / name
        if p.exists():
            parts.append(p.read_text())
    return hashlib.sha256("".join(parts).encode()).hexdigest()[:12]


def _estimate_api_calls(cases: list[dict], variants: int, runs: int) -> int:
    total = 0
    for case in cases:
        snaps = case.get("liveSnapshots") or []
        steps = max(1, len(snaps))
        total += min(variants, len(case.get("transcriptVariants", [""]))) * runs * steps
    return total


def _load_cases(cfg: dict) -> list[dict]:
    data = json.loads(FIXTURE.read_text())
    cases = data["cases"]
    if cfg.get("cases"):
        want = set(cfg["cases"])
        cases = [c for c in cases if c["id"] in want]
    elif cfg.get("subset") == "autoresearch":
        want = set(AUTORESEARCH_SUBSET)
        cases = [c for c in cases if c["id"] in want]
    return cases


def _run_preflight(log: pathlib.Path, *, skip_tests: bool) -> bool:
    with log.open("a") as f:
        f.write("=== preflight ===\n")
        if skip_tests:
            f.write("tests skipped\n")
            return True
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-p", "test_*.py", "-q"],
            cwd=EVALS,
            capture_output=True,
            text=True,
        )
        f.write(proc.stdout)
        f.write(proc.stderr)
        return proc.returncode == 0


def run_experiment(
    *,
    exp_dir: pathlib.Path,
    description: str,
    dry_run: bool,
    max_api_calls: int | None,
    skip_tests: bool,
) -> int:
    cfg = load_experiment_config(exp_dir)
    set_experiment_dir(exp_dir)

    runs = int(cfg.get("runs", 2))
    variants = int(cfg.get("variants", 1))
    score_steps = bool(cfg.get("score_steps", True))
    strict_tools = bool(cfg.get("strict_tools", False))

    cases = _load_cases(cfg)
    est_calls = _estimate_api_calls(cases, variants, runs)

    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / tag
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "run.log"
    report_path = run_dir / "report.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "manifest.json"

    sha = _git_short_sha()
    cfg_hash = _config_hash(exp_dir)

    with log_path.open("w") as log:
        log.write(f"experiment_tag: {tag}\n")
        log.write(f"description: {description}\n")
        log.write(f"git_sha: {sha}\n")
        log.write(f"config_hash: {cfg_hash}\n")
        log.write(f"cases: {len(cases)}\n")
        log.write(f"estimated_api_calls: {est_calls}\n")
        log.write(f"tool_contract: {cfg.get('tool_contract')}\n")
        log.write(f"runs: {runs}\n")

    if max_api_calls is not None and est_calls > max_api_calls:
        print(
            f"Refusing run: estimated {est_calls} API calls > max {max_api_calls}",
            file=sys.stderr,
        )
        return 2

    if not _run_preflight(log_path, skip_tests=skip_tests):
        print("Preflight tests failed; see run.log", file=sys.stderr)
        return 2

    if dry_run:
        print(json.dumps({"dry_run": True, "run_dir": str(run_dir), "estimated_api_calls": est_calls}, indent=2))
        return 0

    ext_kw = apply_config_to_extractor_kwargs(cfg)
    extractor = GroqToolExtractor(ToolExtractorConfig(**ext_kw))
    started = time.time()

    reports: list[ToolVariantReport] = []
    with log_path.open("a") as log:
        for case in cases:
            for vi in range(min(variants, len(case["transcriptVariants"]))):
                label = f"{case['id']} v{vi} x{runs}"
                log.write(f"Running {label}...\n")
                log.flush()
                print(f"Running {label}...", flush=True)
                reports.append(
                    run_one_variant(
                        case,
                        variant_index=vi,
                        extractor=extractor,
                        capture_trace=score_steps,
                        score_steps=score_steps,
                        strict_tools=strict_tools,
                        runs=runs,
                    )
                )
                time.sleep(0.5)

    payload = build_report_payload(
        reports,
        model=cfg.get("model", "llama-3.1-8b-instant"),
        subset=cfg.get("subset", "autoresearch"),
        score_steps=score_steps,
        prompt_mode=cfg.get("prompt_mode", "full_and_fragment"),
        tool_contract=cfg.get("tool_contract", "set_state"),
        runs_per_variant=runs,
        temperature=float(cfg.get("temperature", 0.7)),
    )
    report_path.write_text(json.dumps(payload, indent=2))

    mean_key = f"mean_at_{runs}"
    mean_at_2 = payload[mean_key]
    elapsed = time.time() - started

    summary = {
        "experiment_tag": tag,
        "description": description,
        "git_sha": sha,
        "config_hash": cfg_hash,
        "mean_at_2": mean_at_2,
        "mean_pass_rate": payload["mean_pass_rate"],
        "mean_step_pass_rate": payload["mean_step_pass_rate"],
        "tool_warning_rate": payload["tool_warning_rate"],
        "api_error_rate": payload["api_error_rate"],
        "runs_per_variant": runs,
        "cases": len(cases),
        "elapsed_seconds": round(elapsed, 1),
        "report_path": str(report_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2))

    manifest = {
        "experiment_tag": tag,
        "started_at": tag,
        "git_sha": sha,
        "config_hash": cfg_hash,
        "experiment_dir": str(exp_dir),
        "fixture": str(FIXTURE),
        "estimated_api_calls": est_calls,
        "summary": summary,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))

    with log_path.open("a") as log:
        log.write(f"mean_at_{runs}: {mean_at_2}\n")
        log.write(f"mean_pass_rate: {payload['mean_pass_rate']}\n")
        log.write(f"elapsed_seconds: {elapsed:.1f}\n")

    _append_results_tsv(
        sha=sha,
        mean_at_2=mean_at_2,
        step_rate=payload["mean_step_pass_rate"],
        warning_rate=payload["tool_warning_rate"],
        api_error_rate=payload["api_error_rate"],
        status="complete",
        description=description,
    )

    print(f"mean_at_{runs}: {mean_at_2}")
    print(json.dumps(summary, indent=2))
    return 0


def _append_results_tsv(
    *,
    sha: str,
    mean_at_2: float,
    step_rate: float,
    warning_rate: float,
    api_error_rate: float,
    status: str,
    description: str,
) -> None:
    header = "commit\tmean_at_2\tstep_pass_rate\ttool_warning_rate\tapi_error_rate\tstatus\tdescription\n"
    if not RESULTS_TSV.exists():
        RESULTS_TSV.write_text(header)
    line = (
        f"{sha}\t{mean_at_2:.3f}\t{step_rate:.3f}\t{warning_rate:.3f}\t"
        f"{api_error_rate:.3f}\t{status}\t{description}\n"
    )
    with RESULTS_TSV.open("a") as f:
        f.write(line)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one autoresearch experiment")
    ap.add_argument(
        "--config",
        type=pathlib.Path,
        default=AUTORESEARCH / "experiment" / "config.json",
        help="Path to config.json (parent dir is experiment root)",
    )
    ap.add_argument("--description", default="experiment")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument(
        "--max-api-calls",
        type=int,
        default=120,
        help="Abort if estimated Groq calls exceed this (0 = no limit)",
    )
    args = ap.parse_args()
    exp_dir = args.config.parent
    max_calls = None if args.max_api_calls == 0 else args.max_api_calls
    return run_experiment(
        exp_dir=exp_dir,
        description=args.description,
        dry_run=args.dry_run,
        max_api_calls=max_calls,
        skip_tests=args.skip_tests,
    )


if __name__ == "__main__":
    raise SystemExit(main())
