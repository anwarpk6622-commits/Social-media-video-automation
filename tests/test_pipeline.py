"""Automated tests for Phase 1 + 2.

Run:  python -m unittest discover -s tests -v

- No internet, no API key, no money needed.
- The paid-API test uses a FAKE local server, so nothing is ever sent to Anthropic.
- Everything is created in a temporary folder and deleted afterwards.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import script_writer  # noqa: E402
from pipeline.ffmpeg_tools import run_ffmpeg  # noqa: E402
from pipeline.project import Project, sha256_of  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def make_test_voice(path: Path, seconds: int = 12) -> None:
    """Speech-like test signal: syllable-rate tone bursts + room noise, stereo."""
    run_ffmpeg([
        "-y",
        "-f", "lavfi", "-i", f"sine=f=180:d={seconds}",
        "-f", "lavfi", "-i", f"sine=f=4:d={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:amplitude=0.02:d={seconds}",
        "-filter_complex",
        "[1:a]volume=1[m];[0:a][m]amultiply,volume=0.3[v];[v][2:a]amix=inputs=2:normalize=0,"
        "pan=stereo|c0=c0|c1=c0",
        "-ar", "44100", str(path),
    ])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vid-test-"))

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            try:
                p.chmod(0o644)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class TestProjectAndOriginals(Base):
    def test_add_recording_is_copy_readonly_and_fingerprinted(self):
        src = self.tmp / "my voice.wav"
        make_test_voice(src, 3)
        before = sha256_of(src)
        p = Project.create("Pehla Video", "topic", base=self.tmp / "projects")
        entry = p.add_recording(src)
        self.assertTrue(src.exists(), "source must be copied, not moved")
        self.assertEqual(sha256_of(src), before)
        dest = p.original_dir / "my voice.wav"
        self.assertEqual(entry["sha256"], before)
        self.assertEqual(dest.stat().st_mode & 0o222, 0, "copy must be read-only")
        self.assertEqual(p.verify_originals(), [{"file": "my voice.wav", "status": "ok"}])

    def test_same_name_is_never_overwritten(self):
        src = self.tmp / "a.wav"
        make_test_voice(src, 2)
        p = Project.create("x", base=self.tmp / "projects")
        p.add_recording(src)
        with self.assertRaises(FileExistsError):
            p.add_recording(src)

    def test_tampering_is_detected(self):
        src = self.tmp / "a.wav"
        make_test_voice(src, 2)
        p = Project.create("x", base=self.tmp / "projects")
        p.add_recording(src)
        orig = p.original_dir / "a.wav"
        orig.chmod(0o644)
        with open(orig, "ab") as f:
            f.write(b"tamper")
        self.assertEqual(p.verify_originals()[0]["status"], "CHANGED")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class TestAudio(Base):
    def test_voice_processing_hits_target_and_keeps_original(self):
        from pipeline.audio import _measure, process_voice
        src = self.tmp / "voice.wav"
        make_test_voice(src, 12)
        p = Project.create("audio", base=self.tmp / "projects")
        entry = p.add_recording(src)
        rep = process_voice(p)
        master = p.processed_dir / rep["clean"]["file"]
        self.assertTrue(master.exists())
        self.assertTrue((p.processed_dir / rep["clean"]["preview_file"]).exists())
        self.assertEqual(rep["clean"]["channels"], 1)
        self.assertEqual(rep["clean"]["sample_rate"], 48000)
        # independent re-measure of the delivered file
        m = _measure(master)
        self.assertLessEqual(abs(float(m["input_i"]) - rep["settings"]["target_lufs"]), 1.0)
        self.assertLessEqual(float(m["input_tp"]), rep["settings"]["true_peak_db"] + 0.3)
        # original untouched
        self.assertEqual(sha256_of(p.original_dir / "voice.wav"), entry["sha256"])
        self.assertTrue(rep["original"]["unchanged"])

    def test_filter_chain_options(self):
        from pipeline.audio import build_filter_chain
        base = {"highpass_hz": 80, "noise_reduction": "off", "eq": False, "deesser": False,
                "compressor": False, "trim_silence": False}
        self.assertEqual(build_filter_chain(base), ["aformat=channel_layouts=mono", "highpass=f=80"])
        chain = build_filter_chain({**base, "noise_reduction": "strong", "trim_silence": True,
                                    "silence_threshold_db": -45, "max_silence_seconds": 0.8,
                                    "keep_silence_seconds": 0.35})
        self.assertTrue(chain[0].startswith("aformat"), "mono downmix must come first")
        self.assertTrue(any(c.startswith("silenceremove") for c in chain))
        self.assertIn("afftdn=nr=20:nf=-50:tn=1", chain)


SAMPLE = """# Script
## [TITLES]
1. عنوان
**HOOK**
کیا آپ جانتے ہیں؟
[RECORDING SCRIPT]
السلام علیکم! [PAUSE] آج ہم سیکھیں گے۔ [CHECK: date confirm karein]
### SHORT VERSION:
مختصر بات۔
## [VISUAL AND SOUND CUES]
- السلام → B-roll: phone
## [DESCRIPTION]
تفصیل
## [HASHTAGS]
#Urdu
"""


class TestScript(Base):
    def test_prompt_contains_all_sections_and_rules(self):
        req = script_writer.ScriptRequest("موضوع", 3, "aam log", "dostana", "subscribe")
        prompt = script_writer.build_prompt(req, 130)
        for name, _ in script_writer.SECTIONS:
            self.assertIn(f"## [{name}]", prompt)
        self.assertIn("390 Urdu words", prompt)
        self.assertIn("[CHECK", prompt)

    def test_tolerant_parser_and_check(self):
        f = self.tmp / "script.md"
        f.write_text(SAMPLE, encoding="utf-8")
        r = script_writer.check_script(f, 130)
        self.assertEqual(r["missing_sections"], [])
        self.assertEqual(r["pauses"], 1)
        self.assertEqual(r["facts_to_check"], ["date confirm karein"])
        self.assertTrue(r["has_urdu"])
        out = script_writer.export_reading_script(f, self.tmp / "read.txt")
        text = out.read_text(encoding="utf-8")
        self.assertNotIn("CHECK", text)
        self.assertNotIn("[PAUSE]", text)

    def test_free_mode_writes_prompt_and_never_overwrites_script(self):
        p = Project.create("s", base=self.tmp / "projects")
        req = script_writer.ScriptRequest("topic", 2, "a", "b", "c")
        res = script_writer.write_free_mode(p, req)
        self.assertTrue(res["prompt_file"].exists())
        res["script_file"].write_text(SAMPLE, encoding="utf-8")
        script_writer.write_free_mode(p, req)
        self.assertEqual(res["script_file"].read_text(encoding="utf-8"), SAMPLE)


class _FakeClaude(http.server.BaseHTTPRequestHandler):
    requests: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _FakeClaude.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
        reply = {
            "id": "msg_test", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": SAMPLE.split("\n", 1)[1]}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 900, "output_tokens": 3000},
        }
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


try:
    import anthropic  # noqa: F401
    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


@unittest.skipUnless(HAVE_SDK, "anthropic package not installed (optional)")
class TestPaidApiModeWithFakeServer(Base):
    def setUp(self):
        super().setUp()
        _FakeClaude.requests = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeClaude)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.env = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL")}
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
        os.environ["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.p = Project.create("api", base=self.tmp / "projects")
        self.req = script_writer.ScriptRequest("موضوع", 2, "a", "b", "c")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def test_saying_no_sends_nothing(self):
        res = script_writer.write_api_mode(self.p, self.req, input_fn=lambda _: "no")
        self.assertTrue(res["cancelled"])
        self.assertEqual(_FakeClaude.requests, [], "no request may be sent without 'yes'")

    def test_yes_sends_correct_request_and_logs_cost(self):
        res = script_writer.write_api_mode(self.p, self.req, input_fn=lambda _: "yes")
        self.assertEqual(len(_FakeClaude.requests), 1)
        sent = _FakeClaude.requests[0]
        self.assertEqual(sent["body"]["model"], "claude-opus-5-5")
        self.assertEqual(sent["body"]["fallbacks"], "default")
        self.assertEqual(sent["body"]["output_config"], {"effort": "medium"})
        self.assertIn("server-side-fallback-2026-07-01", sent["headers"].get("anthropic-beta", ""))
        r = script_writer.check_script(res["script_file"], 130)
        self.assertEqual(r["missing_sections"], [])
        # 900 in * $4/M + 3000 out * $20/M = 0.0036 + 0.06
        self.assertAlmostEqual(res["log"]["approx_cost_usd"], 0.0636, places=4)
        self.assertTrue((self.p.script_dir / "api_log.jsonl").exists())
        self.assertNotIn("test-key-not-real", (self.p.script_dir / "api_log.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
