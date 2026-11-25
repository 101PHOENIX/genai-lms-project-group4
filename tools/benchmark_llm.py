"""Benchmark case-file generation: validity, logic pass-rate and latency.

Providers (pick with --provider):
  pollinations  free, no key (default baseline)        POST https://text.pollinations.ai/openai
  gemini        needs env GEMINI_API_KEY (Google AI Studio)
  groq          needs env GROQ_API_KEY

Usage:
  python tools/benchmark_llm.py --provider pollinations --runs 10
  python tools/benchmark_llm.py --provider gemini --runs 20 --model gemini-2.5-flash

Writes raw outputs to baselines/<label>/ and a summary JSON; prints the KPI table.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_case import parse_llm_json, validate  # noqa: E402

TIMEOUT = 120


def _post(url: str, body: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "mystery-game-bench/0.1", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def call(provider: str, model: str | None, system: str, user: str, seed: int = 0) -> str:
    """One completion. 402/429 (rate limit) -> back off and retry up to 4 times."""
    for attempt in range(5):
        try:
            return _call_once(provider, model, system, user, seed)
        except urllib.error.HTTPError as e:
            if e.code not in (402, 429, 503) or attempt == 4:
                raise
            wait = 15 * (attempt + 1)
            print(f"   rate-limited ({e.code}), waiting {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _call_once(provider: str, model: str | None, system: str, user: str, seed: int) -> str:
    if provider == "pollinations":
        body = {"model": model or "openai", "seed": seed, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
        return _post("https://text.pollinations.ai/openai", body)["choices"][0]["message"]["content"]
    if provider == "groq":
        key = os.environ["GROQ_API_KEY"]
        body = {"model": model or "llama-3.3-70b-versatile", "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}, "temperature": 0.9}
        return _post("https://api.groq.com/openai/v1/chat/completions", body,
                     {"Authorization": f"Bearer {key}"})["choices"][0]["message"]["content"]
    if provider == "gemini":
        key = os.environ["GEMINI_API_KEY"]
        m = model or "gemini-2.5-flash"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        return _post(url, body, {"x-goog-api-key": key})["candidates"][0]["content"]["parts"][0]["text"]
    raise ValueError(provider)


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = max(0, min(len(xs) - 1, round(p / 100 * (len(xs) - 1))))
    return xs[k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="pollinations", choices=["pollinations", "gemini", "groq"])
    ap.add_argument("--model")
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--prompt", default=str(ROOT / "narrative" / "master_system_prompt.md"))
    ap.add_argument("--context", default=str(ROOT / "narrative" / "game_context.json"))
    ap.add_argument("--retry", action="store_true", help="on failure, send errors back once (measures 'valid after retry')")
    ap.add_argument("--label")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between calls (free tiers rate-limit)")
    a = ap.parse_args()

    system = Path(a.prompt).read_text(encoding="utf-8")
    ctx = json.loads(Path(a.context).read_text(encoding="utf-8"))
    state = json.dumps({k: v for k, v in ctx.items() if not k.startswith("_")}, ensure_ascii=False)
    base_seed = random.randint(1, 10**9)

    label = a.label or f"{datetime.now():%Y%m%d-%H%M}-{a.provider}"
    out = ROOT / "baselines" / label
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for i in range(a.runs):
        if i and a.interval:
            time.sleep(a.interval)
        seed = base_seed + i
        # The seed in the text defeats response caching and makes each playthrough different.
        user = f"Playthrough seed: {seed}\nGenerate the hidden Case file for this game state:\n{state}"
        row = {"run": i + 1, "json_ok": False, "schema_ok": False, "logic_ok": False,
               "retry_ok": None, "latency_s": None, "errors": [], "case_type": None}
        t0 = time.perf_counter()
        try:
            text = call(a.provider, a.model, system, user, seed)
            row["latency_s"] = round(time.perf_counter() - t0, 2)
            (out / f"run{i + 1:02d}.txt").write_text(text, encoding="utf-8")
            case = parse_llm_json(text)
            row["json_ok"] = True
            row["case_type"] = case.get("case_type")
            schema, logic = validate(case, ctx)
            row["schema_ok"] = not schema
            row["logic_ok"] = not schema and not logic
            row["errors"] = schema + logic
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, RuntimeError) as e:
            row["latency_s"] = round(time.perf_counter() - t0, 2)
            row["errors"] = [f"request failed: {e}"]
            text = None
        except (ValueError, json.JSONDecodeError) as e:
            row["errors"] = [f"invalid JSON: {e}"]

        if a.retry and not row["logic_ok"] and text is not None:
            fix = (user + "\n\nYour previous answer was:\n" + text +
                   "\n\nIt has these problems:\n- " + "\n- ".join(row["errors"]) +
                   "\nReturn the corrected full JSON object only.")
            try:
                case2 = parse_llm_json(call(a.provider, a.model, system, fix, seed))
                s2, l2 = validate(case2, ctx)
                row["retry_ok"] = not s2 and not l2
            except Exception as e:  # noqa: BLE001
                row["retry_ok"] = False
                row["errors"].append(f"retry failed: {e}")

        rows.append(row)
        status = "OK " if row["logic_ok"] else ("JSON" if row["json_ok"] else "FAIL")
        print(f"run {i + 1:2d}/{a.runs}  {status}  {row['latency_s']}s  {row['errors'][:2]}", flush=True)

    n = len(rows)
    lat = [r["latency_s"] for r in rows if r["json_ok"] and r["latency_s"] is not None]
    summary = {
        "label": label, "provider": a.provider, "model": a.model, "runs": n,
        "json_valid_rate": sum(r["json_ok"] for r in rows) / n,
        "schema_valid_rate": sum(r["schema_ok"] for r in rows) / n,
        "logic_pass_rate": sum(r["logic_ok"] for r in rows) / n,
        "valid_after_retry_rate": (sum(bool(r["logic_ok"] or r["retry_ok"]) for r in rows) / n) if a.retry else None,
        "latency_p50_s": statistics.median(lat) if lat else None,
        "latency_p95_s": pct(lat, 95) if lat else None,
        "error_counts": {},
        "rows": rows,
    }
    for r in rows:
        for e in r["errors"]:
            key = e.split(":")[0].split("'")[0].strip()[:60]
            summary["error_counts"][key] = summary["error_counts"].get(key, 0) + 1
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n== KPI summary ==")
    for k in ("json_valid_rate", "schema_valid_rate", "logic_pass_rate", "valid_after_retry_rate",
              "latency_p50_s", "latency_p95_s"):
        print(f"{k:24s} {summary[k]}")
    print("top errors:", sorted(summary["error_counts"].items(), key=lambda kv: -kv[1])[:8])
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
