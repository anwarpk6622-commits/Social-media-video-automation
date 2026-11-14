"""Phase 5 tests: metadata rules, edit protection, frame scoring, thumbnails.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import publish_kit as pk  # noqa: E402

SCRIPT = """# Script
## [TITLES]
1. دبئی نیشنل ڈے کی تیاری
2. برج العرب کے پاس جھنڈے
## [HOOK]
دبئی، برج العرب کے پاس بہت سارے جھنڈے لگائے ہوئے ہیں۔
## [RECORDING SCRIPT]
دبئی، برج العرب کے پاس بہت سارے جھنڈے۔
## [SHORT VERSION]
مختصر
## [VISUAL AND SOUND CUES]
- x
## [DESCRIPTION]
ساحل پر جھنڈوں کا خوبصورت منظر۔
## [HASHTAGS]
#Dubai #UAENationalDay, #BurjAlArab #دبئی #dubai #اردو
"""


def _node_ok() -> bool:
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright');console.log('ok')"], capture_output=True, text=True)
    return r.stdout.strip() == "ok"


class TestTextRules(unittest.TestCase):
    def test_hashtags_normalised_and_deduplicated(self):
        tags = pk.normalize_hashtags("#Dubai #UAE National Day, #دبئی #dubai\n#اردو #2026 #a-b")
        self.assertEqual(tags, ["#Dubai", "#UAENationalDay", "#دبئی", "#اردو", "#ab"])

    def test_english_phrases_for_search(self):
        self.assertEqual(pk.english_phrases(["#UAENationalDay", "#BurjAlArab", "#دبئی"]),
                         ["UAE National Day", "Burj Al Arab"])

    def test_youtube_forbidden_chars_removed(self):
        self.assertNotIn("<", pk.clean("a <b> c"))
        self.assertNotIn(">", pk.clean("a <b> c"))

    def test_two_line_split_keeps_short_words_with_previous_line(self):
        self.assertEqual(pk.split_two_lines("دبئی نیشنل ڈے کی تیاری"), ("دبئی نیشنل ڈے کی", "تیاری"))
        self.assertEqual(pk.split_two_lines("دبئی نیشنل ڈے|کی تیاری"), ("دبئی نیشنل ڈے", "کی تیاری"))
        self.assertEqual(pk.split_two_lines("مختصر عنوان"), ("مختصر عنوان", ""))


class TestMetadata(unittest.TestCase):
    def setUp(self):
        self.info = {"titles": ["دبئی نیشنل ڈے کی تیاری", "دوسرا"], "hook": "ہک کی لائن۔", "description": "تفصیل۔",
                     "hashtags": pk.normalize_hashtags(["#Dubai", "#UAENationalDay", "#BurjAlArab", "#دبئی", "#اردو", "#Six"]),
                     "location": "برج العرب، دبئی", "cta": "سبسکرائب کریں۔", "follow": "فالو کریں۔"}

    def test_platform_rules(self):
        m = pk.build_metadata(self.info)
        self.assertTrue(m["youtube"]["title"].startswith("دبئی نیشنل ڈے کی تیاری"))
        self.assertIn("Dubai", m["youtube"]["title"])                     # English search keywords
        self.assertNotIn("#Shorts", m["youtube_shorts"]["title"])          # RTL-safe title
        self.assertIn("#Shorts", m["youtube_shorts"]["description"])
        self.assertLessEqual(len(m["tiktok"]["hashtags"]), 5)
        self.assertLessEqual(len(m["facebook_reels"]["hashtags"]), 5)
        keys = [t.replace(" ", "").lower() for t in m["youtube"]["tags"]]
        self.assertEqual(len(keys), len(set(keys)), "no duplicate tags like 'UAE National Day' + 'UAENationalDay'")
        checks = pk.validate(m)
        self.assertFalse([c for p in checks.values() for c in p if c["level"] == "error"])

    def test_title_choice(self):
        self.assertTrue(pk.build_metadata(self.info, title_index=1)["facebook_reels"]["title"].startswith("دوسرا"))

    def test_validation_catches_problems(self):
        m = pk.build_metadata(self.info)
        m["youtube"]["title"] = "ا" * 120 + " <b>"
        m["tiktok"]["caption"] = "ب" * 2300
        checks = pk.validate(m)
        yt_errors = [c["msg"] for c in checks["youtube"] if c["level"] == "error"]
        self.assertTrue(any("Title" in x for x in yt_errors))
        self.assertTrue(any("<" in x for x in yt_errors))
        self.assertTrue(any(c["level"] == "error" for c in checks["tiktok"]))


class TestProjectFlow(unittest.TestCase):
    def setUp(self):
        from pipeline.project import Project
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-test-"))
        self.p = Project.create("kit", base=self.tmp / "projects")
        (self.p.script_dir / "script.md").write_text(SCRIPT, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gather_uses_script(self):
        info = pk.gather(self.p)
        self.assertEqual(info["titles"][0], "دبئی نیشنل ڈے کی تیاری")
        self.assertEqual(info["hashtags"], ["#Dubai", "#UAENationalDay", "#BurjAlArab", "#دبئی", "#اردو"])

    def test_hand_edits_protected_refresh_and_force(self):
        res = pk.write_metadata(self.p)
        jf = res["dir"] / "metadata.json"
        self.assertTrue((res["dir"] / "metadata.md").exists())
        data = json.loads(jf.read_text(encoding="utf-8"))
        data["tiktok"]["caption"] = "میرا اپنا کیپشن #Dubai"
        jf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(FileExistsError):
            pk.write_metadata(self.p)
        pk.refresh_from_json(self.p)                                        # keeps the edit
        self.assertIn("میرا اپنا کیپشن", (res["dir"] / "metadata.md").read_text(encoding="utf-8"))
        pk.write_metadata(self.p)                                          # now allowed (hash updated)
        data["tiktok"]["caption"] = "دوبارہ"
        jf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        pk.write_metadata(self.p, force=True)
        self.assertEqual(len(list(res["dir"].glob("metadata.backup-*.json"))), 1)


class TestFrameScoring(unittest.TestCase):
    def test_sharp_beats_blurred_and_edge_intrusion_detected(self):
        import numpy as np
        rng = np.random.default_rng(1)
        sharp = rng.integers(0, 255, (160, 90, 3)).astype(float)
        blurred = np.full((160, 90, 3), 128.0)
        s1, s2 = pk.score_frame(sharp), pk.score_frame(blurred)
        self.assertGreater(s1["sharpness"], s2["sharpness"])
        arm = sharp.copy()
        arm[:, :20] = 60.0                                             # smooth dark object at the edge
        self.assertGreater(pk.score_frame(arm)["intrusion"], pk.score_frame(sharp)["intrusion"] + 0.5)


@unittest.skipUnless(shutil.which("ffmpeg") and _node_ok(), "ffmpeg / Node Playwright not available")
class TestThumbnails(unittest.TestCase):
    def test_thumbnails_from_plain_project_video(self):
        from pipeline.ffmpeg_tools import run_ffmpeg
        from pipeline.project import Project
        tmp = Path(tempfile.mkdtemp(prefix="thumb-test-"))
        try:
            vid = tmp / "v.mp4"
            run_ffmpeg(["-y", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=4", "-f", "lavfi", "-i", "sine=d=4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(vid)])
            p = Project.create("t", base=tmp / "projects")
            (p.script_dir / "script.md").write_text(SCRIPT, encoding="utf-8")
            p.add_recording(vid)
            info = pk.make_thumbnails(p)
            sizes = {k: tuple(v["size"]) for k, v in info["files"].items()}
            self.assertEqual(sizes, {"youtube": (1280, 720), "cover": (1080, 1920)})
            for v in info["files"].values():
                out = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                                                 v["file"]], capture_output=True, text=True).stdout)["streams"][0]
                self.assertEqual((out["width"], out["height"]), tuple(v["size"]))
                self.assertLessEqual(v["bytes"], 2_000_000)
            self.assertTrue(Path(info["candidates_sheet"]).exists())
            info2 = pk.make_thumbnails(p, time=1.0, text="اپنا|عنوان")
            self.assertEqual(info2["time"], 1.0)
            self.assertFalse(info2["auto"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
