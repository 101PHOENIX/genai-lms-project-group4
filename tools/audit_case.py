"""Design audit of case files: the KPIs added after the jury self-critique (2026-11-25).

validate_case.py answers "is the JSON legal?". This answers "is it a fair, playable mystery?":

  solvable_min_actions  fewest investigation actions (visit a location / question an NPC)
                        that collect >= 2 key clues pointing to the culprit, ignoring
                        skill-locked clues (a 6 is never guaranteed). None = unsolvable.
  p_enough_actions      P(7 dice rounds give >= solvable_min_actions actions), exact.
  culprit_margin        key clues pointing to the culprit minus the most-accused innocent
                        (key + false clues). <= 0 means the evidence does not single anyone out.
  culprit_share         share of key clues pointing to the culprit (>= 0.8 = too easy).
  key_false_overlap     a key clue that duplicates a false clue (same location, similar text).
  filter_risk_words     image-prompt words outside the banned list that providers still flag.
  derivative_phrases    host lines that copy the reference franchise's stock announcement.

Usage:
  python tools/audit_case.py narrative/sample_case.json baselines/baseline-v1-pollinations/run*.txt
  python tools/audit_case.py --json out.json <files...>
Standard library only.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_case import parse_llm_json, validate  # noqa: E402

ROUNDS = 7
ACTIONS_PER_ROLL = {1: 0, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2}
EXTRA_FILTER_WORDS = ["blade", "dagger", "weapon", "strangl", "choke", "dying", "death", "died",
                      "slash", "rope", "noose", "overdose", "pills", "gunshot", "bullet", "victim"]
DERIVATIVE = [r"a body has been discovered", r"ding[- ]?dong", r"class trial", r"punishment time"]


def _action_distribution() -> dict[int, float]:
    c: Counter[int] = Counter()
    for rolls in itertools.product(range(1, 7), repeat=ROUNDS):
        c[sum(ACTIONS_PER_ROLL[r] for r in rolls)] += 1
    total = 6 ** ROUNDS
    return {k: v / total for k, v in sorted(c.items())}


ACTION_DIST = _action_distribution()


def p_at_least(n: int | None) -> float:
    return 0.0 if n is None else sum(p for k, p in ACTION_DIST.items() if k >= n)


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-záéíóúñ]+", (s or "").lower()) if len(w) > 3}


def solver(case: dict, culprit: str | None, need: int = 2, culprit_only: bool = True) -> int | None:
    """Min actions to hold `need` key clues (culprit-pointing ones if culprit_only), no skill locks.

    Model ("generous"): one action at a location reveals every clue there; questioning an
    innocent NPC reveals its `knows`. The killer/accomplice never hand over evidence.
    """
    good = {k["id"] for k in case.get("key_clues", [])
            if (not culprit_only or k.get("points_to") == culprit) and not k.get("requires_skill")}
    if need <= 0:
        need = len(good)
    if len(good) < need or not good:
        return None
    guilty = {case.get("killer"), case.get("accomplice")} - {None, ""}
    sources: dict[str, set[str]] = {}
    for k in case.get("key_clues", []):
        if k["id"] in good:
            sources.setdefault("loc:" + str(k.get("location")), set()).add(k["id"])
    for s in case.get("npc_secrets", []):
        got = good & set(s.get("knows") or [])
        if got and s.get("character") not in guilty:
            sources.setdefault("npc:" + str(s.get("character")), set()).update(got)
    keys = list(sources)
    for size in range(1, min(len(keys), 14) + 1):
        for combo in itertools.combinations(keys, size):
            if len(set().union(*(sources[c] for c in combo))) >= need:
                return size
    return None


def audit(case: dict, ctx: dict) -> dict:
    schema, logic = validate(case, ctx)
    ctype = case.get("case_type")
    culprit = case.get("victim") if ctype == "suicide" else case.get("killer")
    kc = case.get("key_clues") or []
    fc = case.get("false_clues") or []

    accus: Counter[str] = Counter()
    for c in kc + fc:
        if c.get("points_to"):
            accus[c["points_to"]] += 1
    to_culprit = sum(1 for c in kc if c.get("points_to") == culprit)
    rival = max((v for k, v in accus.items() if k != culprit), default=0)

    overlap = []
    for k in kc:
        for f in fc:
            a, b = _words(k.get("description", "") + " " + k.get("name", "")), _words(f.get("description", ""))
            if k.get("location") == f.get("location") and a and b and len(a & b) / min(len(a), len(b)) >= 0.3:
                overlap.append(f"{k.get('id')}~{f.get('id')}")

    prompts = [case.get("crime_scene_prompt", "")] + [k.get("image_prompt", "") for k in kc]
    risk = sorted({w for p in prompts for w in EXTRA_FILTER_WORDS if re.search(r"\b" + w, (p or "").lower())})
    deriv = [p for p in DERIVATIVE if re.search(p, (case.get("host_announcement") or "").lower())]

    n = solver(case, culprit)
    full = solver(case, culprit, need=0, culprit_only=False)
    at_scene = sum(1 for k in kc if k.get("points_to") == culprit and not k.get("requires_skill")
                   and k.get("location") == case.get("crime_location"))
    return {
        "logic_ok": not schema and not logic,
        "case_type": ctype,
        "solvable_min_actions": n,
        "p_enough_actions": round(p_at_least(n), 3),
        "full_evidence_actions": full,
        "p_full_evidence": round(p_at_least(full), 3),
        "proof_at_crime_scene": at_scene >= 2,
        "culprit_margin": to_culprit - rival,
        "culprit_share": round(to_culprit / len(kc), 2) if kc else 0.0,
        "skill_locked": sum(1 for k in kc if k.get("requires_skill")),
        "key_false_overlap": overlap,
        "filter_risk_words": risk,
        "derivative_phrases": deriv,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--context", default=str(Path(__file__).parent.parent / "narrative" / "game_context.json"))
    ap.add_argument("--json", help="write per-file results + aggregate here")
    a = ap.parse_args()
    ctx = json.loads(Path(a.context).read_text(encoding="utf-8"))

    rows = []
    for f in a.files:
        try:
            r = audit(parse_llm_json(Path(f).read_text(encoding="utf-8")), ctx)
        except (ValueError, json.JSONDecodeError, KeyError, TypeError) as e:
            r = {"error": f"unreadable: {str(e)[:80]}"}
        r["file"] = Path(f).name
        rows.append(r)
        print(json.dumps(r, ensure_ascii=False))

    ok = [r for r in rows if "error" not in r]
    agg = {"files": len(rows), "parsed": len(ok)}
    if ok:
        agg.update({
            "logic_pass_rate": sum(r["logic_ok"] for r in ok) / len(rows),
            "solvable_rate": sum(r["solvable_min_actions"] is not None for r in ok) / len(rows),
            "solvable_le5_rate": sum((r["solvable_min_actions"] or 99) <= 5 for r in ok) / len(rows),
            "mean_p_enough_actions": round(sum(r["p_enough_actions"] for r in ok) / len(rows), 3),
            "trivial_rate(<=1 action)": sum((r["solvable_min_actions"] or 99) <= 1 for r in ok) / len(rows),
            "proof_at_crime_scene_rate": sum(r["proof_at_crime_scene"] for r in ok) / len(rows),
            "mean_full_evidence_actions": round(sum(r["full_evidence_actions"] or 0 for r in ok) / max(1, len(ok)), 2),
            "mean_p_full_evidence": round(sum(r["p_full_evidence"] for r in ok) / len(rows), 3),
            "singles_out_culprit_rate": sum(r["culprit_margin"] > 0 for r in ok) / len(rows),
            "too_easy_rate": sum(r["culprit_share"] >= 0.8 for r in ok) / len(rows),
            "key_false_overlap_rate": sum(bool(r["key_false_overlap"]) for r in ok) / len(rows),
            "filter_risk_rate": sum(bool(r["filter_risk_words"]) for r in ok) / len(rows),
            "derivative_host_rate": sum(bool(r["derivative_phrases"]) for r in ok) / len(rows),
            "case_types": dict(Counter(r["case_type"] for r in ok)),
        })
    print("\n== aggregate ==")
    for k, v in agg.items():
        print(f"{k:26s} {v}")
    if a.json:
        Path(a.json).write_text(json.dumps({"aggregate": agg, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
