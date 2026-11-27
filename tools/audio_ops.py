"""Non-UI operations behind tools/audio_studio.py.

Manifest editing, run discovery and import, review decisions, promotion into Unity and the
generated sections of ITERATION_LOG.md and docs/AUDIO.md. Everything here is plain functions on
paths so it can be unit-tested without Streamlit. Generation and promotion reuse
tools/generate_audio.py, so the CLI and the Studio write the same files.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_audio as ga  # noqa: E402

ROOT = ga.ROOT
MANIFEST = ga.MANIFEST
PROVENANCE = ga.PROVENANCE
UNITY_AUDIO = ga.UNITY_AUDIO
BASELINES = ROOT / "baselines"
REVIEW = ROOT / "audio" / "review.json"
ITERATION_LOG = ROOT / "ITERATION_LOG.md"
AUDIO_DOC = ROOT / "docs" / "AUDIO.md"
MUSIC_CUES_CS = ROOT / "unity" / "Assets" / "Scripts" / "Core" / "MusicCues.cs"
SFX_PLAYER_CS = ROOT / "unity" / "Assets" / "Scripts" / "Audio" / "SfxPlayer.cs"

REJECT_REASONS = ["Vocals", "Random notes", "Style mismatch", "Bad loop", "Odd volume"]
GENERATORS = ["acestep", "mock"]
IMPORTERS = {
    "stable-audio": {"source": "Stable Audio 3 Small SFX", "licence": "Stability AI Community License"},
    "freesound": {"source": "Freesound: <author>, <sound id>", "licence": "CC0"},
}
ID_RE = re.compile(r"^[a-z](?:[a-z_]*[a-z])?$")  # same alphabet as the C# id tests ([a-z_]+)
IMPORT_SUFFIXES = ga.UNITY_AUDIO_SUFFIXES | {".flac"}
RUN_DATE_RE = re.compile(r"^(\d{8})-(\d{4})")


# --------------------------------------------------------------------------- json helpers

def read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    """Repo-relative POSIX path when inside the repo, else absolute."""
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- manifest

def load_manifest(path: Path = MANIFEST) -> dict:
    """Raw manifest; also checks it parses as cues."""
    ga.load_cues(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _one_line(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(", ", ": "))


def dump_manifest(data: dict) -> str:
    """Serialize the manifest in the hand-written style of audio/audio_cues.json.

    Music cues span three lines (id, prompt, the remaining fields); SFX take one line each.
    """
    out = ["{"]
    items = list(data.items())
    for i, (key, value) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        k = json.dumps(key)
        if key == "music" and isinstance(value, list):
            blocks = []
            for cue in value:
                rest = {f: v for f, v in cue.items() if f not in ("id", "prompt")}
                lines = [f'      "id": {json.dumps(cue["id"], ensure_ascii=False)}']
                if "prompt" in cue:
                    lines.append(f'      "prompt": {json.dumps(cue["prompt"], ensure_ascii=False)}')
                if rest:
                    lines.append("      " + _one_line(rest)[1:-1])
                blocks.append("    {\n" + ",\n".join(lines) + "\n    }")
            out.append(f"  {k}: [\n" + ",\n".join(blocks) + f"\n  ]{comma}")
        elif key == "sfx" and isinstance(value, list):
            rows = ",\n".join("    " + _one_line(c) for c in value)
            out.append(f"  {k}: [\n{rows}\n  ]{comma}")
        else:
            out.append(f"  {k}: {json.dumps(value, ensure_ascii=False)}{comma}")
    out.append("}")
    return "\n".join(out) + "\n"


def _clean_number(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 3)


def normalize_cue(kind: str, entry: dict) -> dict:
    """Build a manifest entry in the canonical field order, dropping empty optional fields."""
    out = {"id": str(entry["id"]).strip(), "prompt": str(entry.get("prompt", "")).strip(),
           "duration_s": _clean_number(entry["duration_s"])}
    if kind == "music":
        bpm = entry.get("bpm")
        if bpm not in (None, "", 0) and bpm == bpm:  # bpm == bpm filters NaN
            out["bpm"] = int(bpm)
        key = entry.get("key")
        if isinstance(key, str) and key.strip():
            out["key"] = key.strip()
    out["loop"] = bool(entry.get("loop", False))
    return out


def validate_manifest(data: dict) -> list[str]:
    """Errors for a manifest dict: structure, ids, durations, bpm (mock limits) and duplicates."""
    errors = []
    cues = []
    for kind in ("music", "sfx"):
        for i, raw in enumerate(data.get(kind, [])):
            cid = str(raw.get("id", ""))
            if not ID_RE.match(cid):
                errors.append(f"{kind}[{i}] id {cid!r}: use lowercase letters and underscores (e.g. door_slam)")
            try:
                cues.append(ga.Cue(id=cid, kind=kind, prompt=str(raw.get("prompt", "")),
                                   duration_s=float(raw["duration_s"]), loop=bool(raw.get("loop", False)),
                                   bpm=raw.get("bpm"), key=raw.get("key")))
            except (KeyError, TypeError, ValueError) as e:
                errors.append(f"{kind}[{i}] {cid}: bad field ({e})")
    errors += ga.validate_cues(cues, "mock")
    return errors


def save_manifest(data: dict, path: Path = MANIFEST) -> list[str]:
    """Validate and write the manifest. Returns errors; nothing is written if there are any."""
    errors = validate_manifest(data)
    if not errors:
        path.write_text(dump_manifest(data), encoding="utf-8")
    return errors


def all_cues(data: dict) -> dict[str, dict]:
    """Cue id -> manifest entry plus its kind."""
    return {c["id"]: {**c, "kind": kind} for kind in ("music", "sfx") for c in data.get(kind, [])}


def add_cue(data: dict, kind: str, entry: dict) -> tuple[dict, list[str]]:
    """Return a copy of the manifest with a new cue appended, and validation errors."""
    entry = normalize_cue(kind, entry)
    if entry["id"] in all_cues(data):
        return data, [f"{entry['id']}: id already exists"]
    new = json.loads(json.dumps(data))
    new.setdefault(kind, []).append(entry)
    return new, validate_manifest(new)


def set_prompt(data: dict, cue_id: str, prompt: str) -> dict:
    new = json.loads(json.dumps(data))
    for kind in ("music", "sfx"):
        for c in new.get(kind, []):
            if c["id"] == cue_id:
                c["prompt"] = prompt.strip()
    return new


def pascal(cue_id: str) -> str:
    return "".join(p.capitalize() for p in cue_id.split("_"))


def add_csharp_constant(kind: str, cue_id: str, music_cs: Path = MUSIC_CUES_CS, sfx_cs: Path = SFX_PLAYER_CS) -> str:
    """Insert `public const string X = "id";` after the last string constant of MusicCues / SfxPlayer.Ids.

    Returns:
        A message describing what happened.
    """
    path = music_cs if kind == "music" else sfx_cs
    src = path.read_text(encoding="utf-8")
    if f'"{cue_id}"' in src:
        return f"{path.name}: '{cue_id}' already declared"
    matches = list(re.finditer(r'^([ \t]*)public const string \w+ = "[a-z_]+";[^\n]*\n', src, re.M))
    if not matches:
        raise ValueError(f"{path.name}: no string constants found to insert after")
    last = matches[-1]
    line = f'{last.group(1)}public const string {pascal(cue_id)} = "{cue_id}";\n'
    path.write_text(src[:last.end()] + line + src[last.end():], encoding="utf-8")
    note = " Wire it in MusicCues.ForState / Loops if it maps to a game state." if kind == "music" else ""
    return f"{path.name}: added {pascal(cue_id)} = \"{cue_id}\".{note}"


# --------------------------------------------------------------------------- runs

def is_audio_run(run_dir: Path) -> bool:
    try:
        s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    rows = s.get("rows")
    return isinstance(rows, list) and "prompts" in s and all(isinstance(r, dict) and "cue" in r for r in rows)


def has_takes(run_dir: Path) -> bool:
    return any(r.get("ok") for r in load_summary(run_dir)["rows"])


def list_runs(baselines: Path = BASELINES) -> list[Path]:
    """Audio run folders with at least one successful take under baselines/, newest first."""
    if not baselines.is_dir():
        return []
    runs = [p for p in baselines.iterdir() if p.is_dir() and is_audio_run(p) and has_takes(p)]
    return sorted(runs, key=lambda p: (p.name[:13] if RUN_DATE_RE.match(p.name) else "", p.stat().st_mtime), reverse=True)


def load_summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def run_date(run_name: str) -> str | None:
    """'20261125-1841-audio-mock' -> '2026-11-25T18:41'."""
    m = RUN_DATE_RE.match(run_name)
    if not m:
        return None
    try:  # a hand-named folder may hold an impossible date (e.g. month 20)
        return datetime.strptime("".join(m.groups()), "%Y%m%d%H%M").strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def unique_dir(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while path.with_name(f"{path.name}-{i}").exists():
        i += 1
    return path.with_name(f"{path.name}-{i}")


def default_run_dir(provider: str, baselines: Path = BASELINES) -> Path:
    return unique_dir(baselines / f"{datetime.now():%Y%m%d-%H%M}-audio-{provider}")


def import_run_zip(zip_path: Path, baselines: Path = BASELINES) -> Path:
    """Unpack a zipped run (e.g. downloaded from Drive after Colab) into baselines/.

    The archive may hold the run at its root or inside one folder; the folder with summary.json wins.

    Raises:
        ValueError: If the archive is unsafe or holds no audio run.
    """
    tmp = unique_dir(baselines / "_import_tmp")
    try:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                target = (tmp / name).resolve()
                if not target.is_relative_to(tmp.resolve()):
                    raise ValueError(f"unsafe path in archive: {name}")
            z.extractall(tmp)
        found = [p.parent for p in tmp.rglob("summary.json") if is_audio_run(p.parent)]
        if not found:
            raise ValueError("no audio run (summary.json with rows and prompts) in the archive")
        src = min(found, key=lambda p: len(p.parts))
        name = src.name if src != tmp else Path(zip_path).stem
        dest = unique_dir(baselines / name)
        shutil.move(str(src), str(dest))
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def import_run_folder(folder: Path, baselines: Path = BASELINES) -> Path:
    """Copy a run folder (e.g. a synced Google Drive folder) into baselines/."""
    folder = Path(folder).expanduser()
    if not is_audio_run(folder):
        raise ValueError(f"{folder} has no audio summary.json")
    if folder.resolve().parent == baselines.resolve():
        return folder
    dest = unique_dir(baselines / folder.name)
    shutil.copytree(folder, dest)
    return dest


def import_external_takes(cue: dict, files: list[tuple[str, bytes]], provider: str, source: str, licence: str,
                          manifest: dict, baselines: Path = BASELINES) -> Path:
    """Turn files from the Stable Audio 3 UI or Freesound into a run like generate_audio.py writes.

    Args:
        cue: Manifest entry plus "kind" (from all_cues).
        files: (original name, bytes) pairs.
        provider: "stable-audio" or "freesound".
        source: Tool or "Freesound: author, id" (goes to provenance).
        licence: Licence of these files.
        manifest: Raw manifest (for the prompt and version).

    Returns:
        The new run folder.

    Raises:
        ValueError: On a missing source/licence or an unsupported format.
    """
    if not source.strip() or not licence.strip():
        raise ValueError("source and licence are required: provenance.json is the attribution record")
    if not files:
        raise ValueError("no files to import")
    for name, _ in files:
        if Path(name).suffix.lower() not in IMPORT_SUFFIXES:
            raise ValueError(f"{name}: unsupported format (use {', '.join(sorted(IMPORT_SUFFIXES))})")
    c = ga.Cue(id=cue["id"], kind=cue["kind"], prompt=cue.get("prompt", ""), duration_s=float(cue["duration_s"]),
               loop=bool(cue.get("loop")), bpm=cue.get("bpm"), key=cue.get("key"))
    run = default_run_dir(provider, baselines)
    run.mkdir(parents=True)
    rows = []
    for i, (name, data) in enumerate(files, 1):
        fname = f"{c.id}_c{i:02d}{Path(name).suffix.lower()}"
        (run / fname).write_bytes(data)
        rows.append({"cue": c.id, "kind": c.kind, "candidate": i, "ok": True, "latency_s": None, "bytes": len(data),
                     "file": fname, "requested_s": c.duration_s, "seed": None, "error": None,
                     "source": source.strip(), "licence": licence.strip(), "original_file": name})
    summary = {
        "provider": provider, "licence": licence.strip(), "settings": {"imported": True},
        "manifest_version": manifest.get("version"), "candidates_per_cue": len(rows), "aborted": None,
        "runs": len(rows), "success_rate": 1.0, "latency_p50_s": None, "latency_max_s": None,
        "generated_audio_s": None, "ok_per_cue": {c.id: len(rows)},
        "prompts": {c.id: ga.build_prompt(manifest, c)}, "rows": rows,
    }
    write_json(run / "summary.json", summary)
    return run


# --------------------------------------------------------------------------- edits

TRIM_KEEP_S = 0.02   # audio kept past the first/last frame above the silence threshold
TRIM_FADE_S = 0.01   # short fades so the cut itself cannot click
TRIM_MIN_FRACTION = 0.5  # refuse a trim that would leave less than half the take


def trimmed_of(summary: dict, file: str) -> dict | None:
    """The row already derived from `file` by a trim, if any."""
    return next((r for r in summary["rows"] if r.get("derived_from") == file and r.get("edit") == "trim"), None)


def trim_take(run_dir: Path, file: str) -> dict:
    """Cut the silent head and tail of a take into a new take of the same run.

    The source file is kept. The new take is a 16-bit WAV named <cue>_cNN.wav with the next free
    candidate number, appended to summary.json with derived_from / edit / trim_s, so it goes through
    the technical filter and the review like any other take, and provenance records where it came from.

    Returns:
        The new summary row.

    Raises:
        ValueError: If the take is missing, has nothing to trim, would become too short, or was trimmed already.
    """
    import numpy as np
    import soundfile as sf

    import audio_qc as qc

    summary = load_summary(run_dir)
    src = next((r for r in summary["rows"] if r.get("file") == file and r.get("ok")), None)
    if src is None:
        raise ValueError(f"{file} is not a successful take of {run_dir.name}")
    if trimmed_of(summary, file):
        raise ValueError(f"{file} was already trimmed into {trimmed_of(summary, file)['file']}")
    x, sr = qc.load_audio(run_dir / file)
    head, tail, silent = qc.silence_edges(x.mean(axis=1), sr)
    if silent:
        raise ValueError(f"{file} is silent: nothing to keep")
    keep = int(TRIM_KEEP_S * sr)
    start = max(0, int(round(head * sr)) - keep)
    end = min(len(x), len(x) - int(round(tail * sr)) + keep)
    if start == 0 and end == len(x):
        raise ValueError(f"{file} has no silent head or tail to trim")
    y = x[start:end].copy()
    if len(y) < TRIM_MIN_FRACTION * len(x):
        raise ValueError(f"trimming {file} would leave {len(y) / sr:.1f}s of {len(x) / sr:.1f}s")
    fade = min(int(TRIM_FADE_S * sr), len(y) // 4)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=y.dtype)[:, None]
        y[:fade] *= ramp
        y[-fade:] *= ramp[::-1]
    n = max(r["candidate"] for r in summary["rows"] if r["cue"] == src["cue"]) + 1
    name = f"{src['cue']}_c{n:02d}.wav"
    sf.write(run_dir / name, y, sr, subtype="PCM_16")
    duration = round(len(y) / sr, 3)
    row = {
        "cue": src["cue"], "kind": src.get("kind"), "candidate": n, "ok": True, "latency_s": None,
        "bytes": (run_dir / name).stat().st_size, "file": name,
        # Deliberately shorter than the provider was asked for: check the trimmed length instead.
        "requested_s": duration, "seed": src.get("seed"), "error": None,
        "derived_from": file, "edit": "trim",
        "trim_s": {"head": round(start / sr, 3), "tail": round((len(x) - end) / sr, 3)},
        "original_requested_s": src.get("requested_s"),
    }
    for key in ("source", "licence", "original_file"):
        if src.get(key):
            row[key] = src[key]
    summary["rows"].append(row)
    summary.setdefault("ok_per_cue", {})[src["cue"]] = sum(
        1 for r in summary["rows"] if r["cue"] == src["cue"] and r.get("ok"))
    write_json(run_dir / "summary.json", summary)
    return row


def trim_candidates(run_dir: Path, qc_results: dict) -> list[str]:
    """Takes failing only or partly on silence that have not been trimmed yet."""
    summary = load_summary(run_dir)
    return [r["file"] for r in summary["rows"]
            if r.get("ok") and not r.get("derived_from") and not trimmed_of(summary, r["file"])
            and r["file"] in qc_results and any(i.code == "silence" for i in qc_results[r["file"]].issues)]


# --------------------------------------------------------------------------- generation

def generate_command(provider: str, cue_ids: list[str], candidates: int, out_dir: Path,
                     manifest: Path = MANIFEST) -> list[str]:
    cmd = [sys.executable, str(ROOT / "tools" / "generate_audio.py"), "generate", "--provider", provider,
           "--candidates", str(int(candidates)), "--out", str(out_dir), "--manifest", str(manifest)]
    if cue_ids:
        cmd += ["--only", *cue_ids]
    return cmd


def acestep_status(url: str) -> str | None:
    """None if an ACE-Step server answers GET /health at url, else why not."""
    return ga.AceStepProvider(url or "http://127.0.0.1:8001", os.environ.get("ACESTEP_API_KEY")).check(timeout=3)


def start_generation(cmd: list[str], out_dir: Path, env: dict | None = None) -> tuple[subprocess.Popen, Path]:
    """Run generate_audio.py in the background, logging to <out_dir>/generate.log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "generate.log"
    log = open(log_path, "w", encoding="utf-8")  # closed by the child exiting; handle kept by Popen
    full_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", **(env or {})}
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT), env=full_env)
    return proc, log_path


