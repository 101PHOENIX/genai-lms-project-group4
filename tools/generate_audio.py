"""Generate the game's music loops and sound effects from audio/audio_cues.json.

Offline asset pipeline (Team 3). The brief lists music as a pre-generated static asset,
so nothing here runs during gameplay: generate N candidates per cue, listen, promote the
best one into unity/Assets/Audio/, and log the run like any other prompt iteration.
Every tool in the pipeline is free: no paid API, no billing account.

Providers (--provider):
  acestep  ACE-Step 1.5 (MIT) REST server on a free Colab GPU or a local GPU.
           Async task + polling. Env ACESTEP_URL (default http://127.0.0.1:8001),
           optional ACESTEP_API_KEY. Music only.
  stable-audio  Stable Audio 3 Small-SFX (Stability AI Community License) through its Python API.
           SFX only. Run with `uv run python` from the stable-audio-3 repo (Colab cells in
           tools/audio_studio.py); gated model: accept the licence on Hugging Face and log in.
  mock     Sine-tone WAVs, no network. Tests the pipeline and the Unity import.

SFX are one-shots: generate them with --provider stable-audio, or make them in the Stable Audio 3 UI /
take them from Freesound and bring them in with `promote --file`, which records source and licence.

Usage:
  python tools/generate_audio.py generate --provider mock
  python tools/generate_audio.py generate --provider acestep --only investigation trial
  python tools/generate_audio.py promote investigation --run baselines/20261126-1010-audio-acestep --take 2
  python tools/generate_audio.py promote dice_roll --file ~/dice.wav --source "Stable Audio 3 Small SFX" \
      --licence "Stability AI Community License"

Settings are read from the environment or a gitignored .env at the repo root.
Standard library only; the stable-audio provider imports its own environment (torch) lazily.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import zlib
from array import array
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "audio" / "audio_cues.json"
PROVENANCE = ROOT / "audio" / "provenance.json"
UNITY_AUDIO = ROOT / "unity" / "Assets" / "Audio"

TIMEOUT_S = 300
MAX_ATTEMPTS = 4
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
AUTH_STATUSES = frozenset({401, 403})
MIN_AUDIO_BYTES = 1000
UNITY_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".ogg", ".aif", ".aiff"})

# (min_s, max_s) accepted by each provider, per cue kind.
LIMITS = {
    ("acestep", "music"): (10.0, 600.0),
    ("stable-audio", "sfx"): (0.1, 120.0),
    ("mock", "music"): (0.1, 600.0),
    ("mock", "sfx"): (0.1, 30.0),
}

log = logging.getLogger("generate_audio")


class ProviderError(RuntimeError):
    """A provider call failed in a way that retrying will not fix."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NetworkError(ProviderError):
    """The provider could not be reached at all (DNS, refused, timeout) after retries."""


@dataclass(frozen=True)
class Cue:
    id: str
    kind: str  # "music" | "sfx"
    prompt: str
    duration_s: float
    loop: bool
    bpm: int | None = None
    key: str | None = None


# --------------------------------------------------------------------------- manifest

