"""Groq llama-3.1-8b-instant proxy extractor. Mirrors the on-device draft schema
(`VoiceExtractionDraft` / former `GeneratedVoiceDraft`) for snapshot JSON prompts.

Groq is fast and has generous limits, so the runner can parallelize. We use the
OpenAI-compatible chat completions endpoint with JSON-mode response_format.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import time
from dataclasses import dataclass

from dotenv import load_dotenv
import re

from openai import APIConnectionError, AuthenticationError, OpenAI, RateLimitError

from scorer import Draft

ENV_PATH = pathlib.Path("/Users/ismaelrobles-razzaq/2_cs_projects/env/llm_api/.env")
GROQ_BASE = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.1-8b-instant"


def _load_client() -> OpenAI:
    if not ENV_PATH.exists():
        raise RuntimeError(f"env file not found at {ENV_PATH}")
    load_dotenv(ENV_PATH)
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY missing from env")
    return OpenAI(api_key=key, base_url=GROQ_BASE)


@dataclass
class ExtractorConfig:
    model: str = DEFAULT_MODEL
    temperature: float = 0.7
    max_output_tokens: int = 256
    use_json_mode: bool = True
    repair: bool = False


class Extractor:
    def __init__(self, prompt_template: str, config: ExtractorConfig | None = None):
        self.prompt_template = prompt_template
        self.config = config or ExtractorConfig()
        self.client = _load_client()

    def extract(self, transcript: str) -> tuple[Draft | None, str | None]:
        trimmed = transcript.strip()
        if not trimmed:
            return None, "empty_transcript"

        # Sentinel-style substitution so `{` in JSON examples doesn't break str.format.
        if "{TRANSCRIPT}" in self.prompt_template:
            prompt = self.prompt_template.replace("{TRANSCRIPT}", trimmed)
        else:
            prompt = self.prompt_template.replace("{transcript}", trimmed)
        kwargs = dict(
            model=self.config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.config.temperature,
            max_tokens=self.config.max_output_tokens,
        )
        if self.config.use_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = None
        for attempt in range(12):  # enough retries to survive Groq free-tier TPM windows
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except RateLimitError as e:
                # Groq returns 'Please try again in 1.86s' — parse it. Fall back to a small backoff.
                msg = str(e)
                m = re.search(r"try again in ([0-9.]+)s", msg)
                base = float(m.group(1)) + 0.5 if m else min(2 ** attempt, 8.0)
                # Jitter so multiple threads don't all wake at the exact same instant and re-collide.
                wait = base + random.uniform(0, 0.5 * (attempt + 1))
                time.sleep(wait)
            except AuthenticationError as e:
                # Treat as a single-call failure, don't kill the whole run.
                return None, f"api_error:AuthenticationError:{str(e)[:120]}"
            except APIConnectionError as e:
                # Transient network issue — back off and retry.
                wait = 2.0 * (attempt + 1) + random.uniform(0, 1.5)
                time.sleep(wait)
                if attempt == 11:
                    return None, f"api_error:APIConnectionError:{str(e)[:120]}"
            except Exception as e:  # noqa: BLE001
                return None, f"api_error:{type(e).__name__}:{e}"

        if resp is None:
            return None, "api_error:exceeded_retries"

        raw = (resp.choices[0].message.content or "").strip() if resp.choices else ""
        parsed = _parse_json(raw)
        if parsed is None:
            return None, f"unparseable_output:{raw[:120]!r}"

        try:
            draft = _to_draft(parsed)
        except (KeyError, TypeError, ValueError) as e:
            return None, f"schema_error:{e}"

        if not draft.contains_actionable_tasks:
            return None, "empty_model_output"
        if not draft.selected_tasks:
            return None, "empty_model_output"

        if self.config.repair:
            from repair import repair_draft  # late import avoids circular w/ scorer
            draft = repair_draft(draft, transcript)
            if not draft.selected_tasks:
                return None, "empty_model_output"
        return draft, None


def _parse_json(raw: str) -> dict | None:
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        inner = [l for l in lines if not l.strip().startswith("```")]
        s = "\n".join(inner).strip()
        if s.lower().startswith("json"):
            s = s[4:].strip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None


def _to_draft(obj: dict) -> Draft:
    sel = _str_list(obj.get("selectedTasks", []))[:3]
    raw_extras = _str_list(obj.get("extraCandidates", []))

    seen = {s.lower() for s in sel}
    extras: list[str] = []
    for e in raw_extras:
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        extras.append(e)

    overflow = bool(obj.get("detectedMoreThanThree", False)) or bool(extras)
    raw_sel = obj.get("selectedTasks", [])
    if isinstance(raw_sel, list) and sum(1 for x in raw_sel if isinstance(x, str) and x.strip()) > 3:
        overflow = True

    return Draft(
        selected_tasks=sel,
        extra_candidates=extras,
        detected_more_than_three=overflow,
        contains_actionable_tasks=bool(obj.get("containsActionableTasks", False)),
    )


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item[:100].strip()
        if cleaned:
            out.append(cleaned)
    return out
