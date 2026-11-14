"""Phase 3 tests: Urdu text, alignment, cues, SRT, edit-protection, rendering.

Run:  python -m unittest discover -s tests -v
Whisper itself is not run here (slow + needs the model); set RUN_WHISPER_TESTS=1 to include it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import subtitles as st  # noqa: E402
from pipeline.config import load_settings  # noqa: E402
from pipeline.urdu_text import normalize, tokenize_script  # noqa: E402

CFG = load_settings()["subtitles"]


def W(text, start, end, prob=0.9):
    return {"text": text, "start": start, "end": end, "prob": prob}


def _node_playwright_ok() -> bool:
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright');console.log('ok')"], capture_output=True, text=True)
    return r.stdout.strip() == "ok"


class TestUrduText(unittest.TestCase):
    def test_normalize_spelling_variants(self):
        self.assertEqual(normalize("كيا"), normalize("کیا"))          # Arabic kaf/yeh vs Urdu
        self.assertEqual(normalize("آپ"), normalize("اپ"))            # madda dropped by ASR
        self.assertEqual(normalize("ہے؟"), normalize("ہے"))           # punctuation
        self.assertEqual(normalize("‏سلام‏"), normalize("سلام"))  # direction marks

    def test_tokenize_removes_notes_and_keeps_punctuation(self):
        toks = tokenize_script("السلام علیکم! [PAUSE] آج [CHECK: date] ہم ۔")
        self.assertEqual(toks, ["السلام", "علیکم!", "آج", "ہم۔"])


class TestAlign(unittest.TestCase):
    def test_text_from_script_timing_from_speech(self):
        script = tokenize_script("آپ کا فون ہی آپ کا اسٹوڈیو ہے")
        asr = [W("اپ", 0, .3), W("کا", .3, .5), W("فون", .5, .9), W("کی", .9, 1.1),
               W("اپ", 1.1, 1.3), W("کار", 1.3, 1.5), W("اسٹوڈیو", 1.5, 2.2), W("ہے", 2.2, 2.4)]
        al = st.align(script, asr)
        self.assertEqual([w["text"] for w in al["words"]], script)          # spelling = script
        self.assertEqual(al["words"][3]["start"], 0.9)                     # ہی took کی's time
        self.assertEqual(al["words"][3]["source"], "fitted")
        self.assertGreater(al["match_rate"], 0.6)

    def test_extra_spoken_words_are_kept_and_flagged(self):
        al = st.align(["آج", "ہم"], [W("آج", 0, .4), W("تو", .4, .6), W("ہم", .6, 1)])
        extra = [w for w in al["words"] if w["source"] == "extra"]
        self.assertEqual([w["text"] for w in extra], ["تو"])
        self.assertTrue(extra[0]["check"])

    def test_unheard_script_words_guessed_or_skipped(self):
        src = lambda al: {w["text"]: w["source"] for w in al["words"]}  # noqa: E731
        # silent stretch of 1.0s → Whisper missed them: guessed + flagged
        al = st.align(["ایک", "دو", "تین", "چار"], [W("ایک", 0, .5), W("چار", 1.5, 2)])
        self.assertEqual(src(al), {"ایک": "matched", "دو": "guessed", "تین": "guessed", "چار": "matched"})
        # no time between → speaker skipped them: not shown in subtitles
        al = st.align(["ایک", "دو", "تین", "چار"], [W("ایک", 0, .5), W("چار", .52, 1)])
        self.assertEqual(src(al), {"ایک": "matched", "دو": "skipped", "تین": "skipped", "چار": "matched"})


class TestAlignRegressions(unittest.TestCase):
    """Problems found in the full 50-second test (2026-11-14)."""

    def _say(self, text, start, step=0.4, garble=None):
        out, t = [], start
        for k, w in enumerate(text.split()):
            out.append(W(garble[k] if garble else w, round(t, 2), round(t + step - .05, 2)))
            t += step
        return out, t

    def test_one_wrong_common_word_does_not_shift_the_timeline(self):
        # Sentence 2 is badly mis-heard; «فون» exists in sentence 2 (script) AND 3 (speech).
        s1, t = self._say("پہلا قدم روشنی ہے۔", 0)
        s2, t = self._say("فون کو منہ سے قریب رکھیں۔", t + 1, garble=["مانٹو", "مون", "سی", "توہا", "گریب", "راکھے"])
        s3, _ = self._say("تیسرا قدم یہ ہے کہ فون کو سیدھا رکھیں۔", t + 1)
        script = tokenize_script("پہلا قدم روشنی ہے۔ فون کو منہ سے قریب رکھیں۔ تیسرا قدم یہ ہے کہ فون کو سیدھا رکھیں۔")
        al = st.align(script, s1 + s2 + s3)
        first_of_2 = next(w for w in al["words"] if w["text"] == "فون")
        self.assertAlmostEqual(first_of_2["start"], s2[0]["start"], delta=0.3)
        third = next(w for w in al["words"] if w["text"] == "تیسرا")
        self.assertAlmostEqual(third["start"], s3[0]["start"], delta=0.3)

    def test_skipped_phrase_is_exactly_detected(self):
        a, t = self._say("فون کو قریب رکھیں", 0)
        b, _ = self._say("تیسرا قدم یہ ہے", t + 0.3)
        script = tokenize_script("فون کو قریب رکھیں اور پنکھا بند کر دیں۔ تیسرا قدم یہ ہے")
        al = st.align(script, a + b)
        skipped = [w["text"] for w in al["words"] if w["source"] == "skipped"]
        self.assertEqual(skipped, ["اور", "پنکھا", "بند", "کر", "دیں۔"])
        # the sentence ended inside the skipped part → subtitle breaks there
        cues = st.build_cues(al["words"], CFG["landscape"])
        self.assertEqual(cues[0]["text"], "فون کو قریب رکھیں")

    def test_confident_extra_word_shown_unclear_junk_hidden(self):
        asr = [W("السلام", 0, .5), W("دوستو", .5, 1, prob=.95), W("علیکم", 1, 1.5), W("مہ", 1.6, 1.7, prob=.2)]
        al = st.align(["السلام", "علیکم"], asr)
        shown = [w["text"] for w in al["words"] if w.get("start") is not None]
        self.assertIn("دوستو", shown)
        self.assertNotIn("مہ", shown)
        self.assertEqual([u["text"] for u in al["unclear"]], ["مہ"])

    def test_misheard_word_in_gap_is_fitted_not_skipped(self):
        # «چینل» heard as «ویڈیو» (low confidence): must still appear, at that time
        asr = [W("میرے", 0, .4), W("ویڈیو", .4, .9, prob=.3), W("میں", .9, 1.2), W("خوش", 1.2, 1.6)]
        al = st.align(tokenize_script("میرے چینل میں خوش"), asr)
        ch = next(w for w in al["words"] if w["text"] == "چینل")
        self.assertNotEqual(ch["source"], "skipped")
        self.assertAlmostEqual(ch["start"], .4, delta=0.15)

    def test_similar_sounds_score_higher(self):
        from pipeline.align import similarity
        self.assertGreater(similarity(normalize("شافہ"), normalize("صاف")), similarity(normalize("دن"), normalize("صاف")))
        self.assertEqual(similarity("فون", "فون"), 1.0)

    def test_without_script_uses_speech(self):
        al = st.align([], [W("سلام", 0, 1)])
        self.assertEqual(al["mode"], "speech-only")
        self.assertEqual(al["words"][0]["text"], "سلام")


class TestCues(unittest.TestCase):
    def _words(self, text, step=0.4):
        return [{"text": t, "start": round(i * step, 3), "end": round(i * step + step - .05, 3)}
                for i, t in enumerate(text.split())]

    def test_sentence_end_breaks_and_limits(self):
        cues = st.build_cues(self._words("پہلا قدم روشنی ہے۔ دوسرا قدم آواز ہے۔"), CFG["landscape"])
        self.assertEqual([c["text"] for c in cues], ["پہلا قدم روشنی ہے۔", "دوسرا قدم آواز ہے۔"])

    def test_no_line_starts_with_postposition(self):
        cues = st.build_cues(self._words("کیا آپ جانتے ہیں کہ آپ کا فون ہی آپ کا اسٹوڈیو ہے؟"), CFG["vertical"])
        for c in cues[1:]:
            self.assertFalse(st._is_glue(c["text"].split()[0]), c["text"])

    def test_sentence_end_not_left_alone(self):
        cues = st.build_cues(self._words("دوسرا قدم صاف آواز ہے۔"), CFG["vertical"])
        self.assertTrue(all(len(c["text"].split()) > 1 for c in cues), [c["text"] for c in cues])

    def test_long_pause_splits(self):
        ws = [{"text": "ایک", "start": 0, "end": .4}, {"text": "دو", "start": 2.0, "end": 2.4}]
        self.assertEqual(len(st.build_cues(ws, CFG["landscape"])), 2)

    def test_cues_never_overlap(self):
        cues = st.build_cues(self._words(" ".join(["لفظ"] * 40), 0.3), CFG["vertical"])
        for a, b in zip(cues, cues[1:]):
            self.assertLessEqual(a["end"], b["start"])


class TestSrtAndEdits(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sub-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_srt_roundtrip_with_rtl_marks(self):
        cues = [{"start": 0.62, "end": 3.12, "text": "السلام علیکم!"},
                {"start": 3661.5, "end": 3663, "text": "میرا YouTube چینل"}]
        st.write_srt(cues, self.tmp / "a.srt")
        raw = (self.tmp / "a.srt").read_text(encoding="utf-8")
        self.assertIn("00:00:00,620 --> 00:00:03,120", raw)
        self.assertIn("01:01:01,500 --> 01:01:03,000", raw)
        self.assertIn(st.RLM, raw)
        back = st.read_srt(self.tmp / "a.srt")
        self.assertEqual([c["text"] for c in back], [c["text"] for c in cues])

    def test_edited_cue_gets_even_word_timing(self):
        words = [{"text": "آج", "start": 0, "end": .5}, {"text": "ہم", "start": .5, "end": 1}]
        same = st.attach_word_times([{"start": 0, "end": 1, "text": "آج ہم"}], words)[0]["words"]
        self.assertEqual(same[1]["start"], .5)
        edited = st.attach_word_times([{"start": 0, "end": 1, "text": "آج ہم سب"}], words)[0]["words"]
        self.assertEqual(len(edited), 3)
        self.assertAlmostEqual(edited[-1]["end"], 1, places=3)

    def test_hand_edits_are_protected(self):
        transcript = {"model": "test", "audio": "x_clean.wav",
                      "words": [W("آج", 0, .5), W("ہم", .5, 1), W("سیکھیں", 1, 1.6), W("گے۔", 1.6, 2)]}
        sub = self.tmp / "subtitles"
        st.build_subtitles(sub, transcript, "آج ہم سیکھیں گے۔", CFG)
        srt = sub / "urdu.srt"
        srt.write_text(srt.read_text(encoding="utf-8").replace("آج", "کل"), encoding="utf-8")
        with self.assertRaises(FileExistsError):
            st.build_subtitles(sub, transcript, "آج ہم سیکھیں گے۔", CFG)
        st.build_subtitles(sub, transcript, "آج ہم سیکھیں گے۔", CFG, force=True)
        backups = list(sub.glob("urdu.backup-*.srt"))
        self.assertEqual(len(backups), 1)
        self.assertIn("کل", backups[0].read_text(encoding="utf-8"))

    def test_unrelated_recording_falls_back_to_speech(self):
        transcript = {"model": "t", "audio": "a.wav", "words": [W("بالکل", 0, .5), W("مختلف", .5, 1), W("بات", 1, 1.5)]}
        res = st.build_subtitles(self.tmp / "s", transcript, "آج ہم سیکھیں گے کہ ویڈیو کیسے بنائیں", CFG)
        self.assertEqual(res["report"]["mode"], "speech-only")
        self.assertIsNotNone(res["report"]["rejected_match_rate"])


class TestTimeline(unittest.TestCase):
    def test_word_highlight_states_cover_whole_audio(self):
        from pipeline.subtitle_render import _timeline
        cues = [{"start": 1, "end": 2, "text": "آج ہم",
                 "words": [{"text": "آج", "start": 1, "end": 1.5}, {"text": "ہم", "start": 1.5, "end": 1.9}]}]
        tl = _timeline(cues, 3, highlight=True)
        self.assertEqual(tl[0], ((), 0.0, 1))
        self.assertEqual([s[1] for s, _, _ in tl[1:3]], [0, 1])
        self.assertEqual(tl[-1], ((), 2, 3))
        for (_, _, e), (_, s, _) in zip(tl, tl[1:]):
            self.assertAlmostEqual(e, s)


@unittest.skipUnless(shutil.which("ffmpeg") and _node_playwright_ok(), "ffmpeg / Node Playwright not available")
class TestRenderVideo(unittest.TestCase):
    def test_vertical_video_with_subtitles(self):
        from pipeline.ffmpeg_tools import run_ffmpeg
        from pipeline.subtitle_render import make_subtitle_video
        tmp = Path(tempfile.mkdtemp(prefix="sub-vid-"))
        try:
            audio = tmp / "v.wav"
            run_ffmpeg(["-y", "-f", "lavfi", "-i", "sine=f=200:d=3", str(audio)])
            cues = [{"start": .5, "end": 2.5, "text": "آج ہم",
                     "words": [{"text": "آج", "start": .5, "end": 1.4}, {"text": "ہم", "start": 1.5, "end": 2.4}]}]
            out = make_subtitle_video(audio, cues, CFG["vertical"], tmp / "o.mp4", tmp / "w")
            info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                                              "-show_format", str(out)], capture_output=True, text=True).stdout)
            v = next(s for s in info["streams"] if s["codec_type"] == "video")
            self.assertEqual((v["width"], v["height"]), (1080, 1920))
            self.assertAlmostEqual(float(info["format"]["duration"]), 3.0, delta=0.15)
            self.assertEqual(len(list((tmp / "w").glob("*.png"))), 3)  # blank + 2 highlight states
            # subtitle pixels present at 1.0s (bright text over dark background)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(out), "-frames:v", "1",
                                  "-vf", "crop=1080:500:0:1000,format=gray", "-f", "rawvideo", "-"],
                                 capture_output=True).stdout
            self.assertGreater(sum(1 for b in raw if b > 200), 500)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(os.environ.get("RUN_WHISPER_TESTS") == "1", "set RUN_WHISPER_TESTS=1 (slow, needs model)")
class TestWhisper(unittest.TestCase):
    def test_transcribe_returns_timed_words(self):
        from pipeline.ffmpeg_tools import run_ffmpeg
        from pipeline.transcribe import transcribe
        tmp = Path(tempfile.mkdtemp(prefix="whisper-"))
        try:
            run_ffmpeg(["-y", "-f", "lavfi", "-i", "anoisesrc=d=2:amplitude=0.01", str(tmp / "a.wav")])
            data = transcribe(tmp / "a.wav", tmp / "t.json", model="small")
            self.assertIn("words", data)
            self.assertEqual(data["language"], "ur")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
