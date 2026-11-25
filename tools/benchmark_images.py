"""Benchmark live image generation via Pollinations (Option B): success rate + latency.

Free tier (observed 2026-11-23): 1 image every 45 s per IP -> the script waits
--interval seconds between requests. With a pollen key set in env POLLINATIONS_KEY
the limit is lifted; pass --interval 0.

Usage:
  python tools/benchmark_images.py --runs 5
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE = ("2D stylized anime visual novel evidence photo, bold black ink outlines, sharp cel shading "
         "with subtle halftone dot texture, high-contrast lighting. Close-up top-down view of ")
SUFFIX = ", dramatic spotlight from above, mysterious atmosphere. Square composition, no text, no labels, no watermark."


def load_prompts() -> list[str]:
    case = json.loads((ROOT / "narrative" / "sample_case.json").read_text(encoding="utf-8"))
    prompts = [c["image_prompt"] for c in case["key_clues"]]
    prompts.insert(0, case["crime_scene_prompt"])
    return prompts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--interval", type=float, default=46.0)
    ap.add_argument("--size", type=int, default=512)
    a = ap.parse_args()

    key = os.environ.get("POLLINATIONS_KEY")
    out = ROOT / "baselines" / f"{datetime.now():%Y%m%d-%H%M}-images"
    out.mkdir(parents=True, exist_ok=True)
    prompts = load_prompts()
    rows = []
    for i in range(a.runs):
        p = STYLE + prompts[i % len(prompts)] + SUFFIX
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(p) +
               f"?width={a.size}&height={a.size}&nologo=true&seed={1000 + i}")
        headers = {"User-Agent": "mystery-game-bench/0.1"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        t0 = time.perf_counter()
        row = {"run": i + 1, "ok": False, "status": None, "latency_s": None, "bytes": 0, "error": None}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as r:
                data = r.read()
                row["status"] = r.status
                ctype = r.headers.get("Content-Type", "")
                row["ok"] = ctype.startswith("image/") and len(data) > 5000
                row["bytes"] = len(data)
                if row["ok"]:
                    (out / f"img{i + 1:02d}.jpg").write_bytes(data)
                else:
                    row["error"] = data[:200].decode(errors="replace")
        except urllib.error.HTTPError as e:
            row["status"] = e.code
            row["error"] = e.read()[:200].decode(errors="replace")
        except (urllib.error.URLError, TimeoutError) as e:
            row["error"] = str(e)
        row["latency_s"] = round(time.perf_counter() - t0, 2)
        rows.append(row)
        print(f"run {i + 1}/{a.runs} ok={row['ok']} status={row['status']} {row['latency_s']}s {row['error'] or ''}"[:220], flush=True)
        if i < a.runs - 1 and a.interval > 0:
            time.sleep(max(0.0, a.interval - row["latency_s"]))

    lat = sorted(r["latency_s"] for r in rows if r["ok"])
    summary = {
        "runs": len(rows),
        "success_rate": sum(r["ok"] for r in rows) / len(rows),
        "latency_p50_s": statistics.median(lat) if lat else None,
        "latency_max_s": lat[-1] if lat else None,
        "interval_s": a.interval, "keyed": bool(key), "rows": rows,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    print(f"saved -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
