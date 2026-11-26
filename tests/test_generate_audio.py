"""Tests for tools/generate_audio.py. Standard library only, no network.

Run: python -m unittest discover -s tests -p "test_*.py"
"""
from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import unittest
import urllib.error
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import generate_audio as ga  # noqa: E402


class FakeResponse:
    def __init__(self, body: bytes, ctype: str):
        self._body, self.headers = body, {"Content-Type": ctype}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int, body: bytes = b"{}", retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://x", code, "err", headers, io.BytesIO(body))


def scripted_opener(*outcomes):
    """Return an opener that raises or returns each outcome in turn, recording requests."""
    calls = []

    def opener(req, timeout):
        calls.append(req)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out
    opener.calls = calls
    return opener


AUDIO = b"ID3" + b"\x00" * 4000


class ManifestTests(unittest.TestCase):
    def test_repo_manifest_is_valid_for_every_provider(self):
        manifest, cues = ga.load_cues(ga.MANIFEST)
        self.assertEqual([], ga.validate_cues(cues, "mock"))
        music = [c for c in cues if c.kind == "music"]
        self.assertEqual([], ga.validate_cues(music, "acestep"))

    def test_music_ids_match_csharp_constants(self):
        src = (ROOT / "unity/Assets/Scripts/Core/MusicCues.cs").read_text(encoding="utf-8")
        csharp = set(re.findall(r'const string \w+ = "([a-z_]+)"', src))
        _, cues = ga.load_cues(ga.MANIFEST)
        self.assertEqual(csharp, {c.id for c in cues if c.kind == "music"})

    def test_sfx_ids_match_csharp_constants(self):
        src = (ROOT / "unity/Assets/Scripts/Audio/SfxPlayer.cs").read_text(encoding="utf-8")
        csharp = set(re.findall(r'const string \w+ = "([a-z_]+)"', src))
        _, cues = ga.load_cues(ga.MANIFEST)
        self.assertEqual(csharp, {c.id for c in cues if c.kind == "sfx"})

    def test_validation_reports_duplicates_ranges_and_bpm(self):
        cues = [ga.Cue("a", "music", "p", 5.0, True, bpm=400), ga.Cue("a", "sfx", " ", 40.0, False)]
        errors = ga.validate_cues(cues, "mock")
        self.assertTrue(any("duplicate" in e for e in errors))
        self.assertTrue(any("empty prompt" in e for e in errors))
        self.assertTrue(any("bpm 400" in e for e in errors))
        self.assertTrue(any("40.0s outside" in e for e in errors))
        self.assertTrue(any("5.0s outside acestep" in e for e in ga.validate_cues(cues[:1], "acestep")))

    def test_missing_field_raises_value_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "cues.json"
            p.write_text(json.dumps({"music": [{"id": "x", "prompt": "p"}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                ga.load_cues(p)

    def test_prompt_adds_style_tempo_key_and_loop_rules(self):
        m = {"music_style": "STYLE.", "loop_rules": "LOOP."}
        prompt = ga.build_prompt(m, ga.Cue("t", "music", "Tense.", 30, True, bpm=120, key="E minor"))
        self.assertEqual("STYLE. Tense. 120 BPM. Key of E minor. LOOP.", prompt)
        self.assertNotIn("LOOP", ga.build_prompt(m, ga.Cue("v", "music", "Win.", 10, False)))
        self.assertEqual("Beep.", ga.build_prompt(m, ga.Cue("b", "sfx", " Beep. ", 1, False)))


class HttpTests(unittest.TestCase):
    def test_retries_rate_limit_then_succeeds(self):
        waits = []
        opener = scripted_opener(http_error(429, retry_after="7"), FakeResponse(AUDIO, "audio/mpeg"))
        body, ctype = ga.http_request("https://x", opener=opener, sleep=waits.append)
        self.assertEqual((AUDIO, "audio/mpeg"), (body, ctype))
        self.assertEqual([7.0], waits)

    def test_client_error_is_not_retried(self):
        opener = scripted_opener(http_error(401, b'{"detail":"invalid key"}'))
        with self.assertRaises(ga.ProviderError) as ctx:
            ga.http_request("https://x", opener=opener, sleep=lambda s: None)
        self.assertEqual(401, ctx.exception.status)
        self.assertIn("invalid key", str(ctx.exception))
        self.assertEqual(1, len(opener.calls))

    def test_gives_up_after_max_attempts(self):
        opener = scripted_opener(*[http_error(503)] * ga.MAX_ATTEMPTS)
        with self.assertRaises(ga.ProviderError) as ctx:
            ga.http_request("https://x", opener=opener, sleep=lambda s: None)
        self.assertEqual(503, ctx.exception.status)
        self.assertEqual(ga.MAX_ATTEMPTS, len(opener.calls))

    def test_network_error_is_retried(self):
        opener = scripted_opener(urllib.error.URLError("reset"), FakeResponse(AUDIO, "audio/mpeg"))
        self.assertEqual(AUDIO, ga.http_request("https://x", opener=opener, sleep=lambda s: None)[0])

    def test_persistent_network_error_raises_network_error(self):
        opener = scripted_opener(*[urllib.error.URLError("refused")] * ga.MAX_ATTEMPTS)
        with self.assertRaises(ga.NetworkError):
            ga.http_request("https://x", opener=opener, sleep=lambda s: None)


class ProviderTests(unittest.TestCase):
    def test_json_instead_of_audio_is_an_error(self):
        with self.assertRaises(ga.ProviderError):
            ga._expect_audio(b'{"error":"busy"}', "application/json", "ACE-Step")

    def test_acestep_submits_polls_and_downloads(self):
        def env(data):
            return json.dumps({"code": 200, "error": None, "data": data}).encode(), "application/json"
        result = json.dumps([{"file": "/v1/audio?path=%2Ftmp%2Fa.mp3"}])
        replies = [env({"task_id": "t1", "status": "queued"}),
                   env([{"task_id": "t1", "status": 0, "result": ""}]),
                   env([{"task_id": "t1", "status": 1, "result": result}]),
                   (AUDIO, "audio/mpeg")]
        calls = []

        def http(url, **kw):
            calls.append((url, kw.get("body")))
            return replies[len(calls) - 1]
        p = ga.AceStepProvider("http://gpu:8001/", http=http, sleep=lambda s: None)
        audio = p.generate(ga.Cue("trial", "music", "x", 75, True, bpm=128, key="E minor"), "PROMPT")
        self.assertEqual(AUDIO, audio)
        self.assertEqual("http://gpu:8001/release_task", calls[0][0])
        self.assertEqual({"prompt": "PROMPT", "lyrics": "[Instrumental]", "audio_duration": 75,
                          "audio_format": "mp3", "bpm": 128, "key_scale": "E minor"}, calls[0][1])
        self.assertEqual({"task_id_list": ["t1"]}, calls[1][1])
        self.assertEqual("http://gpu:8001/v1/audio?path=%2Ftmp%2Fa.mp3", calls[3][0])

    def test_acestep_failed_task_and_timeout(self):
        def env(data):
            return json.dumps({"code": 200, "error": None, "data": data}).encode(), "application/json"
        failing = iter([env({"task_id": "t"}), env([{"task_id": "t", "status": 2, "result": "OOM"}])])
        p = ga.AceStepProvider("http://h", http=lambda u, **k: next(failing), sleep=lambda s: None)
        with self.assertRaisesRegex(ga.ProviderError, "failed: OOM"):
            p.generate(ga.Cue("a", "music", "x", 30, True), "p")

        clock = iter(range(0, 10_000, 500))
        running = lambda u, **k: env({"task_id": "t"}) if u.endswith("release_task") else env([{"status": 0}])  # noqa: E731
        p = ga.AceStepProvider("http://h", task_timeout_s=900, http=running, sleep=lambda s: None,
                               clock=lambda: next(clock))
        with self.assertRaisesRegex(ga.ProviderError, "still running"):
            p.generate(ga.Cue("a", "music", "x", 30, True), "p")

    def test_mock_writes_a_wav_of_the_requested_length(self):
        data = ga.MockProvider().generate(ga.Cue("a", "sfx", "x", 1.5, False), "p")
        with wave.open(io.BytesIO(data)) as w:
            self.assertAlmostEqual(1.5, w.getnframes() / w.getframerate(), places=2)


class PipelineTests(unittest.TestCase):
    def test_generate_then_promote_with_mock(self):
        manifest, cues = ga.load_cues(ga.MANIFEST)
        picked = [c for c in cues if c.id in ("victory", "dice_roll")]
        with tempfile.TemporaryDirectory() as d:
            run = Path(d) / "run"
            summary = ga.run_generate(ga.MockProvider(), manifest, picked, 2, run)
            self.assertEqual(1.0, summary["success_rate"])
            self.assertEqual({"victory": 2, "dice_roll": 2}, summary["ok_per_cue"])
            self.assertTrue((run / "victory_c02.wav").is_file())

            audio, prov_path = Path(d) / "Audio", Path(d) / "prov.json"
            common = ["--unity-audio", str(audio), "--provenance", str(prov_path)]
            args = ga.parse_args(["promote", "victory", "--run", str(run), "--take", "2", *common])
            self.assertEqual(0, args.func(args))
            self.assertTrue((audio / "Music" / "victory.wav").is_file())
            prov = json.loads(prov_path.read_text(encoding="utf-8"))
            self.assertEqual("mock", prov["victory"]["provider"])
            self.assertIn("test tone", prov["victory"]["licence"])

            for bad in (["promote", "victory", "--run", str(run), "--take", "9", *common],
                        ["promote", "victory", "--run", str(run), *common],
                        ["promote", "nope", "--run", str(run), "--take", "1", *common]):
                a = ga.parse_args(bad)
                self.assertEqual(2, a.func(a), bad)

    def test_promote_external_file_needs_source_and_licence(self):
        with tempfile.TemporaryDirectory() as d:
            ext = Path(d) / "dice.wav"
            ext.write_bytes(ga.MockProvider().generate(ga.Cue("dice_roll", "sfx", "x", 1, False), "p"))
            audio, prov_path = Path(d) / "Audio", Path(d) / "prov.json"
            common = ["--unity-audio", str(audio), "--provenance", str(prov_path)]

            a = ga.parse_args(["promote", "dice_roll", "--file", str(ext), *common])
            self.assertEqual(2, a.func(a))

            flac = Path(d) / "dice.flac"
            flac.write_bytes(b"fLaC")
            a = ga.parse_args(["promote", "dice_roll", "--file", str(flac), "--source", "x", "--licence", "CC0", *common])
            self.assertEqual(2, a.func(a))

            a = ga.parse_args(["promote", "dice_roll", "--file", str(ext), "--source", "Stable Audio 3 Small SFX",
                               "--licence", "Stability AI Community License", *common])
            self.assertEqual(0, a.func(a))
            self.assertTrue((audio / "SFX" / "dice_roll.wav").is_file())
            rec = json.loads(prov_path.read_text(encoding="utf-8"))["dice_roll"]
            self.assertEqual(("external", "Stability AI Community License"), (rec["provider"], rec["licence"]))

    def test_auth_error_aborts_the_run(self):
        class Unauthorized:
            name, kinds, extension, licence = "fake", frozenset({"music"}), "mp3", "n/a"

            def settings(self):
                return {}

            def generate(self, cue, prompt):
                raise ga.ProviderError("HTTP 401", 401)
        manifest, cues = ga.load_cues(ga.MANIFEST)
        with tempfile.TemporaryDirectory() as d:
            summary = ga.run_generate(Unauthorized(), manifest, [c for c in cues if c.kind == "music"], 3, Path(d))
        self.assertEqual(1, summary["runs"])
        self.assertIn("auth error 401", summary["aborted"])

    def test_unreachable_provider_aborts_the_run(self):
        class Down:
            name, kinds, extension, licence = "fake", frozenset({"music"}), "mp3", "n/a"

            def settings(self):
                return {}

            def generate(self, cue, prompt):
                raise ga.NetworkError("network error calling h: refused")
        manifest, cues = ga.load_cues(ga.MANIFEST)
        with tempfile.TemporaryDirectory() as d:
            summary = ga.run_generate(Down(), manifest, [c for c in cues if c.kind == "music"], 3, Path(d))
        self.assertEqual(1, summary["runs"])
        self.assertIn("unreachable", summary["aborted"])


if __name__ == "__main__":
    unittest.main()
