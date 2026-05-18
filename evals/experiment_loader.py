"""Load autoresearch experiment prompts and config from evals/autoresearch/experiment/."""
from __future__ import annotations

import json
import pathlib
from typing import Literal

from tool_schemas import ToolContract

REPO = pathlib.Path(__file__).resolve().parent
DEFAULT_EXPERIMENT_DIR = REPO / "autoresearch" / "experiment"

_override_mutation: str | None = None
_override_set_state: str | None = None
_override_user_rules: str | None = None
_experiment_dir: pathlib.Path | None = None


def set_experiment_dir(path: pathlib.Path | None) -> None:
    global _experiment_dir, _override_mutation, _override_set_state, _override_user_rules
    _experiment_dir = path
    _override_mutation = None
    _override_set_state = None
    _override_user_rules = None


def _dir() -> pathlib.Path:
    return _experiment_dir or DEFAULT_EXPERIMENT_DIR


def load_experiment_config(path: pathlib.Path | None = None) -> dict:
    cfg_path = (path or _dir()) / "config.json"
    if not cfg_path.exists():
        return {}
    return json.loads(cfg_path.read_text())


def system_prompt_override(contract: ToolContract) -> str | None:
    global _override_mutation, _override_set_state
    d = _dir()
    if contract == "set_state":
        if _override_set_state is None:
            p = d / "system_prompt_set_state.txt"
            _override_set_state = p.read_text().strip() if p.exists() else ""
        return _override_set_state or None
    if _override_mutation is None:
        p = d / "system_prompt_mutation.txt"
        _override_mutation = p.read_text().strip() if p.exists() else ""
    return _override_mutation or None


def user_message_rules() -> str | None:
    global _override_user_rules
    if _override_user_rules is None:
        p = _dir() / "user_message_rules.txt"
        _override_user_rules = p.read_text().strip() if p.exists() else ""
    return _override_user_rules or None


PromptMode = Literal["full_and_fragment", "omit_fragment", "blank_fragment"]


def apply_config_to_extractor_kwargs(cfg: dict) -> dict:
    """Map experiment config.json fields to ToolExtractorConfig kwargs."""
    out: dict = {}
    if "model" in cfg:
        out["model"] = cfg["model"]
    if "temperature" in cfg:
        out["temperature"] = float(cfg["temperature"])
    if "prompt_mode" in cfg:
        out["prompt_mode"] = cfg["prompt_mode"]
    if "tool_contract" in cfg:
        out["tool_contract"] = cfg["tool_contract"]
    return out
