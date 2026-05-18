"""Groq tool-calling extractor for one live extraction round."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Literal

from openai import RateLimitError

from extractor import DEFAULT_MODEL, _load_client
from live_replay import LiveStep
from tool_schemas import ToolContract, groq_tools, system_instructions
from tool_session import SessionState

PromptMode = Literal["full_and_fragment", "omit_fragment", "blank_fragment"]


@dataclass
class ToolExtractorConfig:
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    max_output_tokens: int = 512
    prompt_mode: PromptMode = "full_and_fragment"
    tool_contract: ToolContract = "mutation"


def _format_indexed_list(label: str, items: list[str]) -> str:
    if not items:
        return f"{label}:\n(none)"
    lines = [f"{label}:"]
    for i, t in enumerate(items):
        lines.append(f"  [{i}] {t}")
    return "\n".join(lines)


def _processed_prefix(step: LiveStep, session: SessionState | None) -> str:
    if not session or session.processed_transcript_character_count <= 0:
        return ""
    full = step.full_transcript
    idx = min(session.processed_transcript_character_count, len(full))
    return full[:idx]


def format_user_message(
    step: LiveStep,
    session: SessionState | None,
    *,
    prompt_mode: PromptMode = "full_and_fragment",
    tool_contract: ToolContract = "mutation",
) -> str:
    """Build the user message sent to Groq for one live round."""
    selected = list(session.selected_tasks) if session else []
    extras = list(session.extra_candidates) if session else []
    prefix = _processed_prefix(step, session)

    lines = [
        f"Full transcript:\n{step.full_transcript}",
        _format_indexed_list("Current selected", selected),
        _format_indexed_list("Current extras", extras),
        f"Processed prefix length: {len(prefix)}",
        f"Processed prefix text:\n{prefix if prefix else '(none)'}",
    ]

    if prompt_mode == "full_and_fragment":
        fragment = step.new_fragment or "(empty)"
        lines.append(f"New fragment:\n{fragment}")
    elif prompt_mode == "blank_fragment":
        lines.append("New fragment:\n(empty)")
    # omit_fragment: no fragment line

    lines.extend(
        [
            f"User finished speaking: {'yes' if step.user_finished_speaking else 'no'}",
        ]
    )

    if tool_contract == "set_state":
        lines.append(
            "Output set_draft with the complete target state after this round. "
            "If there are still no actionable tasks, set contains_actionable_tasks to false."
        )
    else:
        lines.append(
            "Apply tools so the draft matches the transcript. "
            "If there are still no actionable tasks, call no_action."
        )

    try:
        from experiment_loader import user_message_rules

        extra = user_message_rules()
        if extra:
            lines.append(extra)
    except ImportError:
        pass

    return "\n".join(lines)


class GroqToolExtractor:
    def __init__(self, config: ToolExtractorConfig | None = None):
        self.config = config or ToolExtractorConfig()
        self.client = _load_client()

    def apply_round(self, step: LiveStep, session: SessionState | None) -> list[dict]:
        user_msg = format_user_message(
            step,
            session,
            prompt_mode=self.config.prompt_mode,
            tool_contract=self.config.tool_contract,
        )
        resp = self._create_completion(user_msg)
        message = resp.choices[0].message
        return _parse_tool_calls(message.tool_calls or [], self.config.tool_contract)

    def _create_completion(self, user_msg: str, *, max_attempts: int = 6):
        delay = 5.0
        last_err: RateLimitError | None = None
        for attempt in range(max_attempts):
            try:
                return self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {
                            "role": "system",
                            "content": system_instructions(self.config.tool_contract),
                        },
                        {"role": "user", "content": user_msg},
                    ],
                    tools=groq_tools(self.config.tool_contract),
                    tool_choice="required",
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_output_tokens,
                )
            except RateLimitError as err:
                last_err = err
                wait = _rate_limit_wait_seconds(err) or delay
                if attempt + 1 >= max_attempts:
                    raise
                time.sleep(wait)
                delay = min(delay * 1.5, 90.0)
        assert last_err is not None
        raise last_err


def _rate_limit_wait_seconds(err: RateLimitError) -> float | None:
    msg = str(err)
    m = re.search(r"try again in (?:(\d+)m)?([0-9.]+)s", msg, re.I)
    if m:
        minutes = int(m.group(1) or 0)
        seconds = float(m.group(2))
        return minutes * 60.0 + seconds + 1.0
    m = re.search(r"try again in ([0-9.]+)s", msg, re.I)
    if m:
        return float(m.group(1)) + 1.0
    return None


def _parse_tool_calls(tool_calls: list, contract: ToolContract) -> list[dict]:
    out: list[dict] = []
    for tc in tool_calls:
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        if name == "set_draft" and contract == "set_state":
            selected = args.get("selected_tasks") or []
            extras = args.get("extra_candidates") or []
            out.append(
                {
                    "tool": "set_draft",
                    "selected_tasks": [str(t) for t in selected],
                    "extra_candidates": [str(t) for t in extras],
                    "contains_actionable_tasks": bool(
                        args.get("contains_actionable_tasks", True)
                    ),
                    "reason": str(args.get("reason", "")),
                }
            )
            continue

        if name == "add_task":
            out.append({"tool": "add_task", "text": str(args.get("text", ""))})
        elif name == "revise_task":
            out.append(
                {
                    "tool": "revise_task",
                    "pool": str(args.get("pool", "selected")),
                    "slot": int(args.get("slot", 0)),
                    "new_text": str(args.get("new_text", "")),
                }
            )
        elif name == "delete_task":
            out.append(
                {
                    "tool": "delete_task",
                    "pool": str(args.get("pool", "selected")),
                    "slot": int(args.get("slot", 0)),
                }
            )
        elif name == "clear_draft":
            out.append({"tool": "clear_draft"})
        elif name == "no_action":
            reason = str(args.get("reason", "incomplete"))
            if reason not in ("incomplete", "no_actionable", "unchanged"):
                reason = "incomplete"
            out.append({"tool": "no_action", "reason": reason})
    return out
