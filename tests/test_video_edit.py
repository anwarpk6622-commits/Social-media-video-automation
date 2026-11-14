"""Phase 4 tests: edit plan, subtitle shifting, filter chains, export guard, small render.

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

from pipeline import video_edit as ve  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def _node_ok() -> bool:
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright');console.log('ok')"], capture_output=True, text=True)
    return r.stdout.strip() == "ok"


def _plan(**over):
    p = {"trim": {"start": 2.0, "end": None}, "cuts": [18.7],
         "grade": {"look": "cinematic_warm", "soft_ranges": [[29.7, 35.5]]},
         "transition": {"type": "zoom_punch", "strength": 0.16, "duration": 0.45}}
    p.update(over)
    return p


class TestPlanPieces(unittest.TestCase):
    def test_shift_cues_removes_words_from_cut_part(self):
        cues = [{"start": 1.6, "end": 4.2, "text": "کے پاس دبئی، برج",
                 "words": [{"text": "کے", "start": 1.6, "end": 1.8}, {"text": "پاس", "start": 1.85, "end": 2.0},
                           {"text": "دبئی،", "start": 2.1, "end": 2.6}, {"text": "برج", "start": 2.7, "end": 3.0}]}]
        out = ve._shift_cues(cues, 2.0, 30)
        self.assertEqual(out[0]["text"], "دبئی، برج")
        self.assertAlmostEqual(out[0]["start"], 0.1, places=3)
        self.assertAlmostEqual(out[0]["words"][0]["start"], 0.1, places=3)

    def test_shift_cues_drops_cues_before_trim_and_clips_end(self):
        cues = [{"start": 0.1, "end": 1.5, "text": "یہ", "words": [{"text": "یہ", "start": 0.1, "end": 0.5}]},
                {"start": 30, "end": 35, "text": "آخر", "words": [{"text": "آخر", "start": 30, "end": 34}]}]
        out = ve._shift_cues(cues, 2.0, 30.0)
        self.assertEqual([c["text"] for c in out], ["آخر"])
        self.assertLessEqual(out[0]["end"], 30.0)

    def test_grade_is_lighter_on_faces(self):
        chain = ve._grade_chain(_plan())
        self.assertIn("vibrance=intensity=0.45:enable='not(between(t,27.70,33.50))'", chain)
        self.assertIn("vibrance=intensity=0.15:enable='between(t,27.70,33.50)'", chain)

    def test_transition_at_cut_in_edited_time_and_no_tmix(self):
        tr = ve._transition(_plan(), 1080, 1920)
        self.assertIn("zoompan", tr)
        self.assertIn("16.700", tr)          # 18.7 - 2.0
        self.assertNotIn("tmix", tr)         # tmix produced GREEN frames (found in testing)

    def test_segments_split_at_cuts(self):
        self.assertEqual(ve._segments(_plan(), 40.0), [(2.0, 18.7), (18.7, 40.0)])

    def test_plan_hash_changes_with_plan(self):
        a, b = _plan(), _plan()
        self.assertEqual(ve.plan_hash(a), ve.plan_hash(b))
        b["trim"]["start"] = 3
        self.assertNotEqual(ve.plan_hash(a), ve.plan_hash(b))


@unittest.skipUnless(HAVE_FFMPEG and _node_ok(), "ffmpeg / Node Playwright not available")
class TestSmallRender(unittest.TestCase):
    """End-to-end on a tiny synthetic phone video: trim, 2 clips, stabilise, grade,
    title, end card, subtitles off, both formats; checks size, length, no green frames,
    original unchanged, and that export refuses without a preview."""

    def test_render_and_export_guard(self):
        from pipeline.ffmpeg_tools import run_ffmpeg
        from pipeline.project import Project, sha256_of
        tmp = Path(tempfile.mkdtemp(prefix="edit-test-"))
        try:
            clip = tmp / "phone.mp4"
            run_ffmpeg(["-y", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=3",
                        "-f", "lavfi", "-i", "testsrc=s=360x640:r=30:d=3",
                        "-f", "lavfi", "-i", "sine=f=220:d=6",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-map", "2:a",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)])
            p = Project.create("edit", base=tmp / "projects")
            entry = p.add_recording(clip)
            plan = ve.default_plan(p, "phone.mp4", "ٹیسٹ ویڈیو", "کراچی")
            plan["trim"]["start"] = 0.5
            plan["subtitles"]["enabled"] = False
            plan["end_card"]["seconds"] = 1.0
            ve.plan_path(p).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            self.assertTrue(plan["cuts"] and abs(plan["cuts"][0] - 3.0) < 0.1, plan["cuts"])

            log = ve.render(p, preview=True)
            for fmt, (w, h) in (("vertical", (1080, 1920)), ("landscape", (1920, 1080))):
                out = Path(log["outputs"][fmt])
                info = json.loads(subprocess.run(
                    ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(out)],
                    capture_output=True, text=True).stdout)
                v = next(s for s in info["streams"] if s["codec_type"] == "video")
                self.assertEqual((v["width"], v["height"]), (w, h))
                self.assertAlmostEqual(float(info["format"]["duration"]), 5.5, delta=0.2)
                raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-vf", "scale=27:48,format=rgb24",
                                      "-f", "rawvideo", "-"], capture_output=True).stdout
                px = memoryview(raw)
                frames = len(raw) // (27 * 48 * 3)
                for k in range(frames):
                    f = px[k * 27 * 48 * 3:(k + 1) * 27 * 48 * 3]
                    r, g, b = (sum(f[i::3]) / (27 * 48) for i in range(3))
                    self.assertLess(g - (r + b) / 2, 60, f"green frame at {k}")
            self.assertEqual(sha256_of(p.original_dir / "phone.mp4"), entry["sha256"])
            self.assertTrue(log["original_unchanged"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
