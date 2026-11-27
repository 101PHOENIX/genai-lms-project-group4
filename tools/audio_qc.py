"""Objective technical checks on generated audio takes, so only plausible ones need a listen.

Used by tools/audio_studio.py. No UI code here. Each take gets a status (pass / warn / fail),
a 0-100 technical score and human-readable issues:

  duration     length differs from the requested duration (> 5 % and > 0.5 s)       fail
  silence      silent head/tail (< -50 dBFS): loops > 0.25 s fail, one-shot head warn
  muted        integrated loudness below -35 LUFS, or no signal at all             fail
  clipping     > 0.1 % of samples at full scale                                   fail
  loudness     hotter than -8 LUFS or quieter than -26 LUFS                       warn
  jumps        short-term loudness jumps > 10 LU between 3 s windows              warn
  seam         loops only: level step, click or timbre change at the loop point   warn

Loudness follows ITU-R BS.1770 (K-weighting, 400 ms blocks, absolute and relative gates).
Results are cached in <run>/qc.json and recomputed only when a file changes.

Requires numpy, scipy and soundfile (requirements-audio.txt).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from scipy.signal import lfilter

QC_VERSION = 1
SILENCE_DBFS = -50.0
FRAME_S = 0.01

# Thresholds (see module docstring).
DURATION_TOL_REL, DURATION_TOL_ABS = 0.05, 0.5
LOOP_SILENCE_FAIL_S = 0.25
ONESHOT_HEAD_WARN_S = 0.3
MUTED_LUFS = -35.0
HOT_LUFS, QUIET_LUFS = -8.0, -26.0
CLIP_LEVEL, CLIP_FRACTION = 0.999, 0.001
JUMP_LU = 10.0
SEAM_LEVEL_DB = 6.0
SEAM_CLICK_RATIO = 4.0
SEAM_SPECTRAL = 0.35

PENALTY = {"fail": 40, "warn": 12}


@dataclass
class Issue:
    code: str
    severity: str  # "fail" | "warn"
    message: str


@dataclass
class QcResult:
    status: str  # "pass" | "warn" | "fail"
    score: int
    duration_s: float | None = None
    requested_s: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    lufs: float | None = None
    peak_dbfs: float | None = None
    clip_fraction: float | None = None
    head_silence_s: float | None = None
    tail_silence_s: float | None = None
    max_jump_lu: float | None = None
    seam: dict | None = None
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "QcResult":
        d = dict(d)
        d["issues"] = [Issue(**i) for i in d.get("issues", [])]
        return QcResult(**d)


# --------------------------------------------------------------------------- decoding

def load_audio(path: Path) -> tuple[np.ndarray, int]:
    """Decode an audio file to float32 samples.

    Args:
        path: WAV, MP3, OGG, FLAC or AIFF file.

    Returns:
        Samples shaped (frames, channels) in [-1, 1] and the sample rate.

    Raises:
        RuntimeError: If the file cannot be decoded.
    """
    try:
        import soundfile as sf
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise RuntimeError("soundfile is not installed: pip install -r requirements-audio.txt") from e
    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception as e:  # soundfile raises LibsndfileError / RuntimeError / TypeError
        raise RuntimeError(f"cannot decode {Path(path).name}: {e}") from e
    return data, int(sr)


# --------------------------------------------------------------------------- loudness

def _biquad_high_shelf(sr: int) -> tuple[np.ndarray, np.ndarray]:
    gain_db, q, fc = 4.0, 1 / math.sqrt(2), 1500.0
    a_ = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * fc / sr
    alpha = math.sin(w0) / (2 * q)
    cw, sa = math.cos(w0), 2 * math.sqrt(a_) * alpha
    b = [a_ * ((a_ + 1) + (a_ - 1) * cw + sa), -2 * a_ * ((a_ - 1) + (a_ + 1) * cw), a_ * ((a_ + 1) + (a_ - 1) * cw - sa)]
    a = [(a_ + 1) - (a_ - 1) * cw + sa, 2 * ((a_ - 1) - (a_ + 1) * cw), (a_ + 1) - (a_ - 1) * cw - sa]
    return np.array(b) / a[0], np.array(a) / a[0]


def _biquad_high_pass(sr: int) -> tuple[np.ndarray, np.ndarray]:
    q, fc = 0.5, 38.0
    w0 = 2 * math.pi * fc / sr
    alpha = math.sin(w0) / (2 * q)
    cw = math.cos(w0)
    b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
    a = [1 + alpha, -2 * cw, 1 - alpha]
    return np.array(b) / a[0], np.array(a) / a[0]


def k_weight(x: np.ndarray, sr: int) -> np.ndarray:
    """Apply the BS.1770 K-weighting filter along axis 0."""
    for b, a in (_biquad_high_shelf(sr), _biquad_high_pass(sr)):
        x = lfilter(b, a, x, axis=0)
    return x


def _block_loudness(kw: np.ndarray, sr: int, block_s: float, hop_s: float) -> np.ndarray:
    n, step = int(block_s * sr), max(1, int(hop_s * sr))
    if len(kw) < n:
        n = len(kw)
    starts = range(0, len(kw) - n + 1, step)
    power = np.array([np.mean(kw[s:s + n] ** 2, axis=0).sum() for s in starts])
    with np.errstate(divide="ignore"):
        return -0.691 + 10 * np.log10(power)


def integrated_lufs(x: np.ndarray, sr: int) -> float:
    """Gated integrated loudness (LUFS) of (frames, channels) samples; -inf when silent."""
    if len(x) == 0:
        return -math.inf
    blocks = _block_loudness(k_weight(x, sr), sr, 0.4, 0.1)
    blocks = blocks[blocks > -70.0]
    if blocks.size == 0:
        return -math.inf
    def mean_lufs(b):
        return -0.691 + 10 * math.log10(np.mean(10 ** ((b + 0.691) / 10)))
    rel = mean_lufs(blocks) - 10.0
    gated = blocks[blocks > rel]
    return mean_lufs(gated if gated.size else blocks)


def short_term_lufs(x: np.ndarray, sr: int) -> np.ndarray:
    """Ungated 3 s loudness every 1 s."""
    return _block_loudness(k_weight(x, sr), sr, 3.0, 1.0)


# --------------------------------------------------------------------------- checks

def _db(v: float) -> float:
    return 20 * math.log10(v) if v > 0 else -math.inf


def silence_edges(mono: np.ndarray, sr: int) -> tuple[float, float, bool]:
    """Seconds of silence at the head and tail, and whether the whole take is silent."""
    frame = max(1, int(FRAME_S * sr))
    n = len(mono) // frame
    if n == 0:
        return 0.0, 0.0, True
    rms = np.sqrt(np.mean(mono[:n * frame].reshape(n, frame) ** 2, axis=1))
    loud = np.flatnonzero(rms > 10 ** (SILENCE_DBFS / 20))
    if loud.size == 0:
        return len(mono) / sr, len(mono) / sr, True
    return loud[0] * FRAME_S, (n - 1 - loud[-1]) * FRAME_S, False


def loop_seam(mono: np.ndarray, sr: int) -> dict:
    """Measure how cleanly the end of a take joins its start.

    Returns:
        level_step_db: RMS difference between the last and first 50 ms.
        click_ratio: sample jump at the join relative to the typical step near the edges.
        spectral_distance: 1 - cosine similarity of the last and first second's spectra.
    """
    w = max(16, int(0.05 * sr))
    if len(mono) < 4 * w:
        return {"level_step_db": 0.0, "click_ratio": 0.0, "spectral_distance": 0.0}
    head, tail = mono[:w], mono[-w:]
    rms_h, rms_t = float(np.sqrt(np.mean(head ** 2))), float(np.sqrt(np.mean(tail ** 2)))
    floor = 10 ** (SILENCE_DBFS / 20)
    level = abs(_db(max(rms_t, floor)) - _db(max(rms_h, floor)))
    edge_steps = np.abs(np.diff(np.concatenate([tail, head])))
    typical = float(np.percentile(edge_steps, 95)) + 1e-6
    click = float(abs(mono[0] - mono[-1])) / typical
    s = min(len(mono) // 4, sr)
    win = np.hanning(s)
    a = np.abs(np.fft.rfft(mono[-s:] * win))
    b = np.abs(np.fft.rfft(mono[:s] * win))
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    spectral = 1.0 - float(np.dot(a, b)) / denom if denom > 0 else 0.0
    return {"level_step_db": round(level, 2), "click_ratio": round(click, 2), "spectral_distance": round(spectral, 3)}


def analyze_samples(x: np.ndarray, sr: int, *, loop: bool, requested_s: float | None) -> QcResult:
    """Run every check on decoded samples.

    Args:
        x: Samples shaped (frames, channels).
        sr: Sample rate.
        loop: Whether the cue loops (enables the seam and strict silence checks).
        requested_s: Duration asked from the provider, or None to skip the duration check.

    Returns:
        The QC result with status, score, metrics and issues.
    """
    issues: list[Issue] = []
    mono = x.mean(axis=1) if x.ndim == 2 else x
    duration = len(mono) / sr
    res = QcResult(status="pass", score=100, duration_s=round(duration, 3), requested_s=requested_s,
                   sample_rate=sr, channels=int(x.shape[1]) if x.ndim == 2 else 1)

    if requested_s:
        err = abs(duration - requested_s)
        if err > DURATION_TOL_ABS and err > DURATION_TOL_REL * requested_s:
            issues.append(Issue("duration", "fail", f"duration {duration:.1f}s vs requested {requested_s:g}s"))

    peak = float(np.max(np.abs(x))) if x.size else 0.0
    res.peak_dbfs = round(_db(peak), 2) if peak > 0 else None
    res.clip_fraction = round(float(np.mean(np.abs(x) >= CLIP_LEVEL)), 5) if x.size else 0.0
    if res.clip_fraction > CLIP_FRACTION:
        issues.append(Issue("clipping", "fail", f"clipping: {res.clip_fraction:.2%} of samples at full scale"))

    head, tail, silent = silence_edges(mono, sr)
    res.head_silence_s, res.tail_silence_s = round(head, 2), round(tail, 2)
    lufs = integrated_lufs(x if x.ndim == 2 else x[:, None], sr)
    res.lufs = round(lufs, 1) if math.isfinite(lufs) else None
    if silent or not math.isfinite(lufs) or lufs < MUTED_LUFS:
        issues.append(Issue("muted", "fail", "no signal" if silent or res.lufs is None
                            else f"almost muted: {lufs:.1f} LUFS"))
    else:
        if lufs > HOT_LUFS:
            issues.append(Issue("loudness", "warn", f"very loud: {lufs:.1f} LUFS (> {HOT_LUFS:g})"))
        elif lufs < QUIET_LUFS:
            issues.append(Issue("loudness", "warn", f"quiet: {lufs:.1f} LUFS (< {QUIET_LUFS:g})"))
        if loop:
            if head > LOOP_SILENCE_FAIL_S:
                issues.append(Issue("silence", "fail", f"loop starts with {head:.2f}s of silence"))
            if tail > LOOP_SILENCE_FAIL_S:
                issues.append(Issue("silence", "fail", f"loop ends with {tail:.2f}s of silence"))
        elif head > ONESHOT_HEAD_WARN_S:
            issues.append(Issue("silence", "warn", f"one-shot starts {head:.2f}s late"))

        if duration >= 6.0:
            st = short_term_lufs(x if x.ndim == 2 else x[:, None], sr)
            st = st[np.isfinite(st) & (st > -70.0)]
            if st.size >= 2:
                res.max_jump_lu = round(float(np.max(np.abs(np.diff(st)))), 1)
                if res.max_jump_lu > JUMP_LU:
                    issues.append(Issue("jumps", "warn", f"loudness jumps {res.max_jump_lu:.1f} LU between 3 s windows"))

        if loop:
            res.seam = loop_seam(mono, sr)
            if res.seam["level_step_db"] > SEAM_LEVEL_DB:
                issues.append(Issue("seam", "warn", f"loop seam level step {res.seam['level_step_db']:.1f} dB"))
            if res.seam["click_ratio"] > SEAM_CLICK_RATIO:
                issues.append(Issue("seam", "warn", f"click at the loop seam (x{res.seam['click_ratio']:.1f} the usual step)"))
            if res.seam["spectral_distance"] > SEAM_SPECTRAL:
                issues.append(Issue("seam", "warn", f"timbre changes across the loop seam ({res.seam['spectral_distance']:.2f})"))

    res.issues = issues
    res.score = score(res)
    res.status = "fail" if any(i.severity == "fail" for i in issues) else "warn" if issues else "pass"
    return res


def score(res: QcResult) -> int:
    """0-100 technical score: issue penalties plus distance from a comfortable loudness."""
    s = 100.0 - sum(PENALTY[i.severity] for i in res.issues)
    if res.lufs is not None:
        s -= min(15.0, abs(res.lufs - (-16.0)) * 1.0)
    if res.seam:
        s -= min(10.0, res.seam["click_ratio"]) + 10 * res.seam["spectral_distance"]
    return int(max(0, min(100, round(s))))


def analyze(path: Path, *, loop: bool, requested_s: float | None) -> QcResult:
    """Decode and analyze one file; decoding errors become a failed result."""
    try:
        x, sr = load_audio(path)
    except RuntimeError as e:
        return QcResult(status="fail", score=0, requested_s=requested_s,
                        issues=[Issue("unreadable", "fail", str(e))])
    return analyze_samples(x, sr, loop=loop, requested_s=requested_s)


# --------------------------------------------------------------------------- run cache

def analyze_run(run_dir: Path, loops: dict[str, bool], *, force: bool = False) -> dict[str, QcResult]:
    """Analyze every successful take of a run, reusing <run>/qc.json when files are unchanged.

    Args:
        run_dir: Run folder with summary.json.
        loops: Cue id -> loop flag from the manifest (unknown cues count as one-shots).
        force: Recompute everything.

    Returns:
        File name -> QC result.
    """
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    cache_path = run_dir / "qc.json"
    cache = {}
    if cache_path.is_file() and not force:
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}
    if cache.get("qc_version") != QC_VERSION:
        cache = {}
    files = cache.get("files", {})
    out: dict[str, QcResult] = {}
    changed = False
    for row in summary.get("rows", []):
        if not row.get("ok") or not row.get("file"):
            continue
        path = run_dir / row["file"]
        loop = bool(loops.get(row["cue"], False))
        stamp = [path.stat().st_size, int(path.stat().st_mtime)] if path.is_file() else None
        hit = files.get(row["file"])
        if hit and hit.get("stamp") == stamp and hit.get("loop") == loop:
            out[row["file"]] = QcResult.from_dict(hit["result"])
            continue
        if stamp is None:
            res = QcResult(status="fail", score=0, requested_s=row.get("requested_s"),
                           issues=[Issue("missing", "fail", f"{row['file']} not found in the run folder")])
        else:
            res = analyze(path, loop=loop, requested_s=row.get("requested_s"))
        files[row["file"]] = {"stamp": stamp, "loop": loop, "result": res.to_dict()}
        out[row["file"]] = res
        changed = True
    if changed or not cache_path.is_file():
        cache_path.write_text(json.dumps({"qc_version": QC_VERSION, "files": files}, indent=1), encoding="utf-8")
    return out