def repo_url() -> str:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True,
                             text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        url = ""
    return url or "https://github.com/101PHOENIX/genai-lms-project-group4.git"


def current_branch() -> str:
    try:
        b = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True,
                           text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        b = ""
    return b or "main"


COLAB_PROVIDERS = ("acestep", "stable-audio")


def colab_cells(manifest_text: str, cue_ids: list[str], candidates: int, run_name: str,
                url: str | None = None, branch: str | None = None, provider: str = "acestep",
                script_text: str | None = None) -> list[tuple[str, str]]:
    """Notebook cells (title, code) that render the selected cues on a Colab GPU.

    provider "acestep" starts the ACE-Step REST server; "stable-audio" runs Stable Audio 3 Small-SFX
    in its own venv. The local manifest and the local tools/generate_audio.py are written with
    %%writefile, so unpushed edits (and providers not on GitHub yet) are used too. The run is zipped
    into Google Drive (MyDrive/audio_runs/<run>.zip) for import_run_zip.
    """
    if provider not in COLAB_PROVIDERS:
        raise ValueError(f"no Colab cells for provider {provider!r}")
    url, branch = url or repo_url(), branch or current_branch()
    if script_text is None:
        script_text = (ROOT / "tools" / "generate_audio.py").read_text(encoding="utf-8")
    repo = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    only = " ".join(cue_ids)
    write_manifest = f"%%writefile /content/{repo}/audio/audio_cues.json\n{manifest_text.rstrip()}\n"
    write_script = f"%%writefile /content/{repo}/tools/generate_audio.py\n{script_text.rstrip()}\n"
    args = (f"--candidates {int(candidates)} --manifest /content/{repo}/audio/audio_cues.json "
            f"--out /content/{repo}/baselines/{run_name}{' --only ' + only if only else ''}")
    save = f"""!mkdir -p /content/drive/MyDrive/audio_runs
!cd /content/{repo}/baselines && zip -qr /content/drive/MyDrive/audio_runs/{run_name}.zip {run_name}
print("Saved to MyDrive/audio_runs/{run_name}.zip: import it in Audio Studio")"""
    clone_repo = f"!test -d /content/{repo} || git clone -b {branch} {url} /content/{repo}"
    gpu = '!nvidia-smi --query-gpu=name,memory.total --format=csv || echo "NO GPU: change the runtime type"'

    if provider == "acestep":
        install = f"""# Runtime -> Change runtime type -> GPU (T4 is enough). Takes 3-6 min: it installs PyTorch.
{gpu}
!test -d /content/ACE-Step-1.5 || git clone --depth 1 https://github.com/ACE-Step/ACE-Step-1.5 /content/ACE-Step-1.5
!pip install -q uv
!cd /content/ACE-Step-1.5 && uv sync
{clone_repo}"""
        start = """# Starts the REST server in the background and waits for GET /health.
# The first start downloads the model weights (several GB): 5-15 min. Progress is printed every 20 s.
import json, os, subprocess, time, urllib.request
LOG = "/content/ACE-Step-1.5/api.log"

def healthy():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=5) as r:
            return json.load(r).get("data", {}).get("status") == "ok"
    except Exception:
        return False

def log_tail(n=5):
    try:
        with open(LOG, errors="replace") as f:
            return "".join(f.readlines()[-n:]).strip()
    except OSError:
        return "(no log yet)"

if healthy():
    print("ACE-Step server already running")
else:
    if "ace_server" not in globals() or ace_server.poll() is not None:
        # Colab sets MPLBACKEND to its inline backend, which ACE-Step's venv lacks: matplotlib would
        # crash the server on import. Agg is headless and always available.
        env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONUNBUFFERED": "1"}
        ace_server = subprocess.Popen(["uv", "run", "acestep-api"], cwd="/content/ACE-Step-1.5", env=env,
                                      stdout=open(LOG, "w"), stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, start_new_session=True)
    t0 = time.time()
    while not healthy():
        if ace_server.poll() is not None:
            raise RuntimeError(f"ACE-Step server exited (code {ace_server.returncode}). Last log lines:\\n{log_tail(30)}")
        if time.time() - t0 > 1800:
            raise TimeoutError(f"Server not up after 30 min. Last log lines:\\n{log_tail(30)}")
        time.sleep(20)
        print(f"[{int(time.time() - t0)} s] waiting... {log_tail(1)[-160:]}", flush=True)
    print(f"ACE-Step server is up after {int(time.time() - t0)} s")"""
        gen = f"""from google.colab import drive
drive.mount('/content/drive')
!python /content/{repo}/tools/generate_audio.py generate --provider acestep {args}
{save}"""
        return [("1. Install ACE-Step and clone the repo (3-6 min)", install),
                ("2. Start the ACE-Step server and wait until it is ready (first time 5-15 min)", start),
                ("3. Write the current manifest (local edits included)", write_manifest),
                ("4. Write the current generate_audio.py (local changes included)", write_script),
                ("5. Generate and save the run to Google Drive", gen)]

    install = f"""# Runtime -> Change runtime type -> GPU (T4 is plenty; Small-SFX also runs on CPU, slower).
# Takes 3-6 min: it installs PyTorch 2.7 in Stable Audio 3's own environment.
{gpu}
!test -d /content/stable-audio-3 || git clone --depth 1 https://github.com/Stability-AI/stable-audio-3 /content/stable-audio-3
!pip install -q uv
!cd /content/stable-audio-3 && uv sync
{clone_repo}"""
    login = """# Stable Audio 3 Small-SFX is gated. Once: open https://huggingface.co/stabilityai/stable-audio-3-small-sfx,
# log in and accept the licence. Then either add a Colab secret named HF_TOKEN (key icon on the left,
# 'Notebook access' on) or paste a read token in the box this cell shows.
import os
from huggingface_hub import login, whoami
token = None
try:
    from google.colab import userdata
    token = userdata.get("HF_TOKEN")
except Exception:
    pass
if token:
    login(token=token)  # saved to ~/.cache/huggingface, which the generation step reads
else:
    from huggingface_hub import notebook_login
    notebook_login()
print("Logged in to Hugging Face as", whoami()["name"])"""
    gen = f"""# The first take downloads the model weights; after that each take takes seconds on a GPU.
from google.colab import drive
drive.mount('/content/drive')
!cd /content/stable-audio-3 && MPLBACKEND=Agg uv run python /content/{repo}/tools/generate_audio.py generate --provider stable-audio {args}
{save}"""
    return [("1. Install Stable Audio 3 and clone the repo (3-6 min)", install),
            ("2. Log in to Hugging Face (gated model, once per session)", login),
            ("3. Write the current manifest (local edits included)", write_manifest),
            ("4. Write the current generate_audio.py (includes the stable-audio provider)", write_script),
            ("5. Generate and save the run to Google Drive", gen)]


