"""Tests for tools/audio_qc.py, tools/audio_ops.py and the Audio Studio UI start-up.

Needs requirements-audio.txt; skipped otherwise.
Run: python -m unittest discover -s tests -p "test_*.py"
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

DEPS = all(importlib.util.find_spec(m) for m in ("numpy", "scipy", "soundfile"))
if DEPS:
    import numpy as np
    import soundfile as sf

    import audio_ops as ops
    import audio_qc as qc
    import generate_audio as ga

SR = 22050


def tone(seconds: float, freq: float = 440.0, amp: float = 0.25) -> "np.ndarray":
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype("float32")


@unittest.skipUnless(DEPS, "needs requirements-audio.txt")
class QcTests(unittest.TestCase):
    def check(self, x, loop=True, requested=None):
        return qc.analyze_samples(x[:, None], SR, loop=loop, requested_s=requested or len(x) / SR)

    def codes(self, res):
        return {(i.code, i.severity) for i in res.issues}

    def test_clean_whole_period_loop_passes(self):
        res = self.check(tone(10.0))  # 440 Hz x 10 s: whole periods, seamless
        self.assertEqual("pass", res.status, res.issues)
        self.assertGreater(res.score, 90)
        self.assertLess(res.seam["click_ratio"], 2)

    def test_lufs_matches_bs1770_reference(self):
        # A 997 Hz sine at -20 dBFS peak reads about -23 LUFS on a single channel (-3.01 dB RMS, K-weighting ~0).
        res = self.check(tone(10.0, 997.0, 10 ** (-20 / 20)), loop=False)
        self.assertAlmostEqual(-23.0, res.lufs, delta=0.5)

    def test_loop_with_silent_head_and_tail_fails(self):
        x = np.concatenate([np.zeros(SR), tone(8.0), np.zeros(SR)]).astype("float32")
        res = self.check(x)
        self.assertEqual("fail", res.status)
        self.assertIn(("silence", "fail"), self.codes(res))
        self.assertAlmostEqual(1.0, res.head_silence_s, delta=0.02)

    def test_one_shot_late_start_only_warns(self):
        x = np.concatenate([np.zeros(SR // 2), tone(2.0)]).astype("float32")
        self.assertIn(("silence", "warn"), self.codes(self.check(x, loop=False)))

    def test_muted_clipped_and_wrong_length(self):
        self.assertIn(("muted", "fail"), self.codes(self.check(np.zeros(SR * 3, "float32"))))
        self.assertIn(("muted", "fail"), self.codes(self.check(tone(3.0, amp=0.001))))
        clipped = np.clip(tone(3.0, amp=3.0), -1, 1)
        self.assertIn(("clipping", "fail"), self.codes(self.check(clipped)))
        self.assertIn(("duration", "fail"), self.codes(self.check(tone(5.0), requested=10.0)))

    def test_bad_seam_and_loudness_jump_warn(self):
        x = np.concatenate([tone(5.0, 220.0, 0.02), tone(5.0 + 0.37 / 440, 440.0, 0.6)]).astype("float32")
        res = self.check(x)
        self.assertEqual("warn", res.status, res.issues)
        self.assertIn(("seam", "warn"), self.codes(res))
        self.assertIn(("jumps", "warn"), self.codes(res))
        self.assertLess(res.score, self.check(tone(10.0)).score)

    def test_analyze_run_caches_and_flags_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            sf.write(run / "a_c01.wav", tone(4.0), SR)
            (run / "a_c02.wav").write_bytes(b"not audio" * 200)
            rows = [{"cue": "a", "candidate": i, "ok": True, "file": f"a_c0{i}.wav", "requested_s": 4.0} for i in (1, 2)]
            (run / "summary.json").write_text(json.dumps({"rows": rows, "prompts": {}}), encoding="utf-8")
            res = qc.analyze_run(run, {"a": True})
            self.assertEqual("pass", res["a_c01.wav"].status)
            self.assertEqual("unreadable", res["a_c02.wav"].issues[0].code)
            cached = json.loads((run / "qc.json").read_text(encoding="utf-8"))
            self.assertEqual(qc.QC_VERSION, cached["qc_version"])
            again = qc.analyze_run(run, {"a": True})
            self.assertEqual(res["a_c01.wav"].to_dict(), again["a_c01.wav"].to_dict())


@unittest.skipUnless(DEPS, "needs requirements-audio.txt")
class ManifestTests(unittest.TestCase):
    def test_dump_round_trips_the_repo_manifest(self):
        text = ops.MANIFEST.read_text(encoding="utf-8")
        self.assertEqual(text, ops.dump_manifest(json.loads(text)))

    def test_add_cue_validates_and_normalizes(self):
        m = ops.load_manifest()
        new, errors = ops.add_cue(m, "sfx", {"id": "door_slam", "prompt": "Door slams.", "duration_s": 2.0,
                                             "loop": False, "bpm": 120, "key": "C"})
        self.assertEqual([], errors)
        self.assertEqual({"id": "door_slam", "prompt": "Door slams.", "duration_s": 2, "loop": False}, new["sfx"][-1])
        self.assertNotIn("door_slam", ops.all_cues(m))  # original untouched
        self.assertTrue(ops.add_cue(m, "sfx", {"id": "dice_roll", "prompt": "x", "duration_s": 1})[1])
        self.assertTrue(ops.add_cue(m, "sfx", {"id": "Door-2", "prompt": "x", "duration_s": 1})[1])
        self.assertTrue(ops.add_cue(m, "sfx", {"id": "beep", "prompt": " ", "duration_s": 1})[1])

    def test_add_csharp_constant_after_last_string_constant(self):
        with tempfile.TemporaryDirectory() as d:
            music, sfx = Path(d) / "MusicCues.cs", Path(d) / "SfxPlayer.cs"
            shutil.copy(ops.MUSIC_CUES_CS, music)
            shutil.copy(ops.SFX_PLAYER_CS, sfx)
            ops.add_csharp_constant("sfx", "door_slam", music, sfx)
            src = sfx.read_text(encoding="utf-8")
            self.assertIn('public const string VerdictWrong = "verdict_wrong";\n'
                          '            public const string DoorSlam = "door_slam";', src)
            self.assertIn("already declared", ops.add_csharp_constant("sfx", "door_slam", music, sfx))
            ops.add_csharp_constant("music", "credits_theme", music, sfx)
            self.assertIn('public const string CreditsTheme = "credits_theme";', music.read_text(encoding="utf-8"))


@unittest.skipUnless(DEPS, "needs requirements-audio.txt")
class PipelineTests(unittest.TestCase):
    """Generate -> QC -> approve/reject -> apply, all inside a temp folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.base = self.tmp / "baselines"
        self.unity = self.tmp / "Audio"
        self.prov = self.tmp / "provenance.json"
        self.review_path = self.tmp / "review.json"
        self.log = self.tmp / "ITERATION_LOG.md"
        self.doc = self.tmp / "AUDIO.md"
        shutil.copy(ops.ITERATION_LOG, self.log)
        shutil.copy(ops.AUDIO_DOC, self.doc)
        self.manifest = ops.load_manifest()

    def apply(self, review):
        return ops.apply_changes(self.manifest, review, self.unity, provenance=self.prov, baselines=self.base,
                                 review_path=self.review_path, iteration_log=self.log, audio_doc=self.doc)

    def test_end_to_end(self):
        _, cues = ga.load_cues(ga.MANIFEST)
        picked = [c for c in cues if c.id in ("victory", "investigation", "dice_roll")]
        run = self.base / "20261127-1000-audio-mock"
        ga.run_generate(ga.MockProvider(), self.manifest, picked, 2, run)
        self.assertIn(run, ops.list_runs(self.base))
        results = qc.analyze_run(run, {c.id: c.loop for c in cues})
        summary = ops.load_summary(run)
        row = {r["file"]: r for r in summary["rows"]}

        review = ops.load_review(self.review_path)
        ops.approve(review, run.name, row["victory_c01.wav"], results["victory_c01.wav"])
        ops.approve(review, run.name, row["victory_c02.wav"], results["victory_c02.wav"])  # replaces take 1
        ops.reject(review, run.name, row["investigation_c01.wav"], ["Bad loop", "Vocals"], results["investigation_c01.wav"])
        ops.approve(review, run.name, row["dice_roll_c02.wav"], results["dice_roll_c02.wav"])
        self.assertEqual({"victory": 2, "dice_roll": 2}, {c: d["take"] for c, d in ops.winners(review).items()})

        report = self.apply(review)
        self.assertFalse([l for l in report if l.startswith("FAILED")], report)
        self.assertTrue((self.unity / "Music" / "victory.wav").is_file())
        self.assertTrue((self.unity / "SFX" / "dice_roll.wav").is_file())
        prov = json.loads(self.prov.read_text(encoding="utf-8"))
        v = prov["victory"]
        self.assertEqual(("mock", run.name, 2, "2026-11-27T10:00"), (v["provider"], v["run"], v["take"], v["run_date"]))
        for key in ("seed", "latency_s", "prompt", "qc_score", "manifest_version", "promoted_at", "licence"):
            self.assertIn(key, v)
        self.assertIsNotNone(v["seed"])

        log = self.log.read_text(encoding="utf-8")
        self.assertEqual(1, log.count(f"<!-- audio-studio-run:{run.name} -->"))
        self.assertIn("approved 2/3 cues; takes per accepted cue 2.0", log)
        self.assertIn("rejects: Bad loop 1, Vocals 1", log)
        self.assertIn("| investigation | 1 |", log)
        self.assertIn("| --- | --- | --- | --- | --- | --- | --- |\n| 2026-11-27 | 3 | Audio (mock)", log)
        doc = self.doc.read_text(encoding="utf-8")
        self.assertIn("| victory | music | no | 10 | **approved** | mock |", doc)
        self.assertIn("| trial | music | yes | 75 | **pending** |", doc)

        promoted_at = json.loads(self.review_path.read_text(encoding="utf-8"))["decisions"][
            f"{run.name}/victory_c02.wav"]["promoted_at"]
        self.apply(ops.load_review(self.review_path))  # idempotent
        self.assertEqual(log.split("## Audio Studio")[0].count("audio-studio-run"),
                         self.log.read_text(encoding="utf-8").split("## Audio Studio")[0].count("audio-studio-run"))
        self.assertEqual(1, self.doc.read_text(encoding="utf-8").count(ops.INV_START))
        again = json.loads(self.review_path.read_text(encoding="utf-8"))["decisions"][f"{run.name}/victory_c02.wav"]
        self.assertEqual(promoted_at, again["promoted_at"])

    def test_trim_silence_makes_a_new_passing_take(self):
        run = self.base / "20261127-1942-audio-acestep"
        run.mkdir(parents=True)
        # 0.6 s silent head, 9 s of whole-period tone, 4 s silent tail: the ACE-Step pattern
        sf.write(run / "exploration_c01.wav", np.concatenate([np.zeros(int(0.6 * SR)), tone(9.0), np.zeros(4 * SR)]), SR)
        rows = [{"cue": "exploration", "kind": "music", "candidate": 1, "ok": True, "latency_s": 260.0,
                 "file": "exploration_c01.wav", "requested_s": 13.6, "seed": "42", "error": None}]
        ops.write_json(run / "summary.json", {"provider": "acestep", "licence": "MIT (ACE-Step 1.5)", "settings": {},
                                              "manifest_version": "v0", "prompts": {"exploration": "P"}, "rows": rows,
                                              "ok_per_cue": {"exploration": 1}})
        loops = {"exploration": True}
        before = qc.analyze_run(run, loops)
        self.assertEqual("fail", before["exploration_c01.wav"].status)
        self.assertEqual(["exploration_c01.wav"], ops.trim_candidates(run, before))

        row = ops.trim_take(run, "exploration_c01.wav")
        self.assertEqual(("exploration_c02.wav", 2, "exploration_c01.wav"), (row["file"], row["candidate"], row["derived_from"]))
        self.assertAlmostEqual(0.6, row["trim_s"]["head"], delta=0.05)
        self.assertAlmostEqual(4.0, row["trim_s"]["tail"], delta=0.05)
        self.assertTrue((run / "exploration_c01.wav").is_file())  # original kept
        after = qc.analyze_run(run, loops)
        self.assertEqual("pass", after["exploration_c02.wav"].status, after["exploration_c02.wav"].issues)
        self.assertAlmostEqual(9.0, after["exploration_c02.wav"].duration_s, delta=0.1)
        self.assertEqual([], ops.trim_candidates(run, after))
        self.assertEqual(2, ops.load_summary(run)["ok_per_cue"]["exploration"])
        with self.assertRaisesRegex(ValueError, "already trimmed"):
            ops.trim_take(run, "exploration_c01.wav")
        with self.assertRaisesRegex(ValueError, "no silent head or tail"):
            ops.trim_take(run, "exploration_c02.wav")

        _, record = ga._from_run(run, "exploration", 2)
        self.assertEqual(("exploration_c01.wav", "trim", "42"), (record["derived_from"], record["edit"], record["seed"]))

    def test_import_external_takes_and_zip(self):
        cue = ops.all_cues(self.manifest)["door_open"]
        wav = self.tmp / "door.wav"
        sf.write(wav, tone(2.0), SR)
        with self.assertRaises(ValueError):
            ops.import_external_takes(cue, [("door.wav", wav.read_bytes())], "freesound", "", "CC0", self.manifest, self.base)
        run = ops.import_external_takes(cue, [("door.wav", wav.read_bytes())], "freesound",
                                        "Freesound: someone, 123", "CC0", self.manifest, self.base)
        self.assertTrue(ops.is_audio_run(run))
        src, record = ga._from_run(run, "door_open", 1)
        self.assertEqual(("freesound", "Freesound: someone, 123", "CC0", "door.wav"),
                         (record["provider"], record["source"], record["licence"], record["original_file"]))

        z = self.tmp / "run.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in run.iterdir():
                zf.write(f, f"20261127-1200-audio-acestep/{f.name}")
        dest = ops.import_run_zip(z, self.base)
        self.assertEqual("20261127-1200-audio-acestep", dest.name)
        self.assertTrue((dest / "door_open_c01.wav").is_file())
        self.assertFalse((self.base / "_import_tmp").exists())

        evil = self.tmp / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../escape.txt", "x")
        with self.assertRaises(ValueError):
            ops.import_run_zip(evil, self.base)

    def test_colab_cells_embed_manifest_and_cues(self):
        cells = ops.colab_cells('{"music": []}', ["trial"], 2, "20261127-1300-audio-acestep",
                                url="https://github.com/x/genai-lms-project-group4.git", branch="audio")
        code = "\n".join(c for _, c in cells)
        self.assertIn("git clone -b audio https://github.com/x/genai-lms-project-group4.git", code)
        self.assertEqual(5, len(cells))
        compile(cells[1][1], "start_server_cell", "exec")  # plain Python: polls /health, fails fast
        self.assertIn("127.0.0.1:8001/health", cells[1][1])
        self.assertIn("ace_server.poll() is not None", cells[1][1])
        self.assertIn('"MPLBACKEND": "Agg"', cells[1][1])  # Colab's inline backend crashes ACE-Step's venv
        self.assertTrue(cells[2][1].startswith("%%writefile /content/genai-lms-project-group4/audio/audio_cues.json"))
        # The local generate_audio.py is shipped too, so Colab never runs an older pushed copy.
        script = ga.ROOT.joinpath("tools", "generate_audio.py").read_text(encoding="utf-8").rstrip()
        self.assertEqual(f"%%writefile /content/genai-lms-project-group4/tools/generate_audio.py\n{script}\n", cells[3][1])
        self.assertIn("--provider acestep --candidates 2 --manifest /content/genai-lms-project-group4/audio/"
                      "audio_cues.json --out /content/genai-lms-project-group4/baselines/20261127-1300-audio-acestep "
                      "--only trial", code)

    def test_colab_cells_for_stable_audio(self):
        cells = ops.colab_cells("{}", ["dice_roll", "door_open"], 3, "20261127-2330-audio-stable-audio",
                                url="https://github.com/x/genai-lms-project-group4.git", branch="audio",
                                provider="stable-audio", script_text="# script")
        self.assertEqual(5, len(cells))
        self.assertIn("git clone --depth 1 https://github.com/Stability-AI/stable-audio-3", cells[0][1])
        compile(cells[1][1], "login_cell", "exec")
        self.assertIn('userdata.get("HF_TOKEN")', cells[1][1])
        self.assertIn("notebook_login()", cells[1][1])
        self.assertIn("cd /content/stable-audio-3 && MPLBACKEND=Agg uv run python "
                      "/content/genai-lms-project-group4/tools/generate_audio.py generate --provider stable-audio "
                      "--candidates 3", cells[4][1])
        self.assertIn("--only dice_roll door_open", cells[4][1])
        self.assertIn("MyDrive/audio_runs/20261127-2330-audio-stable-audio.zip", cells[4][1])
        with self.assertRaises(ValueError):
            ops.colab_cells("{}", [], 1, "r", url="u/r.git", branch="b", provider="mock", script_text="")


