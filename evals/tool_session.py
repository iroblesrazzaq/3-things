"""Live tool session state mirroring Swift VoiceDraftToolEnvironment + scheduler skips."""
from __future__ import annotations

from dataclasses import dataclass, field

from live_replay import LiveStep, should_skip_model_round
from tool_runner import ToolTraceExecutor, build_draft


@dataclass
class SessionState:
    selected_tasks: list[str] = field(default_factory=list)
    extra_candidates: list[str] = field(default_factory=list)
    processed_transcript_character_count: int = 0
    last_full_transcript: str = ""

    def to_executor(self) -> ToolTraceExecutor:
        ex = ToolTraceExecutor()
        ex.selected = list(self.selected_tasks)
        ex.extras = list(self.extra_candidates)
        return ex

    @classmethod
    def from_executor(cls, ex: ToolTraceExecutor, *, full: str, advance_processed: bool) -> SessionState:
        proc = len(full) if advance_processed else 0
        return cls(
            selected_tasks=list(ex.selected),
            extra_candidates=list(ex.extras),
            processed_transcript_character_count=proc if advance_processed else 0,
            last_full_transcript=full if advance_processed else "",
        )


@dataclass
class RoundResult:
    outcome_kind: str  # draft | no_draft
    no_draft_reason: str | None = None
    draft: object | None = None
    session: SessionState | None = None
    tool_messages: list[str] = field(default_factory=list)


def apply_tool_calls(
    session: SessionState | None,
    step: LiveStep,
    calls: list[dict],
) -> RoundResult:
    ex = session.to_executor() if session else ToolTraceExecutor()
    no_action: str | None = None

    # set_draft alone replaces state; ignore mixed sequences after first set_draft.
    set_calls = [c for c in calls if c.get("tool") == "set_draft"]
    if set_calls:
        r = ex.apply_set_draft(set_calls[-1])
        if r is not None:
            no_action = r
    else:
        for call in calls:
            r = ex.apply_call(call)
            if r is not None:
                no_action = r

    full = step.full_transcript
    if no_action and not ex.selected and not ex.extras:
        new_session = SessionState(
            processed_transcript_character_count=len(full),
            last_full_transcript=full,
        )
        reason = no_action if no_action in ("incomplete", "no_actionable", "unchanged") else "no_actionable"
        return RoundResult(
            outcome_kind="no_draft",
            no_draft_reason=reason,
            session=new_session,
            tool_messages=ex.messages,
        )

    if not ex.selected and not ex.extras:
        new_session = SessionState(
            processed_transcript_character_count=len(full),
            last_full_transcript=full,
        )
        return RoundResult(
            outcome_kind="no_draft",
            no_draft_reason="no_actionable",
            session=new_session,
            tool_messages=ex.messages,
        )

    try:
        draft = build_draft(
            list(ex.selected),
            list(ex.extras),
            len(ex.selected) + len(ex.extras) > 3,
            contains_actionable_tasks=True,
            cleaned_transcript=full,
        )
    except ValueError:
        new_session = SessionState(
            processed_transcript_character_count=len(full),
            last_full_transcript=full,
        )
        return RoundResult(
            outcome_kind="no_draft",
            no_draft_reason="no_actionable",
            session=new_session,
            tool_messages=ex.messages,
        )

    new_session = SessionState(
        selected_tasks=draft.selected_tasks,
        extra_candidates=draft.extra_candidates,
        processed_transcript_character_count=len(full),
        last_full_transcript=full,
    )
    return RoundResult(
        outcome_kind="draft",
        draft=draft,
        session=new_session,
        tool_messages=ex.messages,
    )


def apply_client_skip(session: SessionState | None, step: LiveStep) -> RoundResult:
    ex = session.to_executor() if session else ToolTraceExecutor()
    full = step.full_transcript
    if ex.selected or ex.extras:
        reason = "unchanged"
    else:
        reason = "incomplete"
    new_session = SessionState(
        selected_tasks=list(ex.selected),
        extra_candidates=list(ex.extras),
        processed_transcript_character_count=len(full),
        last_full_transcript=full,
    )
    return RoundResult(
        outcome_kind="no_draft",
        no_draft_reason=reason,
        session=new_session,
    )


@dataclass
class LiveStepResult:
    step: LiveStep
    calls: list[dict]
    session: SessionState | None
    outcome_kind: str
    no_draft_reason: str | None = None
    skipped: bool = False


def run_live_steps_with_results(
    steps: list[LiveStep],
    *,
    initial: SessionState | None,
    model_round,
) -> tuple[SessionState | None, list[LiveStepResult]]:
    """Execute steps; returns per-step session state and tool calls."""
    session = initial
    results: list[LiveStepResult] = []
    for step in steps:
        if should_skip_model_round(step):
            result = apply_client_skip(session, step)
            session = result.session
            results.append(
                LiveStepResult(
                    step=step,
                    calls=[{"tool": "no_action", "reason": result.no_draft_reason}],
                    session=session,
                    outcome_kind=result.outcome_kind,
                    no_draft_reason=result.no_draft_reason,
                    skipped=True,
                )
            )
            continue
        calls = model_round(step, session)
        result = apply_tool_calls(session, step, calls)
        session = result.session
        results.append(
            LiveStepResult(
                step=step,
                calls=calls,
                session=session,
                outcome_kind=result.outcome_kind,
                no_draft_reason=result.no_draft_reason,
                skipped=False,
            )
        )
    return session, results


def run_live_steps(
    steps: list[LiveStep],
    *,
    initial: SessionState | None,
    model_round,
) -> tuple[SessionState | None, list[dict]]:
    """Execute steps; model_round(step, session) -> list[tool calls]."""
    session, results = run_live_steps_with_results(steps, initial=initial, model_round=model_round)
    trace_steps = [
        {
            "full": r.step.full_transcript,
            "fragment": r.step.new_fragment,
            "finished": r.step.user_finished_speaking,
            "calls": r.calls,
        }
        for r in results
    ]
    return session, trace_steps
