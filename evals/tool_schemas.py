"""OpenAI-compatible tool definitions matching Swift ToolVoiceDraftExtractor."""
from __future__ import annotations

from typing import Literal

ToolContract = Literal["mutation", "set_state"]

TOOL_INSTRUCTIONS_V2 = """You extract 1–3 focus tasks for TODAY from English voice text. Use ONLY the tools—never prose lists or JSON outside tool calls.

Live update rules:
- Use the new fragment to decide what changed THIS round. Use the full transcript to resolve references and corrections.
- Preserve existing indexed tasks unless the user cancels or replaces them.
- NEVER call clear_draft for a normal fragment update. clear_draft is ONLY for explicit cancel-all / start-over (e.g. "forget both", "cancel everything", "start over").
- Each tool call must affect ONE task. Never put multiple tasks in one add_task or revise_task (no comma-separated blobs).
- If the fragment corrects an existing task, prefer revise_task on that slot.
- If the fragment cancels one task, delete_task that slot.
- If the fragment adds a new independent task, add_task once.
- Merge duplicate phrasings; drop future-day-only items (tomorrow, next week, not today); keep negative commitments (don't X, avoid X); collapse substeps under one parent; never invent tasks.

no_action: fragment too short, mic test / filler only, or nothing should change.

Examples (tool traces, not prose):
- New task: add_task("email Sam")
- Correction: revise_task selected slot 0 new_text "go to the store" (when [0] was park)
- Replacement: revise_task selected slot 0 new_text "text Alex" (when [0] was call Alex)
- Remove one: delete_task selected slot 1
- Cancel all: clear_draft
- No tasks: no_action reason no_actionable"""

SET_STATE_INSTRUCTIONS = """You extract 1–3 focus tasks for TODAY from English voice text. Output the COMPLETE desired draft state after this round using set_draft only.

Rules:
- Use the new fragment for what changed this round; use the full transcript for corrections and references.
- selected_tasks: up to 3 focus tasks for today, in order.
- extra_candidates: additional explicit tasks beyond the first 3 (overflow).
- contains_actionable_tasks: false only for mic test / filler / no actionable commitments.
- Never invent tasks. Respect cancellations, duplicates collapse, future-day exclusion, negative commitments, substep collapse.
- Do not output mutation tools—only set_draft with the full target state."""

TOOL_INSTRUCTIONS = TOOL_INSTRUCTIONS_V2


def groq_tools_mutation() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "add_task",
                "description": "Append exactly one new actionable task for today. Never multiple tasks in one call.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "revise_task",
                "description": "Replace text of one selected or extra task by index. One task only—never a comma-separated list.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pool": {"type": "string", "enum": ["selected", "extra"]},
                        "slot": {"type": "integer"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["pool", "slot", "new_text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_task",
                "description": "Remove one task by pool and index when the user cancels that item.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pool": {"type": "string", "enum": ["selected", "extra"]},
                        "slot": {"type": "integer"},
                    },
                    "required": ["pool", "slot"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "clear_draft",
                "description": "Remove ALL tasks ONLY when user explicitly cancels everything or starts over. Never for partial updates.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "no_action",
                "description": "Fragment incomplete, non-actionable, or no change needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "enum": ["incomplete", "no_actionable", "unchanged"],
                        }
                    },
                    "required": ["reason"],
                },
            },
        },
    ]


def groq_tools_set_state() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "set_draft",
                "description": "Set the complete draft state after applying this round's transcript.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selected_tasks": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "extra_candidates": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "contains_actionable_tasks": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "selected_tasks",
                        "extra_candidates",
                        "contains_actionable_tasks",
                    ],
                },
            },
        },
    ]


def groq_tools(contract: ToolContract = "mutation") -> list[dict]:
    if contract == "set_state":
        return groq_tools_set_state()
    return groq_tools_mutation()


def system_instructions(contract: ToolContract = "mutation") -> str:
    try:
        from experiment_loader import system_prompt_override

        override = system_prompt_override(contract)
        if override:
            return override
    except ImportError:
        pass
    if contract == "set_state":
        return SET_STATE_INSTRUCTIONS
    return TOOL_INSTRUCTIONS_V2
