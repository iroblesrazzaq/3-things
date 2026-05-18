"""Replay fixture liveSnapshots into LiveStep sequences (Swift scheduler parity)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LiveStep:
    full_transcript: str
    new_fragment: str
    user_finished_speaking: bool


def normalize(text: str) -> str:
    return text.strip()


def should_reset_session(existing: dict | None, full: str) -> bool:
    if not existing:
        return False
    last = existing.get("lastFullTranscript") or existing.get("last_full_transcript") or ""
    if not last:
        return False
    if full == last:
        return False
    if full.startswith(last):
        return False
    return True


def new_fragment(full: str, session: dict | None) -> str:
    if not session:
        return full
    idx = int(session.get("processedTranscriptCharacterCount") or session.get("processed_transcript_character_count") or 0)
    if idx <= 0 or idx > len(full):
        return full
    return full[idx:].strip()


def build_request(full: str, finished: bool, session: dict | None) -> LiveStep:
    clean = normalize(full)
    reset = should_reset_session(session, clean)
    existing = None if reset else session
    fragment = clean if reset else new_fragment(clean, existing)
    return LiveStep(
        full_transcript=clean,
        new_fragment=fragment,
        user_finished_speaking=finished,
    )


def advance_session_after_round(session: dict | None, step: LiveStep, *, skipped: bool) -> dict:
    if skipped:
        # Client skip advances via env snapshot; mirror by advancing processed index only when unchanged/incomplete
        proc = len(step.full_transcript)
        return {
            "selectedTasks": (session or {}).get("selectedTasks") or (session or {}).get("selected_tasks") or [],
            "extraCandidates": (session or {}).get("extraCandidates") or (session or {}).get("extra_candidates") or [],
            "processedTranscriptCharacterCount": proc,
            "lastFullTranscript": step.full_transcript,
        }
    return {
        "selectedTasks": (session or {}).get("selectedTasks") or (session or {}).get("selected_tasks") or [],
        "extraCandidates": (session or {}).get("extraCandidates") or (session or {}).get("extra_candidates") or [],
        "processedTranscriptCharacterCount": len(step.full_transcript),
        "lastFullTranscript": step.full_transcript,
    }


def should_skip_model_round(step: LiveStep) -> bool:
    return not step.new_fragment.strip() and not step.user_finished_speaking


def live_steps_from_snapshots(snapshots: list[str]) -> list[LiveStep]:
    if not snapshots:
        return []
    session: dict | None = None
    steps: list[LiveStep] = []
    for i, raw in enumerate(snapshots):
        finished = i == len(snapshots) - 1
        step = build_request(raw, finished, session)
        steps.append(step)
        if should_skip_model_round(step):
            session = advance_session_after_round(session, step, skipped=True)
        else:
            session = advance_session_after_round(session, step, skipped=False)
    return steps


def live_steps_for_case(case: dict, *, variant_index: int = 0) -> list[LiveStep]:
    snapshots = case.get("liveSnapshots")
    if snapshots:
        return live_steps_from_snapshots(snapshots)
    partials = case.get("livePartials")
    if partials:
        from generate_live_snapshots import snapshots_from_partials

        return live_steps_from_snapshots(snapshots_from_partials(partials))
    variant = case["transcriptVariants"][variant_index]
    from generate_live_snapshots import clause_growth_partials, snapshots_from_partials

    return live_steps_from_snapshots(snapshots_from_partials(clause_growth_partials(variant)))
