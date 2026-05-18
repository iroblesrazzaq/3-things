"""Add liveSnapshots, livePartials, and liveStepExpectations to fixture cases.

Usage:
    python enrich_fixture_live.py --fixture ../ThreeThings/Fixtures/voice_extraction_cases.json
    python enrich_fixture_live.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re

from generate_live_snapshots import DIAGNOSTIC_PARTIALS, HAND_SNAPSHOTS, snapshots_from_partials
from step_expectation_builder import build_step_expectations

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO / "ThreeThings" / "Fixtures" / "voice_extraction_cases.json"

# Cases with hand-tuned expectations — do not overwrite expectations.
HAND_EXPECTATIONS = {
    "literal_three_store_park_food",
    "overflow_four_clean",
    "correction_never_mind_single",
    "duplicate_email_sam",
    "no_task_testing",
    "inference_store_only",
    "vague_taxes",
}

# Cumulative snapshot scripts (first transcript variant semantics).
CASE_SNAPSHOTS: dict[str, list[str]] = {
    **HAND_SNAPSHOTS,
    "literal_one_email": ["Email Sam."],
    "literal_two_call_and_pay": ["Call mom", "Call mom and pay rent."],
    "overflow_six_messy": [
        "Finish the deck",
        "Finish the deck, call Alex",
        "Finish the deck, call Alex, book dentist",
        "Finish the deck, call Alex, book dentist, buy milk",
        "Finish the deck, call Alex, book dentist, buy milk, clean the kitchen",
        "Finish the deck, call Alex, book dentist, buy milk, clean the kitchen, return the package",
    ],
    "overflow_one_extra_only": [
        "Do laundry",
        "Do laundry, submit timesheet",
        "Do laundry, submit timesheet, text Jamie",
        "Do laundry, submit timesheet, text Jamie, and take out trash.",
    ],
    "correction_replace_call_with_text": [
        "Call Alex",
        "Call Alex, actually make that text Alex.",
    ],
    "correction_remove_one_keep_others": [
        "Email Sam",
        "Email Sam, go to the gym",
        "Email Sam, go to the gym, actually skip gym, and pay rent.",
    ],
    "duplicate_grocery_wording": [
        "Buy milk",
        "Buy milk, get milk from the store, and call mom.",
    ],
    "no_task_random_talk": ["I'm tired and I don't really know what I'm doing today."],
    "inference_eat_food_only": ["Eat food."],
    "inference_doctor": ["Call the doctor."],
    "ramble_two_clear_tasks": [
        "I have a lot going on, um, but really today I need to finish the deck and book the dentist."
    ],
    "ramble_three_clear_tasks": [
        "Um okay so today I need to ship the build, reply to Nora, and clean my desk. That's it."
    ],
    "vague_apartment": ["Deal with apartment stuff."],
    "substeps_launch_email": [
        "For the launch email, write the subject line",
        "For the launch email, write the subject line, draft the body, and send it.",
    ],
    "separate_not_substeps": [
        "Write launch email",
        "Write launch email, call Sam",
        "Write launch email, call Sam, and pay rent.",
    ],
    "future_tomorrow_exclude": [
        "Pay rent today.",
        "Tomorrow I need to call Sam, but today I need to pay rent.",
    ],
    "future_prepare_today": ["For tomorrow's meeting, prepare the notes today."],
    "negative_no_twitter": ["Don't scroll Twitter."],
    "correction_forget_everything": [
        "Email Sam",
        "Email Sam, pay rent",
        "Email Sam, pay rent, actually forget both.",
    ],
    "correction_park_to_store_direct": [
        "Go to the park",
        "Go to the park, actually go to the store.",
    ],
    "overflow_then_drop_fourth": [
        "Email Sam",
        "Email Sam, pay rent",
        "Email Sam, pay rent, buy milk",
        "Email Sam, pay rent, buy milk, and call mom",
        "Email Sam, pay rent, buy milk, scratch call mom.",
    ],
    "no_task_then_one_task": [
        "Testing, testing",
        "Testing, testing, one two three. Email Sam.",
    ],
    "duplicate_pay_rent_thrice": [
        "Pay rent",
        "Pay rent, pay the rent, and pay rent again.",
    ],
    "literal_exactly_three_no_overflow": [
        "Email Sam",
        "Email Sam, pay rent",
        "Email Sam, pay rent, buy milk",
    ],
    "negative_plus_positive": [
        "Don't scroll Twitter",
        "Don't scroll Twitter, and email Sam.",
    ],
    "inference_doctor_ramble": [
        "I've been putting off health stuff, but today I need to call the doctor.",
    ],
    "substeps_incremental_launch": [
        "Launch email: subject line",
        "Launch email: subject line, body",
        "Launch email: subject line, body, send it.",
    ],
    "vague_taxes_not_specific": [
        "Figure out taxes",
        "Figure out taxes, not file the return.",
    ],
    "future_intraday_correction": [
        "Call Sam tomorrow",
        "Call Sam tomorrow, wait, call Sam today.",
    ],
}


def _partials_from_snapshots(snapshots: list[str]) -> list[str]:
    """Approximate ASR growth from cumulative snapshots."""
    if not snapshots:
        return []
    partials: list[str] = []
    for snap in snapshots:
        words = snap.replace(",", " ,").split()
        for n in range(1, len(words) + 1):
            chunk = " ".join(words[:n]).replace(" ,", ",")
            if not partials or partials[-1] != chunk:
                partials.append(chunk)
    return partials


def enrich_case(case: dict, *, force_snapshots: bool = False) -> dict:
    case_id = case["id"]
    out = dict(case)

    if case_id in CASE_SNAPSHOTS:
        snaps = CASE_SNAPSHOTS[case_id]
    elif case_id in DIAGNOSTIC_PARTIALS:
        snaps = snapshots_from_partials(DIAGNOSTIC_PARTIALS[case_id])
    else:
        transcript = (case.get("transcriptVariants") or [""])[0]
        snaps = [transcript.strip()] if transcript.strip() else []

    if force_snapshots or not out.get("liveSnapshots"):
        out["liveSnapshots"] = snaps

    if not out.get("livePartials"):
        out["livePartials"] = _partials_from_snapshots(out["liveSnapshots"])

    if case_id in HAND_EXPECTATIONS and out.get("liveStepExpectations"):
        return out

    built = build_step_expectations(out, out["liveSnapshots"])
    if len(built) != len(out["liveSnapshots"]):
        raise ValueError(
            f"{case_id}: built {len(built)} expectations for {len(out['liveSnapshots'])} snapshots"
        )
    out["liveStepExpectations"] = built
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=pathlib.Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-snapshots", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.fixture.read_text())
    cases = data.get("cases", [])
    enriched = [
        enrich_case(c, force_snapshots=args.force_snapshots) for c in cases
    ]
    data["cases"] = enriched
    data["version"] = max(int(data.get("version", 2)), 3)

    if args.dry_run:
        missing = [c["id"] for c in enriched if not c.get("liveSnapshots")]
        print(f"cases={len(enriched)} missing_snapshots={len(missing)}")
        for c in enriched:
            snaps = len(c.get("liveSnapshots") or [])
            exps = len(c.get("liveStepExpectations") or [])
            print(f"  {c['id']}: snapshots={snaps} expectations={exps}")
        return 0

    args.fixture.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {args.fixture} ({len(enriched)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