# --------------------------------------------------------------------------- review state

def load_review(path: Path = REVIEW) -> dict:
    data = read_json(path, {})
    data.setdefault("version", 1)
    data.setdefault("decisions", {})
    return data


def save_review(review: dict, path: Path = REVIEW) -> None:
    write_json(path, review)


def decision_key(run: str, file: str) -> str:
    return f"{run}/{file}"


def _qc_fields(qc) -> dict:
    if qc is None:
        return {"qc_status": None, "qc_score": None, "qc_issues": []}
    return {"qc_status": qc.status, "qc_score": qc.score, "qc_issues": [i.message for i in qc.issues]}


def approve(review: dict, run: str, row: dict, qc=None) -> dict:
    """Mark a take as the cue's winner; an earlier winner of that cue becomes 'superseded'."""
    for d in review["decisions"].values():
        if d["cue"] == row["cue"] and d["status"] == "approved":
            d["status"] = "superseded"
    key = decision_key(run, row["file"])
    review["decisions"][key] = {
        "run": run, "cue": row["cue"], "kind": row.get("kind"), "take": row["candidate"], "file": row["file"],
        "status": "approved", "reasons": [], **_qc_fields(qc), "decided_at": now_iso(),
        "promoted_at": None, "unity_file": None, "unity_root": None,
    }
    return review["decisions"][key]


