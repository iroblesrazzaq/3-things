"""Generate liveSnapshots from livePartials using scheduler debounce/min-char rules.

Usage:
    python generate_live_snapshots.py --fixture ../ThreeThings/Fixtures/voice_extraction_cases.json
    python generate_live_snapshots.py --case correction_never_mind_single --partials '["a","ab"]'
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

MIN_LIVE = 8
MIN_FLUSH = 2

# Hand-authored ASR growth scripts per diagnostic case (first variant).
DIAGNOSTIC_PARTIALS: dict[str, list[str]] = {
    "literal_three_store_park_food": [
        "Go",
        "Go to",
        "Go to a store",
        "Go to a store, go",
        "Go to a store, go to the park",
        "Go to a store, go to the park, and",
        "Go to a store, go to the park, and eat food.",
    ],
    "overflow_four_clean": [
        "Email Sam",
        "Email Sam, pay rent",
        "Email Sam, pay rent, buy milk",
        "Email Sam, pay rent, buy milk, call mom",
    ],
    "correction_never_mind_single": [
        "Go to the park",
        "Go to the park, wait",
        "Go to the park, wait never mind",
        "Go to the park, wait never mind, go",
        "Go to the park, wait never mind, go to the store.",
    ],
    "no_task_testing": [
        "Testing",
        "Testing, testing",
        "Testing, testing, one two",
        "Testing, testing, one two three.",
    ],
    "inference_store_only": [
        "I need to",
        "I need to go to",
        "I need to go to the store",
        "I need to go to the store today.",
    ],
    "duplicate_email_sam": [
        "Email Sam",
        "Email Sam, pay rent",
        "Email Sam, pay rent, send Sam an email",
    ],
    "vague_taxes": [
        "I should",
        "I should figure out",
        "I should figure out taxes",
        "I should figure out taxes this week.",
    ],
}

# Phrase-break rounds for partial harness (cannot be inferred from extending partials alone).
HAND_SNAPSHOTS: dict[str, list[str]] = {
    "correction_never_mind_single": [
        "Go to the park",
        "Go to the park, wait never mind, go to the store.",
    ],
    "literal_three_store_park_food": [
        "Go to a store",
        "Go to a store, go to the park",
        "Go to a store, go to the park, and eat food.",
    ],
    "duplicate_email_sam": [
        "Email Sam",
        "Email Sam, pay rent, send Sam an email",
    ],
    "overflow_four_clean": [
        "Email Sam",
        "Email Sam, pay rent",
        "Email Sam, pay rent, buy milk",
        "Email Sam, pay rent, buy milk, call mom",
    ],
}


def normalize(text: str) -> str:
    return text.strip()


def snapshots_from_partials(partials: list[str]) -> list[str]:
    """Collapse extending partials (debounce wins) and enforce min live chars."""
    cleaned = [normalize(p) for p in partials if normalize(p)]
    if not cleaned:
        return []

    emitted: list[str] = []
    for i, current in enumerate(cleaned):
        if len(current) < MIN_LIVE:
            continue
        if i + 1 < len(cleaned):
            nxt = cleaned[i + 1]
            if nxt.startswith(current) and nxt != current:
                continue
        if emitted and emitted[-1] == current:
            continue
        emitted.append(current)

    final = cleaned[-1]
    if len(final) >= MIN_FLUSH and (not emitted or emitted[-1] != final):
        emitted.append(final)
    elif emitted and len(final) >= MIN_FLUSH:
        emitted[-1] = final
    return emitted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=pathlib.Path)
    ap.add_argument("--write", action="store_true", help="Update fixture JSON in place")
    ap.add_argument("--subset", choices=["diagnostic"], default="diagnostic")
    ap.add_argument("--case", help="Single case id")
    ap.add_argument(
        "--snapshots",
        help='JSON array of snapshot strings, e.g. \'["a","b"]\' (with --case --write)',
    )
    args = ap.parse_args()

    if args.fixture is None:
        for case_id, partials in DIAGNOSTIC_PARTIALS.items():
            snaps = HAND_SNAPSHOTS.get(case_id) or snapshots_from_partials(partials)
            print(case_id)
            print("  partials:", len(partials), "snapshots:", len(snaps))
            for s in snaps:
                print("   -", s[:80])
        return 0

    if args.case and args.snapshots and args.fixture:
        data = json.loads(args.fixture.read_text())
        snaps = json.loads(args.snapshots)
        for case in data["cases"]:
            if case["id"] == args.case:
                case["liveSnapshots"] = [normalize(s) for s in snaps]
                break
        else:
            print(f"Unknown case {args.case}", file=__import__("sys").stderr)
            return 1
        if args.write:
            args.fixture.write_text(json.dumps(data, indent=2) + "\n")
            print(f"Wrote {args.fixture} ({args.case})")
        else:
            print(json.dumps(snaps, indent=2))
        return 0

    data = json.loads(args.fixture.read_text())
    diagnostic_ids = {
        "literal_three_store_park_food",
        "overflow_four_clean",
        "correction_never_mind_single",
        "no_task_testing",
        "inference_store_only",
        "duplicate_email_sam",
        "vague_taxes",
    }
    for case in data["cases"]:
        if case["id"] not in diagnostic_ids:
            continue
        partials = DIAGNOSTIC_PARTIALS.get(case["id"])
        if not partials:
            variant = case["transcriptVariants"][0]
            partials = clause_growth_partials(variant)
        case["livePartials"] = partials
        case["liveSnapshots"] = HAND_SNAPSHOTS.get(case["id"]) or snapshots_from_partials(partials)

    if args.write:
        args.fixture.write_text(json.dumps(data, indent=2) + "\n")
        print(f"Wrote {args.fixture}")
    else:
        print(json.dumps({c["id"]: c.get("liveSnapshots") for c in data["cases"] if c["id"] in diagnostic_ids}, indent=2))
    return 0


def clause_growth_partials(variant: str) -> list[str]:
    """Fallback: grow cumulative text on comma boundaries."""
    text = normalize(variant)
    parts = re.split(r"(,\s*)", text)
    partials: list[str] = []
    buf = ""
    for piece in parts:
        buf += piece
        partials.append(buf.strip())
    if not partials:
        partials = [text]
    return partials


if __name__ == "__main__":
    raise SystemExit(main())
