"""Validate a generated Case file against the schema + game-logic rules.

Usage:
    python tools/validate_case.py narrative/sample_case.json [--context narrative/game_context.json]

Exit code 0 = valid. Used by benchmark_llm.py to compute the
"valid JSON" and "logic checks pass" KPIs. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CASE_TYPES = {"standard", "accomplice", "suicide"}
BANNED_IMAGE_WORDS = [
    "blood", "bloody", "gore", "corpse", "dead body", "wound", "stab", "gun",
    "knife", "kill", "murder", "suicide", "hanging", "hanged", "poison", "decapitat",
]
REQUIRED_TOP = [
    "case_number", "case_type", "victim", "killer", "accomplice", "weapon", "motive",
    "crime_location", "time_of_death", "truth_summary", "crime_scene_prompt",
    "host_announcement", "key_clues", "minor_clues", "false_clues", "npc_secrets",
]


def parse_llm_json(text: str) -> dict:
    """Parse model output, tolerating ```json fences and leading/trailing prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("top-level JSON is not an object")
    return obj


def _banned(prompt: str) -> list[str]:
    low = prompt.lower()
    return [w for w in BANNED_IMAGE_WORDS if re.search(r"\b" + re.escape(w), low)]


def validate(case: dict, ctx: dict) -> tuple[list[str], list[str]]:
    """Return (schema_errors, logic_errors). Both empty = valid."""
    schema: list[str] = []
    logic: list[str] = []

    for key in REQUIRED_TOP:
        if key not in case:
            schema.append(f"missing field '{key}'")
    for key in ("key_clues", "minor_clues", "false_clues", "npc_secrets"):
        if key in case and not isinstance(case[key], list):
            schema.append(f"'{key}' must be a list")
    if schema:
        return schema, logic

    alive = set(ctx["alive"])
    det = ctx["detective"]
    places = set(ctx["locations"]) | {ctx.get("dormitory_prefix", "dorm_") + a for a in alive}
    skills = {c["skill"] for c in ctx["characters"]}

    ctype = case["case_type"]
    victim, killer, acc = case["victim"], case["killer"], case["accomplice"]

    if ctype not in CASE_TYPES:
        schema.append(f"case_type '{ctype}' not in {sorted(CASE_TYPES)}")
    if victim not in alive:
        logic.append(f"victim '{victim}' is not alive/known")
    if det in (victim, killer, acc):
        logic.append("detective is victim, killer or accomplice")

    culprit = victim if ctype == "suicide" else killer
    if ctype == "suicide":
        if killer is not None or acc is not None:
            logic.append("suicide case must have killer=null and accomplice=null")
    else:
        if killer not in alive:
            logic.append(f"killer '{killer}' is not alive/known")
        if killer == victim:
            logic.append("killer == victim in a non-suicide case")
        if ctype == "accomplice":
            if acc not in alive or acc in (killer, victim):
                logic.append(f"accomplice '{acc}' invalid (must be alive, distinct)")
        elif acc is not None:
            logic.append("standard case must have accomplice=null")

    if case["crime_location"] not in places:
        logic.append(f"crime_location '{case['crime_location']}' unknown")

    # Key clues
    kc = case["key_clues"]
    if not 4 <= len(kc) <= 5:
        logic.append(f"{len(kc)} key clues (need 4-5)")
    ids: list[str] = []
    to_culprit = 0
    skill_locked = 0
    for c in kc:
        for f in ("id", "name", "location", "description", "points_to", "image_prompt"):
            if f not in c:
                schema.append(f"key clue missing '{f}'")
        if "id" not in c:
            continue
        ids.append(c["id"])
        if c.get("location") not in places:
            logic.append(f"key clue {c['id']} location '{c.get('location')}' unknown")
        if c.get("points_to") == culprit:
            to_culprit += 1
        rs = c.get("requires_skill")
        if rs:
            skill_locked += 1
            if rs not in skills:
                logic.append(f"key clue {c['id']} requires unknown skill '{rs}'")
        bad = _banned(c.get("image_prompt", ""))
        if bad:
            logic.append(f"key clue {c['id']} image_prompt not filter-safe: {bad}")
    if to_culprit < 2:
        logic.append(f"only {to_culprit} key clue(s) point to the culprit (need >= 2)")
    if skill_locked > 2:
        logic.append(f"{skill_locked} skill-locked key clues (max 2)")

    for c in case["minor_clues"]:
        ids.append(c.get("id", "?"))
        if c.get("location") not in places:
            logic.append(f"minor clue {c.get('id')} location unknown")
    if not 3 <= len(case["minor_clues"]) <= 6:
        logic.append(f"{len(case['minor_clues'])} minor clues (need 3-6)")

    fc = case["false_clues"]
    if not 2 <= len(fc) <= 3:
        logic.append(f"{len(fc)} false clues (need 2-3)")
    for c in fc:
        ids.append(c.get("id", "?"))
        if c.get("planted_by") not in alive:
            logic.append(f"false clue {c.get('id')} planted_by unknown")
        if c.get("points_to") == culprit:
            logic.append(f"false clue {c.get('id')} points to the real culprit")

    if len(ids) != len(set(ids)):
        schema.append("duplicate clue ids")

    # NPC secrets
    expected = alive - {det, victim}
    got = {s.get("character") for s in case["npc_secrets"]}
    missing = expected - got
    if missing:
        logic.append(f"npc_secrets missing for {sorted(missing)}")
    if got - expected:
        logic.append(f"npc_secrets for non-NPCs {sorted(got - expected)}")
    liars = 0
    all_ids = set(ids)
    for s in case["npc_secrets"]:
        ch = s.get("character")
        if s.get("is_lying"):
            liars += 1
        if ch in (killer, acc) and not s.get("is_lying"):
            logic.append(f"culprit '{ch}' is not marked as lying")
        for k in s.get("knows", []):
            if k not in all_ids:
                logic.append(f"{ch} knows unknown clue '{k}'")
    innocent_liars = liars - (1 if killer else 0) - (1 if acc else 0)
    if innocent_liars < 2:
        logic.append(f"only {innocent_liars} innocent NPC(s) lie/hide secrets (need >= 2)")

    bad = _banned(case["crime_scene_prompt"])
    if bad:
        logic.append(f"crime_scene_prompt not filter-safe: {bad}")

    return schema, logic


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--context", default=str(Path(__file__).parent.parent / "narrative" / "game_context.json"))
    a = ap.parse_args()
    ctx = json.loads(Path(a.context).read_text(encoding="utf-8"))
    try:
        case = parse_llm_json(Path(a.case).read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError) as e:
        print(f"INVALID JSON: {e}")
        return 2
    schema, logic = validate(case, ctx)
    for e in schema:
        print("SCHEMA:", e)
    for e in logic:
        print("LOGIC: ", e)
    if not schema and not logic:
        print("OK: case file is valid")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