def reject(review: dict, run: str, row: dict, reasons: list[str], qc=None) -> dict:
    key = decision_key(run, row["file"])
    review["decisions"][key] = {
        "run": run, "cue": row["cue"], "kind": row.get("kind"), "take": row["candidate"], "file": row["file"],
        "status": "rejected", "reasons": list(reasons), **_qc_fields(qc), "decided_at": now_iso(),
        "promoted_at": None, "unity_file": None, "unity_root": None,
    }
    return review["decisions"][key]


def undo(review: dict, run: str, file: str) -> None:
    review["decisions"].pop(decision_key(run, file), None)


def winners(review: dict) -> dict[str, dict]:
    """Cue id -> approved decision."""
    return {d["cue"]: d for d in review["decisions"].values() if d["status"] == "approved"}


# --------------------------------------------------------------------------- promotion

def _cue_obj(cue: dict) -> ga.Cue:
    return ga.Cue(id=cue["id"], kind=cue["kind"], prompt=cue.get("prompt", ""), duration_s=float(cue["duration_s"]),
                  loop=bool(cue.get("loop")), bpm=cue.get("bpm"), key=cue.get("key"))


def needs_promotion(decision: dict, unity_audio: Path) -> bool:
    if not decision.get("promoted_at") or decision.get("unity_root") != str(Path(unity_audio).resolve()):
        return True
    dest = Path(decision["unity_file"]) if decision.get("unity_file") else None
    if dest and not dest.is_absolute():
        dest = ROOT / dest
    return dest is None or not dest.is_file()