@unittest.skipUnless(DEPS, "needs requirements-audio.txt")
class StableAudioProviderTests(unittest.TestCase):
    class FakeSA3:
        """Stands in for stable_audio_3.StableAudioModel: (batch, channels, samples) float32, a bit too long."""

        def __init__(self, sr=44100, fail=None):
            self.model = type("M", (), {"sample_rate": sr})()
            self.calls, self.fail = [], fail

        def generate(self, **kw):
            if self.fail:
                raise RuntimeError(self.fail)
            self.calls.append(kw)
            n = int((kw["duration"] + 0.3) * self.model.sample_rate)
            t = np.arange(n) / self.model.sample_rate
            x = 1.5 * np.sin(2 * np.pi * 440 * t)  # over full scale: must be clipped, not wrapped
            return np.stack([x, 0.5 * x])[None].astype("float32")

    def test_generates_a_stereo_wav_of_the_requested_length_and_records_the_seed(self):
        import io
        import wave
        fake = self.FakeSA3()
        p = ga.StableAudioProvider(model=fake, rng=lambda a, b: 1234)
        data = p.generate(ga.Cue("dice_roll", "sfx", "x", 1.5, False), "A die rolls.")
        with wave.open(io.BytesIO(data)) as w:
            self.assertEqual((2, 2, 44100, int(1.5 * 44100)),
                             (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()))
            pcm = np.frombuffer(w.readframes(w.getnframes()), "<i2")
        self.assertEqual(32767, int(pcm.max()))
        self.assertEqual({"prompt": "A die rolls.", "duration": 1.5, "seed": 1234, "steps": 8, "cfg_scale": 1.0},
                         fake.calls[0])
        self.assertEqual(1234, p.last_seed)
        self.assertIsNone(p.check())
        self.assertEqual(44100, p.settings()["sample_rate"])

    def test_run_generate_writes_a_normal_run(self):
        manifest, cues = ga.load_cues(ga.MANIFEST)
        seeds = iter([11, 22])
        p = ga.StableAudioProvider(model=self.FakeSA3(), rng=lambda a, b: next(seeds))
        with tempfile.TemporaryDirectory() as d:
            s = ga.run_generate(p, manifest, [c for c in cues if c.id == "door_open"], 2, Path(d))
            self.assertEqual((1.0, "stable-audio"), (s["success_rate"], s["provider"]))
            self.assertEqual([11, 22], [r["seed"] for r in s["rows"]])
            self.assertTrue((Path(d) / "door_open_c02.wav").is_file())
            self.assertIn("Stability AI Community License", s["licence"])
            res = qc.analyze_run(Path(d), {"door_open": False})
            self.assertEqual("fail", res["door_open_c01.wav"].status)  # the fake clips: QC must catch it
            self.assertIn("clipping", {i.code for i in res["door_open_c01.wav"].issues})

    def test_gated_model_aborts_the_run(self):
        class Gated(ga.StableAudioProvider):
            def _load(self):
                raise ga.ProviderError("cannot load: 401 Client Error, gated repo", 401)
        manifest, cues = ga.load_cues(ga.MANIFEST)
        with tempfile.TemporaryDirectory() as d:
            s = ga.run_generate(Gated(), manifest, [c for c in cues if c.kind == "sfx"], 3, Path(d))
        self.assertEqual(1, s["runs"])
        self.assertIn("auth error 401", s["aborted"])

    def test_cli_accepts_the_provider_and_validates_limits(self):
        args = ga.parse_args(["generate", "--provider", "stable-audio", "--only", "dice_roll"])
        self.assertEqual("stable-audio", args.provider)
        self.assertIsInstance(ga.make_provider("stable-audio"), ga.StableAudioProvider)
        _, cues = ga.load_cues(ga.MANIFEST)
        self.assertEqual([], ga.validate_cues([c for c in cues if c.kind == "sfx"], "stable-audio"))


@unittest.skipUnless(DEPS and importlib.util.find_spec("streamlit"), "needs streamlit")
class UiStartTests(unittest.TestCase):
    def test_app_renders_every_tab_without_exceptions(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "tools" / "audio_studio.py"), default_timeout=60).run()
        self.assertEqual([], [e.value for e in at.exception])
        self.assertEqual(3, len(at.tabs))


if __name__ == "__main__":
    unittest.main()