def load_cues(path: Path) -> tuple[dict, list[Cue]]:
    """Read the cue manifest.

    Args:
        path: Path to audio_cues.json.

    Returns:
        The raw manifest dict and its cues (music first, then sfx).

    Raises:
        ValueError: If the file is not valid JSON or a cue misses a required field.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: invalid JSON ({e})") from e
    cues = []
    for kind in ("music", "sfx"):
        for i, raw in enumerate(data.get(kind, [])):
            try:
                cues.append(Cue(
                    id=raw["id"], kind=kind, prompt=raw["prompt"],
                    duration_s=float(raw["duration_s"]), loop=bool(raw.get("loop", False)),
                    bpm=raw.get("bpm"), key=raw.get("key"),
                ))
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"{path}: {kind}[{i}] is missing or has a bad field ({e})") from e
    return data, cues


def validate_cues(cues: list[Cue], provider: str) -> list[str]:
    """Check cues against the manifest rules and the provider's duration limits.

    Args:
        cues: Cues selected for this run.
        provider: Provider name, a key prefix of LIMITS.

    Returns:
        Human-readable errors; empty if the cues are valid.
    """
    errors = []
    seen = set()
    for c in cues:
        if c.id in seen:
            errors.append(f"{c.id}: duplicate id")
        seen.add(c.id)
        if not c.prompt.strip():
            errors.append(f"{c.id}: empty prompt")
        if c.bpm is not None and not 30 <= c.bpm <= 300:
            errors.append(f"{c.id}: bpm {c.bpm} outside 30-300")
        limits = LIMITS.get((provider, c.kind))
        if limits and not limits[0] <= c.duration_s <= limits[1]:
            errors.append(f"{c.id}: {c.duration_s}s outside {provider} {c.kind} range {limits[0]}-{limits[1]}s")
    return errors


def build_prompt(manifest: dict, cue: Cue) -> str:
    """Compose the text sent to the provider: shared style + cue prompt + musical constraints.

    Args:
        manifest: Raw manifest, for `music_style` and `loop_rules`.
        cue: The cue to render.

    Returns:
        The final prompt. SFX prompts are sent as written.
    """
    if cue.kind == "sfx":
        return cue.prompt.strip()
    parts = [manifest.get("music_style", ""), cue.prompt]
    if cue.bpm:
        parts.append(f"{cue.bpm} BPM.")
    if cue.key:
        parts.append(f"Key of {cue.key}.")
    if cue.loop:
        parts.append(manifest.get("loop_rules", ""))
    return " ".join(p.strip() for p in parts if p and p.strip())


# --------------------------------------------------------------------------- http

def _backoff_seconds(attempt: int, retry_after: str | None) -> float:
    if retry_after and retry_after.strip().isdigit():
        return min(float(retry_after), 120.0)
    return min(10.0 * 2 ** (attempt - 1), 120.0)


def http_request(url: str, *, method: str = "GET", body: dict | None = None,
                 headers: dict | None = None, timeout: float = TIMEOUT_S,
                 opener: Callable = urllib.request.urlopen,
                 sleep: Callable[[float], None] = time.sleep) -> tuple[bytes, str]:
    """HTTP call with retry and exponential backoff on rate limits, 5xx and network errors.

    Args:
        url: Full URL.
        method: HTTP method.
        body: JSON body, or None.
        headers: Extra headers (auth). Never logged.
        timeout: Socket timeout per attempt, in seconds.
        opener: Injected for tests; defaults to urllib.request.urlopen.
        sleep: Injected for tests; defaults to time.sleep.

    Returns:
        Response body and its Content-Type.

    Raises:
        ProviderError: On a non-retryable status or after MAX_ATTEMPTS.
    """
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"User-Agent": "mystery-game-audio/0.1", **(headers or {})}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(1, MAX_ATTEMPTS + 1):
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with opener(req, timeout=timeout) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            if e.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS:
                raise ProviderError(f"HTTP {e.code} from {host}: {detail}", e.code) from e
            wait = _backoff_seconds(attempt, e.headers.get("Retry-After") if e.headers else None)
            log.warning("http_retry host=%s status=%d attempt=%d wait_s=%.0f", host, e.code, attempt, wait)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == MAX_ATTEMPTS:
                raise NetworkError(f"network error calling {host}: {e}") from e
            wait = _backoff_seconds(attempt, None)
            log.warning("http_retry host=%s error=%r attempt=%d wait_s=%.0f", host, e, attempt, wait)
        sleep(wait)
    raise AssertionError("unreachable")


def _expect_audio(data: bytes, content_type: str, source: str) -> bytes:
    if content_type.startswith(("application/json", "text/")) or len(data) < MIN_AUDIO_BYTES:
        raise ProviderError(f"{source} returned no audio ({content_type or 'no type'}, "
                            f"{len(data)} bytes): {data[:200].decode(errors='replace')}")
    return data


# --------------------------------------------------------------------------- providers

class AceStepProvider:
    """ACE-Step 1.5 REST server: submit a task, poll until done, download the file."""

    name = "acestep"
    kinds = frozenset({"music"})
    extension = "mp3"
    licence = "MIT (ACE-Step 1.5)"

    def __init__(self, base_url: str, api_key: str | None = None, poll_s: float = 3.0,
                 task_timeout_s: float = 900.0, http: Callable = http_request,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._poll_s = poll_s
        self._task_timeout_s = task_timeout_s
        self._http = http
        self._sleep = sleep
        self._clock = clock

    def settings(self) -> dict:
        return {"base_url": self._base, "lyrics": "[Instrumental]", "audio_format": "mp3"}

    def check(self, timeout: float = 5.0, opener: Callable = urllib.request.urlopen) -> str | None:
        """One quick GET /health, no retries.

        Returns:
            None when the server answers ok, else a human-readable reason.
        """
        try:
            with opener(urllib.request.Request(self._base + "/health", headers=self._headers), timeout=timeout) as r:
                status = json.loads(r.read()).get("data", {}).get("status")
        except urllib.error.HTTPError as e:
            return f"ACE-Step at {self._base} answered HTTP {e.code} on /health"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            return f"no ACE-Step server at {self._base} ({getattr(e, 'reason', e)})"
        except (json.JSONDecodeError, AttributeError):
            return f"{self._base}/health did not return ACE-Step's JSON"
        return None if status == "ok" else f"ACE-Step at {self._base} is not ready (status={status!r})"

    def _call(self, path: str, body: dict):
        raw, _ = self._http(self._base + path, method="POST", body=body, headers=self._headers)
        try:
            env = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"ACE-Step {path}: non-JSON response {raw[:200]!r}") from e
        if env.get("code") != 200 or env.get("error"):
            raise ProviderError(f"ACE-Step {path}: code={env.get('code')} error={env.get('error')}")
        return env["data"]

    last_seed = None  # seed the server reported for the last take, if any

    def generate(self, cue: Cue, prompt: str) -> bytes:
        """Render one music cue.

        Args:
            cue: A music cue; bpm and key are passed as native parameters.
            prompt: Output of build_prompt.

        Returns:
            MP3 bytes.

        Raises:
            ProviderError: If the task fails, times out or returns no file.
        """
        body = {"prompt": prompt, "lyrics": "[Instrumental]", "audio_duration": cue.duration_s,
                "audio_format": "mp3"}
        if cue.bpm:
            body["bpm"] = cue.bpm
        if cue.key:
            body["key_scale"] = cue.key
        task_id = self._call("/release_task", body)["task_id"]
        deadline = self._clock() + self._task_timeout_s
        while True:
            item = self._call("/query_result", {"task_id_list": [task_id]})[0]
            if item["status"] == 1:
                break
            if item["status"] == 2:
                raise ProviderError(f"ACE-Step task {task_id} failed: {str(item.get('result'))[:200]}")
            if self._clock() > deadline:
                raise ProviderError(f"ACE-Step task {task_id} still running after {self._task_timeout_s:.0f}s")
            self._sleep(self._poll_s)
        outputs = item["result"]
        if isinstance(outputs, str):
            outputs = json.loads(outputs)
        if not outputs or not outputs[0].get("file"):
            raise ProviderError(f"ACE-Step task {task_id} succeeded without a file")
        self.last_seed = outputs[0].get("seed_value", outputs[0].get("seed"))
        data, ctype = self._http(self._base + outputs[0]["file"], headers=self._headers)
        return _expect_audio(data, ctype, "ACE-Step")


class MockProvider:
    """Deterministic sine tones so the pipeline and Unity import can be tested offline."""

    name = "mock"
    kinds = frozenset({"music", "sfx"})
    extension = "wav"
    licence = "test tone, replace before release"
    sample_rate = 22050

    def settings(self) -> dict:
        return {"sample_rate": self.sample_rate}

    def generate(self, cue: Cue, prompt: str) -> bytes:
        freq = 220 + zlib.crc32(cue.id.encode()) % 440
        self.last_seed = zlib.crc32(cue.id.encode())
        n = int(cue.duration_s * self.sample_rate)
        step = 2 * math.pi * freq / self.sample_rate
        samples = array("h", (int(8000 * math.sin(step * i)) for i in range(n)))
        buf = BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(samples.tobytes())
        return buf.getvalue()


class StableAudioProvider:
    """Stable Audio 3 Small-SFX through its Python API (github.com/Stability-AI/stable-audio-3).

    Needs that repo's environment (torch, stable_audio_3), so run this script with
    `uv run python .../generate_audio.py` from the stable-audio-3 folder, e.g. on Colab (Audio Studio
    prints the cells). The model is gated on Hugging Face: accept its licence and log in (HF_TOKEN).
    Env SA3_MODEL (default small-sfx), SA3_STEPS (8), SA3_CFG (1.0).
    """

    name = "stable-audio"
    kinds = frozenset({"sfx"})
    extension = "wav"
    licence = "Stability AI Community License (Stable Audio 3 Small-SFX)"
    max_seed = 99999  # same range the library draws from for seed=-1

    def __init__(self, model_name: str = "small-sfx", steps: int = 8, cfg_scale: float = 1.0,
                 model=None, rng: Callable[[int, int], int] | None = None):
        self._model_name, self._steps, self._cfg = model_name, steps, cfg_scale
        self._model = model
        import random
        self._rng = rng or random.randint
        self.last_seed = None

    def settings(self) -> dict:
        return {"model": self._model_name, "steps": self._steps, "cfg_scale": self._cfg,
                "sample_rate": self._model.model.sample_rate if self._model is not None else None}

    def check(self) -> str | None:
        if self._model is not None:
            return None
        import importlib.util
        if importlib.util.find_spec("stable_audio_3") is None:
            return ("stable_audio_3 is not importable: run this script with `uv run python` from the "
                    "stable-audio-3 folder (see the Colab cells in Audio Studio)")
        return None

    def _load(self):
        if self._model is None:
            try:
                from stable_audio_3 import StableAudioModel
                log.info("loading model=%s (first run downloads the weights)", self._model_name)
                self._model = StableAudioModel.from_pretrained(self._model_name)
            except Exception as e:  # gated repo, no token, no network, bad model name...
                text = str(e)
                status = 401 if any(s in text for s in ("401", "403", "gated", "Gated", "token", "authorized")) else None
                raise ProviderError(f"cannot load Stable Audio 3 '{self._model_name}': {text[:300]}", status) from e
        return self._model

    def generate(self, cue: Cue, prompt: str) -> bytes:
        """Render one SFX take as a 16-bit WAV of exactly the cue's duration.

        Raises:
            ProviderError: If the model cannot be loaded or generation fails.
        """
        model = self._load()
        seed = self._rng(0, self.max_seed)
        try:
            audio = model.generate(prompt=prompt, duration=cue.duration_s, seed=seed,
                                   steps=self._steps, cfg_scale=self._cfg)
        except Exception as e:  # CUDA OOM, bad duration...
            raise ProviderError(f"Stable Audio 3 generation failed: {str(e)[:300]}") from e
        self.last_seed = seed
        import numpy as np
        take = audio[0]
        take = take.detach().float().cpu().numpy() if hasattr(take, "detach") else np.asarray(take, dtype="float32")
        sr = int(model.model.sample_rate)
        take = take[:, : int(round(cue.duration_s * sr))]  # (channels, samples), trimmed to the request
        pcm = (np.clip(take, -1.0, 1.0) * 32767).astype("<i2").T.copy()
        buf = BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(pcm.shape[1])
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()


def make_provider(name: str):
    """Build a provider from its name and the environment.

    Args:
        name: "acestep", "stable-audio" or "mock".

    Returns:
        A provider instance.

    Raises:
        ValueError: If the name is unknown.
    """
    if name == "acestep":
        return AceStepProvider(os.environ.get("ACESTEP_URL", "http://127.0.0.1:8001"),
                               os.environ.get("ACESTEP_API_KEY"))
    if name == "stable-audio":
        return StableAudioProvider(os.environ.get("SA3_MODEL", "small-sfx"), int(os.environ.get("SA3_STEPS", "8")),
                                   float(os.environ.get("SA3_CFG", "1.0")))
    if name == "mock":
        return MockProvider()
    raise ValueError(f"unknown provider {name!r}")


# --------------------------------------------------------------------------- commands

def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding variables already set.

    Args:
        path: The .env file; ignored if missing.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def summarize(rows: list[dict]) -> dict:
    lat = sorted(r["latency_s"] for r in rows if r["ok"])
    return {
        "runs": len(rows),
        "success_rate": round(sum(r["ok"] for r in rows) / len(rows), 3) if rows else 0.0,
        "latency_p50_s": statistics.median(lat) if lat else None,
        "latency_max_s": lat[-1] if lat else None,
        "generated_audio_s": round(sum(r["requested_s"] for r in rows if r["ok"]), 1),
        "ok_per_cue": {c: sum(r["ok"] for r in rows if r["cue"] == c) for c in dict.fromkeys(r["cue"] for r in rows)},
    }


def run_generate(provider, manifest: dict, cues: list[Cue], candidates: int, out_dir: Path) -> dict:
    """Generate `candidates` takes per cue and write them next to a summary.json.

    Args:
        provider: A provider instance.
        manifest: Raw manifest (for prompts and version).
        cues: Validated cues supported by the provider.
        candidates: Takes per cue.
        out_dir: Run folder under baselines/.

    Returns:
        The summary dict that was written to out_dir/summary.json.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, prompts = [], {}
    aborted = None
    for cue in cues:
        prompt = prompts[cue.id] = build_prompt(manifest, cue)
        for i in range(1, candidates + 1):
            row = {"cue": cue.id, "kind": cue.kind, "candidate": i, "ok": False, "latency_s": None,
                   "bytes": 0, "file": None, "requested_s": cue.duration_s, "seed": None, "error": None}
            t0 = time.perf_counter()
            try:
                audio = provider.generate(cue, prompt)
                row["file"] = f"{cue.id}_c{i:02d}.{provider.extension}"
                (out_dir / row["file"]).write_bytes(audio)
                row.update(ok=True, bytes=len(audio), seed=getattr(provider, "last_seed", None))
            except ProviderError as e:
                row["error"] = str(e)
                if e.status in AUTH_STATUSES:
                    aborted = f"auth error {e.status}: check the credentials (ACESTEP_API_KEY / Hugging Face login)"
                elif isinstance(e, NetworkError) and not any(r["ok"] for r in rows):
                    aborted = "provider unreachable before any success: is the server/URL up?"
            row["latency_s"] = round(time.perf_counter() - t0, 2)
            rows.append(row)
            log.info("generated cue=%s candidate=%d ok=%s latency_s=%.1f bytes=%d error=%s",
                     cue.id, i, row["ok"], row["latency_s"], row["bytes"], row["error"])
            if aborted:
                break
        if aborted:
            log.error("run_aborted reason=%r", aborted)
            break
    summary = {
        "provider": provider.name, "licence": provider.licence, "settings": provider.settings(),
        "manifest_version": manifest.get("version"), "candidates_per_cue": candidates,
        "aborted": aborted, **summarize(rows), "prompts": prompts, "rows": rows,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def cmd_generate(args: argparse.Namespace) -> int:
    manifest, cues = load_cues(args.manifest)
    if args.only:
        known = {c.id for c in cues}
        unknown = sorted(set(args.only) - known)
        if unknown:
            log.error("unknown_cues ids=%s", unknown)
            return 2
        cues = [c for c in cues if c.id in args.only]
    provider = make_provider(args.provider)
    skipped = [c.id for c in cues if c.kind not in provider.kinds]
    if skipped:
        log.warning("skipped_unsupported provider=%s cues=%s", provider.name, skipped)
    cues = [c for c in cues if c.kind in provider.kinds]
    errors = validate_cues(cues, provider.name)
    for e in errors:
        log.error("invalid_cue %s", e)
    if errors or not cues:
        return 2
    if hasattr(provider, "check"):
        problem = provider.check()
        if problem:
            log.error("provider_unavailable %s. Start it (`uv run acestep-api` in ACE-Step-1.5) or set ACESTEP_URL; "
                      "no run folder was created", problem)
            return 2
    out_dir = args.out or ROOT / "baselines" / f"{datetime.now():%Y%m%d-%H%M}-audio-{provider.name}"
    summary = run_generate(provider, manifest, cues, args.candidates, out_dir)
    log.info("run_done out=%s success_rate=%.2f latency_p50_s=%s generated_audio_s=%s",
             out_dir, summary["success_rate"], summary["latency_p50_s"], summary["generated_audio_s"])
    return 0 if summary["success_rate"] == 1.0 else 1


def _from_run(run_dir: Path, cue_id: str, take: int) -> tuple[Path, dict]:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    row = next((r for r in summary["rows"] if r["cue"] == cue_id and r["candidate"] == take and r["ok"]), None)
    if row is None:
        raise ValueError(f"no successful take {take} for '{cue_id}' in {run_dir}")
    record = {
        "provider": summary["provider"], "licence": summary.get("licence"), "settings": summary["settings"],
        "run": run_dir.name, "take": take, "prompt": summary["prompts"].get(cue_id),
        "seed": row.get("seed"), "latency_s": row.get("latency_s"),
        "manifest_version": summary.get("manifest_version"),
    }
    # imported takes (Stable Audio 3 UI, Freesound) and edited takes (Audio Studio trim)
    for key in ("source", "original_file", "licence", "derived_from", "edit", "trim_s"):
        if row.get(key):
            record[key] = row[key]
    return run_dir / row["file"], record


def _from_file(path: Path, source: str | None, licence: str | None) -> tuple[Path, dict]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if not source or not licence:
        raise ValueError("--file needs --source and --licence: provenance.json is the attribution record")
    return path, {"provider": "external", "source": source, "licence": licence, "original_file": path.name}


def cmd_promote(args: argparse.Namespace) -> int:
    """Copy one take, or an external file, into unity/Assets/Audio and record its provenance.

    Args:
        args: Parsed CLI arguments (cue plus --run/--take or --file/--source/--licence).

    Returns:
        0 on success, 2 on a usage error.
    """
    _, cues = load_cues(args.manifest)
    cue = next((c for c in cues if c.id == args.cue), None)
    if cue is None:
        log.error("unknown_cue id=%s", args.cue)
        return 2
    try:
        if args.file:
            src, record = _from_file(Path(args.file).expanduser(), args.source, args.licence)
        elif args.take is None:
            raise ValueError("--run needs --take")
        else:
            src, record = _from_run(Path(args.run), cue.id, args.take)
    except (ValueError, FileNotFoundError) as e:
        log.error("promote_failed cue=%s error=%s", cue.id, e)
        return 2
    try:
        promote(cue, src, record, args.unity_audio, args.provenance)
    except ValueError as e:
        log.error("promote_failed cue=%s error=%s", cue.id, e)
        return 2
    return 0


def promote(cue: Cue, src: Path, record: dict, unity_audio: Path, provenance: Path) -> Path:
    """Copy an audio file into <unity_audio>/Music|SFX/<cue id>.<ext> and record its provenance.

    Shared by the CLI and tools/audio_studio.py.

    Args:
        cue: The cue the file is for (its kind picks Music/ or SFX/).
        src: Source audio file.
        record: Provenance fields (provider, licence, run, take, prompt...).
        unity_audio: Unity audio root holding Music/ and SFX/.
        provenance: provenance.json path; created if missing.

    Returns:
        The destination path.

    Raises:
        ValueError: If Unity cannot import the file format.
    """
    if src.suffix.lower() not in UNITY_AUDIO_SUFFIXES:
        raise ValueError(f"unsupported format {src.name} (Unity imports {sorted(UNITY_AUDIO_SUFFIXES)})")
    dest_dir = unity_audio / ("Music" if cue.kind == "music" else "SFX")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{cue.id}{src.suffix.lower()}"
    for stale in dest_dir.glob(f"{cue.id}.*"):
        if stale.suffix != ".meta" and stale != dest:
            log.warning("replacing_other_format old=%s new=%s (re-assign the clip in the Inspector)", stale.name, dest.name)
            stale.unlink()
    shutil.copyfile(src, dest)
    prov = json.loads(provenance.read_text(encoding="utf-8")) if provenance.is_file() else {}
    prov[cue.id] = {
        "file": dest.relative_to(ROOT).as_posix() if dest.is_relative_to(ROOT) else str(dest),
        **record, "promoted_at": datetime.now().isoformat(timespec="seconds"),
    }
    provenance.parent.mkdir(parents=True, exist_ok=True)
    provenance.write_text(json.dumps(prov, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("promoted cue=%s dest=%s licence=%r", cue.id, dest, record.get("licence"))
    return dest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="generate candidates into baselines/")
    g.add_argument("--provider", choices=["acestep", "stable-audio", "mock"], default="mock")
    g.add_argument("--only", nargs="+", metavar="CUE", help="cue ids to render (default: all)")
    g.add_argument("--candidates", type=int, default=3)
    g.add_argument("--manifest", type=Path, default=MANIFEST)
    g.add_argument("--out", type=Path, help="run folder (default baselines/<date>-audio-<provider>)")
    g.set_defaults(func=cmd_generate)
    p = sub.add_parser("promote", help="copy a take or an external file into unity/Assets/Audio/")
    p.add_argument("cue")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--run", help="run folder under baselines/")
    src.add_argument("--file", help="external audio file (Stable Audio 3 UI, Freesound...)")
    p.add_argument("--take", type=int, help="take number in --run")
    p.add_argument("--source", help="with --file: tool or site it came from")
    p.add_argument("--licence", help="with --file: licence, e.g. 'CC0' or 'Stability AI Community License'")
    p.add_argument("--manifest", type=Path, default=MANIFEST)
    p.add_argument("--unity-audio", type=Path, default=UNITY_AUDIO)
    p.add_argument("--provenance", type=Path, default=PROVENANCE)
    p.set_defaults(func=cmd_promote)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    load_dotenv(ROOT / ".env")
    args = parse_args(argv)
    try:
        return args.func(args)
    except (ProviderError, ValueError, FileNotFoundError) as e:
        log.error("fatal error=%s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