def promote_decision(decision: dict, manifest: dict, unity_audio: Path, provenance: Path = PROVENANCE,
                     baselines: Path = BASELINES) -> Path:
    """Copy an approved take into Unity and write its provenance record (via generate_audio.promote).

    Raises:
        ValueError: If the cue left the manifest or the take is missing.
    """
    cues = all_cues(manifest)
    if decision["cue"] not in cues:
        raise ValueError(f"{decision['cue']} is no longer in the manifest")
    run_dir = baselines / decision["run"]
    src, record = ga._from_run(run_dir, decision["cue"], decision["take"])
    if not src.is_file():
        raise ValueError(f"{rel(src)} not found")
    record.update({"qc_status": decision.get("qc_status"), "qc_score": decision.get("qc_score"),
                   "run_date": run_date(decision["run"]), "approved_at": decision.get("decided_at")})
    dest = ga.promote(_cue_obj(cues[decision["cue"]]), src, record, Path(unity_audio), provenance)
    decision.update(promoted_at=now_iso(), unity_file=rel(dest), unity_root=str(Path(unity_audio).resolve()))
    return dest


# --------------------------------------------------------------------------- docs

def _md(text) -> str:
    return str(text if text is not None else "—").replace("|", "\\|").replace("\n", " ")


def run_stats(run: str, review: dict, baselines: Path = BASELINES) -> dict:
    """KPIs of one reviewed run, from its summary.json, qc.json and the decisions."""
    run_dir = baselines / run
    summary = load_summary(run_dir)
    qc = read_json(run_dir / "qc.json", {}).get("files", {})
    ok_rows = [r for r in summary["rows"] if r.get("ok")]
    statuses = Counter(qc[r["file"]]["result"]["status"] for r in ok_rows if r["file"] in qc)
    decisions = [d for d in review["decisions"].values() if d["run"] == run]
    approved = sorted({d["cue"] for d in decisions if d["status"] in ("approved", "superseded")})
    cues = list(dict.fromkeys(r["cue"] for r in summary["rows"]))
    reasons = Counter(r for d in decisions if d["status"] == "rejected" for r in d["reasons"])
    lat = [r["latency_s"] for r in ok_rows if r.get("latency_s") is not None]
    return {
        "run": run, "provider": summary.get("provider"), "manifest_version": summary.get("manifest_version"),
        "date": (run_date(run) or now_iso())[:10], "takes": len(summary["rows"]), "ok": len(ok_rows),
        "analyzed": sum(statuses.values()), "qc_pass": statuses.get("pass", 0), "qc_warn": statuses.get("warn", 0),
        "qc_fail": statuses.get("fail", 0), "cues": cues, "approved": approved,
        "rejected": sum(1 for d in decisions if d["status"] == "rejected"),
        "takes_per_accepted": round(sum(r["cue"] in approved for r in ok_rows) / len(approved), 1) if approved else None,
        "latency_p50_s": round(statistics.median(lat), 2) if lat else None, "reasons": reasons,
        "summary": summary, "qc": qc,
    }


def _log_row(s: dict) -> str:
    reasons = ", ".join(f"{k} {v}" for k, v in s["reasons"].most_common(3)) or "none"
    approved = ", ".join(s["approved"]) or "none"
    lat = f"{s['latency_p50_s']} s" if s["latency_p50_s"] is not None else "n/a"
    tpa = s["takes_per_accepted"] if s["takes_per_accepted"] is not None else "n/a"
    kpi = (f"QC pass {s['qc_pass']}/{s['ok']} (warn {s['qc_warn']}, auto-discarded {s['qc_fail']}); "
           f"approved {len(s['approved'])}/{len(s['cues'])} cues; takes per accepted cue {tpa}; "
           f"latency p50 {lat}; rejects: {reasons}")
    change = f"Audio Studio review of {s['ok']} takes ({len(s['cues'])} cues). Approved: {approved}"
    evidence = (f"`baselines/{s['run']}/summary.json`, `baselines/{s['run']}/qc.json`, `audio/review.json` "
                f"<!-- audio-studio-run:{s['run']} -->")
    return (f"| {s['date']} | 3 | Audio ({_md(s['provider'])}) | manifest {_md(s['manifest_version'])} | "
            f"{_md(change)} | {_md(kpi)} | {evidence} |")


def _take_table(s: dict, review: dict) -> list[str]:
    lines = [f"### {s['run']} ({s['provider']})", "",
             "| Cue | Take | QC | Score | LUFS | Duration (s) | Seam (dB / click / timbre) | Auto issues | Decision | Reasons |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in s["summary"]["rows"]:
        if not r.get("ok"):
            lines.append(f"| {r['cue']} | {r['candidate']} | error | — | — | — | — | {_md(r.get('error'))} | — | — |")
            continue
        q = s["qc"].get(r["file"], {}).get("result", {})
        seam = q.get("seam")
        seam_txt = f"{seam['level_step_db']} / {seam['click_ratio']} / {seam['spectral_distance']}" if seam else "—"
        issues = "; ".join(i["message"] for i in q.get("issues", [])) or "—"
        d = review["decisions"].get(decision_key(s["run"], r["file"]), {})
        lines.append(f"| {r['cue']} | {r['candidate']} | {q.get('status', 'not analyzed')} | {_md(q.get('score'))} | "
                     f"{_md(q.get('lufs'))} | {_md(q.get('duration_s'))} | {seam_txt} | {_md(issues)} | "
                     f"{d.get('status', 'undecided')} | {_md(', '.join(d.get('reasons', [])) or '—')} |")
    return lines + [""]


STUDIO_START, STUDIO_END = "<!-- audio-studio:start -->", "<!-- audio-studio:end -->"
INV_START, INV_END = "<!-- audio-inventory:start -->", "<!-- audio-inventory:end -->"


def _replace_block(text: str, start: str, end: str, body: str) -> str:
    block = f"{start}\n{body.rstrip()}\n{end}"
    if start in text and end in text:
        a, b = text.index(start), text.index(end) + len(end)
        return text[:a] + block + text[b:]
    return text.rstrip() + "\n\n" + block + "\n"


def update_iteration_log(review: dict, path: Path = ITERATION_LOG, baselines: Path = BASELINES) -> list[str]:
    """Upsert one row per reviewed run in the main table and rewrite the take-level section.

    Returns:
        Names of the runs written.
    """
    runs = sorted({d["run"] for d in review["decisions"].values() if (baselines / d["run"]).is_dir()},
                  key=lambda r: run_date(r) or "", reverse=True)
    stats = [run_stats(r, review, baselines) for r in runs]
    text = path.read_text(encoding="utf-8") if path.is_file() else (
        "# Iteration Log\n\n| Date | Team | Artifact | Version | Change | KPI before → after | Evidence |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n")
    lines = text.split("\n")
    for s in reversed(stats):  # insert oldest first so the newest ends on top
        marker = f"<!-- audio-studio-run:{s['run']} -->"
        row = _log_row(s)
        idx = next((i for i, l in enumerate(lines) if marker in l), None)
        if idx is not None:
            lines[idx] = row
            continue
        sep = next((i for i, l in enumerate(lines) if l.startswith("| --- |")), None)
        if sep is None:
            raise ValueError(f"{path.name}: no results table found")
        lines.insert(sep + 1, row)
    text = "\n".join(lines)
    body = ["## Audio Studio: take-level results", "",
            "_Generated by `tools/audio_studio.py` from `baselines/<run>/qc.json` and `audio/review.json`. "
            "Edits inside this block are overwritten._", ""]
    for s in stats:
        body += _take_table(s, review)
    text = _replace_block(text, STUDIO_START, STUDIO_END, "\n".join(body))
    path.write_text(text, encoding="utf-8")
    return runs


def inventory_markdown(manifest: dict, review: dict, provenance: dict) -> str:
    win = winners(review)
    rows = ["## 7. Inventory", "",
            "_Generated by `tools/audio_studio.py` from `audio/audio_cues.json`, `audio/review.json` and "
            "`audio/provenance.json`. Edits inside this block are overwritten._", ""]
    done = 0
    table = ["| Cue | Kind | Loop | Duration (s) | Status | Provider | Run / take | Licence | QC |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    cues = all_cues(manifest)
    for cid, c in cues.items():
        p, d = provenance.get(cid), win.get(cid)
        if p and d and p.get("run") == d["run"] and p.get("take") == d["take"]:
            status = "approved"
        elif d:
            status = "approved, not promoted"
        elif p:
            status = "promoted (CLI)"
        else:
            status = "pending"
        done += status in ("approved", "promoted (CLI)")
        src = p or {}
        run_take = f"{src['run']} / {src['take']}" if src.get("run") else (
            f"{d['run']} / {d['take']}" if d else (_md(src.get("source")) if src else "—"))
        qc = (d or {}).get("qc_score") if d else src.get("qc_score")
        table.append(f"| {cid} | {c['kind']} | {'yes' if c.get('loop') else 'no'} | {_md(c.get('duration_s'))} | "
                     f"**{status}** | {_md(src.get('provider'))} | {_md(run_take)} | {_md(src.get('licence'))} | "
                     f"{_md(qc)} |")
    rows.append(f"{done}/{len(cues)} cues have an asset in Unity "
                f"(manifest {_md(manifest.get('version'))}, updated {now_iso()[:16].replace('T', ' ')}).")
    return "\n".join(rows + [""] + table)


def update_audio_doc(manifest: dict, review: dict, provenance: dict, path: Path = AUDIO_DOC) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(_replace_block(text, INV_START, INV_END, inventory_markdown(manifest, review, provenance)),
                    encoding="utf-8")


def apply_changes(manifest: dict, review: dict, unity_audio: Path, *, provenance: Path = PROVENANCE,
                  baselines: Path = BASELINES, review_path: Path = REVIEW, iteration_log: Path = ITERATION_LOG,
                  audio_doc: Path = AUDIO_DOC) -> list[str]:
    """Promote every approved take not yet in Unity, then regenerate the docs. Safe to run repeatedly.

    Returns:
        Report lines for the UI.
    """
    report = []
    for cue, d in winners(review).items():
        if not needs_promotion(d, unity_audio):
            continue
        try:
            dest = promote_decision(d, manifest, unity_audio, provenance, baselines)
            report.append(f"promoted {cue} -> {rel(dest)}")
        except (ValueError, FileNotFoundError, KeyError) as e:
            report.append(f"FAILED {cue}: {e}")
    save_review(review, review_path)
    runs = update_iteration_log(review, iteration_log, baselines)
    report.append(f"{iteration_log.name}: {len(runs)} run row(s) and the take-level section updated")
    update_audio_doc(manifest, review, read_json(provenance, {}), audio_doc)
    report.append(f"{audio_doc.name}: inventory updated")
    return report
