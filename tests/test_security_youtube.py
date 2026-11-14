"""Security fixes + YouTube adapter tests — fully OFFLINE (every socket blocked).

Covers: HMAC approval signatures (invalid / forged / missing / other key), keyring
failure (fail closed), file changes DURING upload (incl. change-and-restore),
interrupted uploads, per-platform switches, hard-blocked Facebook/TikTok,
private-only, separate UPLOAD confirmation, and the YouTube resumable protocol
against an in-memory fake of the documented API behaviour.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from publishers import approval as ap  # noqa: E402
from publishers import models as md  # noqa: E402
from publishers.adapters import FakeAdapter  # noqa: E402
from publishers.fingerprint import sha256_file  # noqa: E402
from publishers.guard import HARD_BLOCKED, SAFE_DEFAULTS, load_config  # noqa: E402
from publishers.log import PublishLog  # noqa: E402
from publishers.plan import make_plan  # noqa: E402
from publishers.retry import FatalError, RetryPolicy  # noqa: E402
from publishers.runner import RunError, run_job  # noqa: E402
from publishers.secrets import MemoryStore  # noqa: E402
from publishers.signing import KEY_NAME, Signer, SigningUnavailable  # noqa: E402
from publishers.store import JobStore  # noqa: E402
from publishers.validate import validate_and_store  # noqa: E402
from publishers import youtube as yt  # noqa: E402

_real_connect, _real_create = socket.socket.connect, socket.create_connection


def _blocked(*a, **k):
    raise AssertionError("NETWORK CALL attempted during offline security tests!")


def setUpModule():
    socket.socket.connect = _blocked
    socket.create_connection = _blocked


def tearDownModule():
    socket.socket.connect = _real_connect
    socket.create_connection = _real_create


FAST = RetryPolicy(max_attempts=3, base_delay=0.0)
NO_SLEEP = dict(sleep=lambda s: None, rng=random.Random(1))
HAVE_FFMPEG = shutil.which("ffmpeg") is not None
LIVE_CFG = {"live_enabled": True, "platforms_live": {"youtube": True, "youtube_shorts": True,
                                                     "facebook_reels": True, "tiktok": True}, "private_only": True}
YCFG = {"category_id": "22", "language": "ur", "made_for_kids": False, "upload_thumbnail": True, "upload_captions": True}
FAKE_TOKEN = "ya29." + "Q" * 40          # built at runtime (secret scanner never sees a literal)
FAKE_REFRESH = "1//" + "R" * 40


class BrokenStore(MemoryStore):
    """A keyring that is locked / missing / broken."""

    def get(self, key):
        raise OSError("keyring locked")

    def set(self, key, value):
        raise OSError("keyring locked")


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_project(tmp: Path) -> Path:
    """Phase 1–5 shaped project with a ~1.5 MB video (several 256 KB chunks) + captions."""
    from pipeline.project import Project
    from pipeline.publish_kit import build_metadata
    from pipeline.subtitles import write_srt
    p = Project.create("sec", base=tmp / "projects").path
    (p / "output" / "thumbnails").mkdir(parents=True, exist_ok=True)
    for name, size in (("final_9x16.mp4", "540x960"), ("final_16x9.mp4", "960x540")):
        _ff("-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d=4", "-f", "lavfi", "-i", "sine=d=4",
            "-c:v", "libx264", "-b:v", "3M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p / "output" / name))
    _ff("-f", "lavfi", "-i", "color=c=red:s=1280x720", "-frames:v", "1", str(p / "output/thumbnails/youtube_thumbnail_1280x720.jpg"))
    _ff("-f", "lavfi", "-i", "color=c=blue:s=1080x1920", "-frames:v", "1", str(p / "output/thumbnails/cover_9x16_1080x1920.jpg"))
    info = {"titles": ["دبئی نیشنل ڈے کی تیاری"], "hook": "ہک۔", "description": "تفصیل۔", "hashtags": ["#Dubai", "#دبئی"],
            "location": "دبئی", "cta": "سبسکرائب کریں۔", "follow": "فالو کریں۔"}
    (p / "metadata").mkdir(exist_ok=True)
    (p / "metadata" / "metadata.json").write_text(json.dumps(build_metadata(info), ensure_ascii=False), encoding="utf-8")
    # captions on the ORIGINAL timeline + an edit that trimmed 1.0 s
    (p / "subtitles").mkdir(exist_ok=True)
    words = [{"text": "یہ", "start": 0.4, "end": 0.8}, {"text": "دبئی", "start": 1.5, "end": 2.0},
             {"text": "ہے۔", "start": 2.0, "end": 2.6}]
    cues = [{"start": 0.4, "end": 0.9, "text": "یہ"}, {"start": 1.5, "end": 2.6, "text": "دبئی ہے۔"}]
    for f in ("urdu.srt", "urdu_vertical.srt"):
        write_srt(cues, p / "subtitles" / f)
    (p / "subtitles" / "words.json").write_text(json.dumps({"words": words}, ensure_ascii=False), encoding="utf-8")
    (p / "edit.json").write_text(json.dumps({"trim": {"start": 1.0, "end": None}, "_source_duration": 5.0}), encoding="utf-8")
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sec-test-"))
        self.root = make_project(self.tmp)
        self.store = JobStore(self.root)
        self.signer = Signer(MemoryStore())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def approved(self, platform, privacy=None, extra=()):
        make_plan(self.root, [platform], privacy={platform: privacy} if privacy else None)
        validate_and_store(self.root, self.store, platform)
        answers = iter(["APPROVE", *extra])
        return ap.approve(self.root, self.store, platform, input_fn=lambda _: next(answers), signer=self.signer)

    def run_offline(self, jid, adapter, **k):
        return run_job(self.root, self.store, jid, adapter, simulate=False, policy=FAST, poll_interval=0,
                       signer=k.pop("signer", self.signer), **NO_SLEEP, **k)


# ====================================================================== FIX 1: signatures
@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class TestSignatures(Base):
    def test_approval_is_signed_and_key_never_stored_in_files(self):
        j = self.approved("tiktok")
        self.assertEqual(j.approval["alg"], "HMAC-SHA256")
        self.assertEqual(len(j.approval["signature"]), 64)
        key = self.signer.store.get(KEY_NAME)
        everything = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (self.root / "publish").rglob("*") if p.is_file())
        self.assertNotIn(key, everything)
        self.assertNotIn(key, str(self.signer.store) + repr(self.signer.store))

    def test_invalid_signature_is_rejected_and_revoked(self):
        self.approved("tiktok")
        jf = self.root / "publish/jobs/tiktok.json"
        j = json.loads(jf.read_text(encoding="utf-8"))
        j["approval"]["signature"] = "0" * 64
        jf.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        fa = FakeAdapter("tiktok")
        with self.assertRaises(RunError) as cm:
            self.run_offline("tiktok", fa)
        self.assertIn("dastakhat", str(cm.exception))
        self.assertEqual(fa.calls, 0)
        self.assertEqual(self.store.load("tiktok").status, md.PENDING)

    def test_forged_approval_with_matching_fingerprints_is_rejected(self):
        """Attacker swaps the video AND rewrites every fingerprint consistently — but has no key."""
        self.approved("tiktok")
        video = self.root / "output/final_9x16.mp4"
        with open(video, "ab") as f:
            f.write(b"evil")
        new = sha256_file(video)
        jf = self.root / "publish/jobs/tiktok.json"
        j = json.loads(jf.read_text(encoding="utf-8"))
        j["files"]["video"]["sha256"] = new
        j["files"]["video"]["bytes"] = video.stat().st_size
        j["approval"]["fingerprints"]["files"]["video"] = new
        jf.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        fa = FakeAdapter("tiktok")
        with self.assertRaises(RunError) as cm:
            self.run_offline("tiktok", fa)
        self.assertIn("dastakhat ghalat", str(cm.exception))
        self.assertEqual(fa.calls, 0)

    def test_unsigned_or_other_key_approval_rejected(self):
        self.approved("tiktok")
        with self.assertRaises(RunError):                               # signed by a different key
            self.run_offline("tiktok", FakeAdapter("tiktok"), signer=Signer(MemoryStore()))
        self.approved("youtube")
        jf = self.root / "publish/jobs/youtube.json"
        j = json.loads(jf.read_text(encoding="utf-8"))
        for k in ("signature", "key_id", "alg", "v"):
            j["approval"].pop(k)                                         # old, unsigned 6.1-style approval
        jf.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(RunError) as cm:
            self.run_offline("youtube", FakeAdapter("youtube"))
        self.assertIn("signature", str(cm.exception))

    def test_simulation_also_requires_valid_signature(self):
        self.approved("tiktok")
        jf = self.root / "publish/jobs/tiktok.json"
        j = json.loads(jf.read_text(encoding="utf-8"))
        j["approval"]["signature"] = "f" * 64
        jf.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(RunError):
            run_job(self.root, self.store, "tiktok", FakeAdapter("tiktok"), simulate=True, policy=FAST,
                    signer=self.signer, **NO_SLEEP)


# ====================================================================== keyring failure
@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class TestKeyringFailure(Base):
    def test_broken_keyring_blocks_approval_and_changes_nothing(self):
        make_plan(self.root, ["youtube"])
        validate_and_store(self.root, self.store, "youtube")
        asked = []
        with self.assertRaises(ap.ApprovalError):
            ap.approve(self.root, self.store, "youtube", input_fn=lambda p: asked.append(p) or "APPROVE",
                       signer=Signer(BrokenStore()))
        self.assertEqual(asked, [], "the user must not even be asked when signing is impossible")
        self.assertEqual(self.store.load("youtube").status, md.VALIDATED)
        self.assertIn("approval_blocked_keyring", [r["event"] for r in PublishLog(self.root).read()])

    def test_broken_keyring_at_run_stops_without_revoking(self):
        self.approved("youtube")
        fa = FakeAdapter("youtube")
        with self.assertRaises(RunError) as cm:
            self.run_offline("youtube", fa, signer=Signer(BrokenStore()))
        self.assertIn("Signing key", str(cm.exception))
        j = self.store.load("youtube")
        self.assertEqual((j.status, bool(j.approval), fa.calls), (md.APPROVED, True, 0))

    def test_real_keyring_without_secure_backend_fails_closed(self):
        try:
            import keyring
            from keyring.backends import fail
        except ImportError:
            self.skipTest("keyring not installed")
        from publishers.signing import get_signer
        old = keyring.get_keyring()
        keyring.set_keyring(fail.Keyring())
        try:
            with self.assertRaises(SigningUnavailable):
                get_signer()
        finally:
            keyring.set_keyring(old)


# ====================================================================== FIX 2: integrity during upload
@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class TestUploadIntegrity(Base):
    CH = 256 * 1024

    def _flip(self, offset):
        v = self.root / "output/final_9x16.mp4"
        with open(v, "r+b") as f:
            f.seek(offset)
            b = f.read(1)
            f.seek(offset)
            f.write(bytes([b[0] ^ 0xFF]))

    def test_file_changed_during_upload_aborts_before_finish(self):
        self.approved("tiktok")
        fa = FakeAdapter("tiktok", chunk_size=self.CH, on_chunk=lambda n: self._flip(3 * self.CH + 10) if n == 1 else None)
        j = self.run_offline("tiktok", fa)
        self.assertEqual(j.status, md.FAILED)
        self.assertEqual(fa.finished, 0, "finish() must never be called for changed data")
        self.assertIn("upload roka gaya", j.error["message"])

    def test_change_and_restore_during_upload_is_caught(self):
        """Bytes of chunk 3 are altered, sent, then restored — the file looks perfect at the end."""
        self.approved("tiktok")
        off = 2 * self.CH + 100

        def hook(n):
            if n in (2, 3):
                self._flip(off)               # n=2: corrupt before chunk 3 is read; n=3: restore after sending
        fa = FakeAdapter("tiktok", chunk_size=self.CH, on_chunk=hook)
        j = self.run_offline("tiktok", fa)
        self.assertEqual(sha256_file(self.root / "output/final_9x16.mp4"), j.approval["fingerprints"]["files"]["video"])
        self.assertEqual(j.status, md.FAILED)
        self.assertEqual(fa.finished, 0)
        self.assertIn("mukhtalif", j.error["message"])

    def test_interrupted_upload_resumes_and_covers_every_byte(self):
        self.approved("facebook_reels")
        size = (self.root / "output/final_9x16.mp4").stat().st_size
        fa = FakeAdapter("facebook_reels", chunk_size=self.CH, failures=[None, None, "crash"])
        with self.assertRaises(KeyboardInterrupt):
            self.run_offline("facebook_reels", fa)
        priv = json.loads((self.root / "publish/private/facebook_reels.json").read_text())
        self.assertEqual(len(priv["sent_ranges"]), 2)
        fa2 = FakeAdapter("facebook_reels", chunk_size=self.CH)
        j = self.run_offline("facebook_reels", fa2)
        self.assertEqual(j.status, md.COMPLETED)
        self.assertEqual(fa2.received_bytes, size)

    def test_file_changed_while_upload_was_interrupted_is_refused(self):
        self.approved("facebook_reels")
        with self.assertRaises(KeyboardInterrupt):
            self.run_offline("facebook_reels", FakeAdapter("facebook_reels", chunk_size=self.CH, failures=[None, "crash"]))
        self._flip(10)
        fa = FakeAdapter("facebook_reels", chunk_size=self.CH)
        with self.assertRaises(RunError):
            self.run_offline("facebook_reels", fa)
        self.assertEqual((fa.calls, self.store.load("facebook_reels").status), (0, md.PENDING))
        self.assertFalse((self.root / "publish/private/facebook_reels.json").exists(), "stale session must be deleted")

    def test_missing_progress_record_is_never_trusted(self):
        self.approved("tiktok")
        with self.assertRaises(KeyboardInterrupt):
            self.run_offline("tiktok", FakeAdapter("tiktok", chunk_size=self.CH, failures=[None, None, "crash"]))
        pf = self.root / "publish/private/tiktok.json"
        st = json.loads(pf.read_text())
        st["sent_ranges"] = st["sent_ranges"][1:]          # someone deleted the record of chunk 1
        pf.write_text(json.dumps(st))
        fa = FakeAdapter("tiktok", chunk_size=self.CH)
        j = self.run_offline("tiktok", fa)
        self.assertEqual(j.status, md.FAILED)
        self.assertEqual(fa.finished, 0)


# ====================================================================== FIX 3: switches / private-only
@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class TestSwitches(Base):
    def online(self, jid, cfg, *, settings_live=True, confirm=None, http=None):
        http = http or FakeYouTube(self.root)
        ad = yt.YouTubeAdapter(jid, self.root, http, YCFG) if jid.startswith("youtube") else _Online(jid)
        return ad, run_job(self.root, self.store, jid, ad, simulate=False, policy=FAST, poll_interval=0, signer=self.signer,
                           guard_cfg=cfg, settings_live=settings_live, confirm_fn=confirm, **NO_SLEEP)

    def test_repo_config_has_only_youtube_on_and_master_off(self):
        cfg = load_config()
        self.assertFalse(cfg["live_enabled"])
        self.assertEqual({k for k, v in cfg["platforms_live"].items() if v}, {"youtube", "youtube_shorts"})
        self.assertTrue(cfg["private_only"])
        self.assertEqual(set(HARD_BLOCKED), {"facebook_reels", "tiktok"})

    def test_missing_or_bad_config_means_everything_off(self):
        self.assertEqual(load_config(self.tmp / "nope.json"), SAFE_DEFAULTS)
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({"live_enabled": "true", "platforms_live": {"youtube": 1}, "private_only": 0}))
        c = load_config(bad)
        self.assertEqual((c["live_enabled"], c["platforms_live"]["youtube"], c["private_only"]), (False, False, True))

    def test_each_switch_blocks_on_its_own(self):
        self.approved("youtube")
        cases = [
            (dict(LIVE_CFG, live_enabled=False), True, "live_enabled"),
            (LIVE_CFG, False, "live_enabled"),                       # settings.json switch off
            (dict(LIVE_CFG, platforms_live=dict(LIVE_CFG["platforms_live"], youtube=False)), True, "youtube ka switch"),
        ]
        for cfg, settings_live, why in cases:
            http = FakeYouTube(self.root)
            with self.assertRaises(RunError) as cm:
                self.online("youtube", cfg, settings_live=settings_live, confirm=lambda _: "UPLOAD youtube", http=http)
            self.assertIn(why, str(cm.exception))
            self.assertEqual(http.calls, [], "no request may be sent when a switch is off")
            self.assertEqual(self.store.load("youtube").status, md.APPROVED)

    def test_facebook_and_tiktok_hard_blocked_even_if_all_switches_on(self):
        for jid in ("facebook_reels", "tiktok"):
            self.approved(jid)
            ad = _Online(jid)
            with self.assertRaises(RunError) as cm:
                run_job(self.root, self.store, jid, ad, simulate=False, signer=self.signer, guard_cfg=LIVE_CFG,
                        settings_live=True, confirm_fn=lambda _: f"UPLOAD {jid}", **NO_SLEEP)
            self.assertIn("manzoor nahi", str(cm.exception))
            self.assertEqual(ad.calls, 0)

    def test_private_only_refuses_unlisted_and_public(self):
        for priv in ("unlisted", "public"):
            self.approved("youtube", priv, extra=["PUBLIC"])
            http = FakeYouTube(self.root)
            with self.assertRaises(RunError) as cm:
                self.online("youtube", LIVE_CFG, confirm=lambda _: "UPLOAD youtube", http=http)
            self.assertIn("private_only", str(cm.exception))
            self.assertEqual(http.calls, [])

    def test_default_privacy_is_private(self):
        for j in (r["job"] for r in make_plan(self.root, ["youtube", "youtube_shorts"])):
            self.assertEqual(j.privacy, "private")

    def test_separate_upload_confirmation_required(self):
        self.approved("youtube")
        for confirm in (None, lambda _: "APPROVE", lambda _: "upload youtube", lambda _: "UPLOAD youtube_shorts"):
            http = FakeYouTube(self.root)
            with self.assertRaises(RunError):
                self.online("youtube", LIVE_CFG, confirm=confirm, http=http)
            self.assertEqual(http.calls, [])


class _Online(FakeAdapter):
    """A FakeAdapter that pretends to be online (to prove the guards fire first)."""
    offline = False

    def __init__(self, platform):
        super().__init__(platform)


# ====================================================================== YouTube adapter
class Resp:
    def __init__(self, code, headers=None, body=None):
        self.status_code, self.headers, self._body = code, headers or {}, body

    def json(self):
        return self._body or {}


class FakeYouTube:
    """In-memory YouTube following the documented resumable protocol."""

    def __init__(self, root, faults=None, polls=1, final_upload_status="processed", partial_at=None,
                 returned_privacy="SAME", poll_privacy="private"):
        self.root, self.faults, self.polls = root, dict(faults or {}), polls
        self.calls, self.sessions, self.received = [], 0, bytearray()
        self.init_body, self.thumb, self.caption_body, self.final = None, None, None, final_upload_status
        self.partial_at, self.put_n, self._get_n = partial_at, 0, 0
        self.returned_privacy, self.poll_privacy = returned_privacy, poll_privacy

    def request(self, method, url, params=None, headers=None, data=None, timeout=None):
        headers = headers or {}
        assert "Authorization" not in headers, "adapter must not handle tokens itself"
        self.calls.append((method, url.split("?")[0], dict(params or {}), {k: v for k, v in headers.items()}, len(data or b"")))
        if method == "POST" and url == yt.UPLOAD_URL:
            self.sessions += 1
            self.received = bytearray()
            self.init_body = json.loads(data.decode("utf-8"))
            self.total = int(headers["X-Upload-Content-Length"])
            return Resp(200, {"Location": f"https://www.googleapis.com/upload/youtube/v3/videos?upload_id=S{self.sessions}"})
        if method == "PUT" and "upload_id=" in url:
            if not url.endswith(f"S{self.sessions}"):
                return Resp(404)
            cr = headers["Content-Range"]
            if cr.startswith("bytes */"):
                n = len(self.received)
                return Resp(308, {"Range": f"bytes=0-{n - 1}"} if n else {})
            self.put_n += 1
            f = self.faults.pop(self.put_n, None)
            if f == 503:
                return Resp(503, {"Retry-After": "0"})
            if f == "quota":
                return Resp(403, body={"error": {"errors": [{"reason": "quotaExceeded"}]}})
            if f == 404:
                self.sessions += 1                       # old session forgotten
                return Resp(404)
            start, end, total = map(int, re.match(r"bytes (\d+)-(\d+)/(\d+)", cr).groups())
            assert start == len(self.received), (start, len(self.received))
            assert end - start + 1 == len(data)
            take = data if self.partial_at != self.put_n else data[: len(data) // 2]
            self.received += take
            if len(self.received) == total:
                rp = self.init_body["status"]["privacyStatus"] if self.returned_privacy == "SAME" else self.returned_privacy
                st = {"uploadStatus": "uploaded"}
                if rp is not None:
                    st["privacyStatus"] = rp
                return Resp(200, body={"id": "VID123", "status": st})
            return Resp(308, {"Range": f"bytes=0-{len(self.received) - 1}"})
        if method == "POST" and url == yt.THUMB_URL:
            self.thumb = (params, len(data))
            return Resp(200, body={"items": []})
        if method == "POST" and url == yt.CAPTIONS_URL:
            self.caption_body = data
            return Resp(200, body={"id": "CAP1"})
        if method == "GET" and url == yt.VIDEOS_URL and params.get("part") == "status":
            return Resp(200, body={"items": [{"status": {"privacyStatus": "private"}}]})
        if method == "GET" and url == yt.VIDEOS_URL:
            self._get_n += 1
            if self._get_n <= self.polls:
                return Resp(200, body={"items": [{"status": {"uploadStatus": "uploaded"},
                                                  "processingDetails": {"processingStatus": "processing"}}]})
            return Resp(200, body={"items": [{"status": {"uploadStatus": self.final, "privacyStatus": self.poll_privacy},
                                              "processingDetails": {"processingStatus": "succeeded" if self.final == "processed" else "failed"}}]})
        return Resp(400)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class TestYouTubeAdapter(Base):
    CH = 256 * 1024

    def live(self, jid="youtube", http=None, **k):
        http = http or FakeYouTube(self.root)
        ad = yt.YouTubeAdapter(jid, self.root, http, YCFG)
        ad.chunk_size = self.CH
        j = run_job(self.root, self.store, jid, ad, simulate=False, policy=FAST, poll_interval=0, signer=self.signer,
                    guard_cfg=LIVE_CFG, settings_live=True, confirm_fn=lambda _: f"UPLOAD {jid}", **NO_SLEEP, **k)
        return j, http

    def test_full_private_upload_follows_documented_protocol(self):
        self.approved("youtube")
        j, http = self.live()
        video = self.root / "output/final_16x9.mp4"
        self.assertEqual(j.status, md.COMPLETED)
        self.assertEqual(j.upload["remote_id"], "VID123")
        self.assertEqual(bytes(http.received), video.read_bytes())
        st = http.init_body["status"]
        self.assertEqual(st["privacyStatus"], "private")                         # always explicit
        self.assertNotIn("publishAt", st)
        self.assertEqual(http.init_body["snippet"]["defaultLanguage"], "ur")
        init = http.calls[0]
        self.assertEqual(init[2], {"uploadType": "resumable", "part": "snippet,status", "notifySubscribers": "false"})
        self.assertEqual(init[3]["X-Upload-Content-Length"], str(video.stat().st_size))
        puts = [c for c in http.calls if c[0] == "PUT"]
        for c in puts[:-1]:
            self.assertEqual(c[4] % (256 * 1024), 0, "every chunk but the last must be a multiple of 256 KB")
        self.assertEqual(http.thumb[0], {"videoId": "VID123", "uploadType": "media"})
        self.assertEqual(j.upload["extras"], {"thumbnail": "uploaded", "captions": "uploaded"})

    def test_captions_are_shifted_to_the_final_video_timeline(self):
        self.approved("youtube")
        j, http = self.live()
        body = http.caption_body.decode("utf-8")
        self.assertIn('"language": "ur"', body)
        self.assertIn('"videoId": "VID123"', body)
        self.assertIn("00:00:00,500 --> 00:00:01,600", body)        # 1.5 s − 1.0 s trim
        self.assertNotIn("یہ", body.split("\r\n\r\n", 2)[-1])        # the word in the cut part is gone

    def test_transient_503_is_retried(self):
        self.approved("youtube")
        j, http = self.live(http=FakeYouTube(self.root, faults={2: 503}))
        self.assertEqual(j.status, md.COMPLETED)
        self.assertGreaterEqual(j.upload.get("retries", 0), 1)

    def test_quota_exceeded_is_fatal_without_retry(self):
        self.approved("youtube")
        http = FakeYouTube(self.root, faults={1: "quota"})
        j, _ = self.live(http=http)
        self.assertEqual(j.status, md.FAILED)
        self.assertIn("quota", j.error["message"])
        self.assertEqual(len([c for c in http.calls if c[0] == "PUT"]), 1)

    def test_expired_session_restarts_from_zero_in_new_session(self):
        self.approved("youtube")
        http = FakeYouTube(self.root, faults={3: 404})
        j, _ = self.live(http=http)
        self.assertEqual(j.status, md.COMPLETED)
        self.assertEqual(len([c for c in http.calls if c[0] == "POST" and c[1] == yt.UPLOAD_URL]), 2)
        self.assertEqual(bytes(http.received), (self.root / "output/final_16x9.mp4").read_bytes())
        self.assertIn("upload_restarted", [r["event"] for r in PublishLog(self.root).read("youtube")])

    def test_partial_chunk_confirmation_continues_correctly(self):
        self.approved("youtube")
        j, http = self.live(http=FakeYouTube(self.root, partial_at=2))
        self.assertEqual(j.status, md.COMPLETED)
        self.assertEqual(bytes(http.received), (self.root / "output/final_16x9.mp4").read_bytes())

    def test_resume_after_crash_asks_server_offset(self):
        self.approved("youtube")
        http = FakeYouTube(self.root)
        ad = yt.YouTubeAdapter("youtube", self.root, http, YCFG)
        ad.chunk_size = self.CH
        real_send = ad.send_chunk
        n = {"c": 0}

        def crashing(*a):
            n["c"] += 1
            if n["c"] == 3:
                raise KeyboardInterrupt
            return real_send(*a)
        ad.send_chunk = crashing
        with self.assertRaises(KeyboardInterrupt):
            run_job(self.root, self.store, "youtube", ad, simulate=False, policy=FAST, signer=self.signer, guard_cfg=LIVE_CFG,
                    settings_live=True, confirm_fn=lambda _: "UPLOAD youtube", **NO_SLEEP)
        ad.send_chunk = real_send
        j = run_job(self.root, self.store, "youtube", ad, simulate=False, policy=FAST, poll_interval=0, signer=self.signer,
                    guard_cfg=LIVE_CFG, settings_live=True, confirm_fn=lambda _: "UPLOAD youtube", **NO_SLEEP)
        self.assertEqual(j.status, md.COMPLETED)
        self.assertTrue(any(c[0] == "PUT" and c[3].get("Content-Range", "").startswith("bytes */") for c in http.calls))
        self.assertEqual(http.sessions, 1, "resume must reuse the session, not start a new one")

    def test_rejected_video_marks_job_failed(self):
        self.approved("youtube")
        j, _ = self.live(http=FakeYouTube(self.root, final_upload_status="rejected"))
        self.assertEqual(j.status, md.FAILED)

    def test_adapter_itself_refuses_public_and_schedule_without_confirmation(self):
        make_plan(self.root, ["youtube"])
        job = self.store.load("youtube")
        ad = yt.YouTubeAdapter("youtube", self.root, FakeYouTube(self.root), YCFG)
        self.assertEqual(ad.video_body(job)["status"]["privacyStatus"], "private")
        job.privacy = "public"
        with self.assertRaises(FatalError):
            ad.video_body(job)
        job.privacy, job.schedule = "private", "2099-01-01T10:00"
        with self.assertRaises(FatalError):                       # publishAt would make it public later
            ad.video_body(job)

    def test_returned_public_privacy_stops_everything(self):
        self.approved("youtube")
        j, http = self.live(http=FakeYouTube(self.root, returned_privacy="public"))
        self.assertEqual(j.status, md.FAILED)
        self.assertIn("KHATRA", j.error["message"])
        self.assertIn("VID123", j.error["message"])                     # so the user can find it in Studio
        self.assertIsNone(http.thumb)
        self.assertIsNone(http.caption_body)

    def test_missing_returned_privacy_is_looked_up(self):
        self.approved("youtube")
        j, http = self.live(http=FakeYouTube(self.root, returned_privacy=None))
        self.assertEqual(j.status, md.COMPLETED)
        self.assertTrue(any(c[0] == "GET" and c[2].get("part") == "status" for c in http.calls))

    def test_privacy_change_during_processing_is_flagged(self):
        self.approved("youtube")
        j, _ = self.live(http=FakeYouTube(self.root, poll_privacy="unlisted"))
        self.assertEqual(j.status, md.FAILED)
        self.assertIn("private", j.error["message"])

    def test_adapter_refuses_non_private_even_with_public_confirmation(self):
        make_plan(self.root, ["youtube"])
        job = self.store.load("youtube")
        ad = yt.YouTubeAdapter("youtube", self.root, FakeYouTube(self.root), YCFG)
        job.approval = {"public_confirmed": True}
        for priv in ("public", "unlisted"):
            job.privacy = priv
            with self.assertRaises(FatalError):
                ad.video_body(job)
        job.privacy, job.schedule = "private", "2099-01-01T10:00"
        with self.assertRaises(FatalError):
            ad.video_body(job)

    def test_public_cannot_execute_even_if_private_only_turned_off(self):
        """Worst case: someone sets private_only=false AND gives public confirmation."""
        for priv in ("public", "unlisted"):
            self.approved("youtube", priv, extra=["PUBLIC"])
            http = FakeYouTube(self.root)
            cfg = dict(LIVE_CFG, private_only=False)
            ad = yt.YouTubeAdapter("youtube", self.root, http, YCFG)
            j = run_job(self.root, self.store, "youtube", ad, simulate=False, policy=FAST, poll_interval=0,
                        signer=self.signer, guard_cfg=cfg, settings_live=True,
                        confirm_fn=lambda _: "UPLOAD youtube", **NO_SLEEP)
            self.assertEqual(http.calls, [], f"{priv}: not a single request may reach YouTube")
            self.assertEqual(j.status, md.FAILED)

    def test_logs_and_jobs_never_contain_session_urls_or_tokens(self):
        self.approved("youtube")
        self.live(http=FakeYouTube(self.root, faults={2: 503}))
        text = "".join(p.read_text(encoding="utf-8", errors="replace") for p in (self.root / "publish").rglob("*") if p.is_file())
        self.assertNotIn("upload_id=S1", text)
        self.assertNotIn("Authorization", text)


class TestOAuth(unittest.TestCase):
    def test_login_uses_official_flow_least_privilege_and_keyring_only(self):
        seen = {}

        class Creds:
            granted_scopes = [yt.SCOPE_UPLOAD]

            def to_json(self):
                return json.dumps({"token": FAKE_TOKEN, "refresh_token": FAKE_REFRESH, "client_id": "x", "client_secret": "y"})

        class Flow:
            def run_local_server(self, **k):
                seen["kw"] = k
                return Creds()

        def factory(path, scopes):
            seen["scopes"] = scopes
            return Flow()
        tmp = Path(tempfile.mkdtemp())
        try:
            cs = tmp / "client.json"
            cs.write_text("{}")
            store = MemoryStore()
            import io
            import contextlib
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                info = yt.login(cs, store, "default", captions=False, flow_factory=factory)
            self.assertEqual(seen["scopes"], [yt.SCOPE_UPLOAD])                 # no broad scope without captions
            self.assertEqual(seen["kw"]["port"], 0)                             # loopback redirect, Google's page
            self.assertTrue(seen["kw"]["open_browser"])
            self.assertIn(FAKE_REFRESH, store.get(yt.credentials_key("default")))
            self.assertNotIn(FAKE_TOKEN, out.getvalue() + json.dumps(info))
            self.assertEqual(yt.scopes(True), [yt.SCOPE_UPLOAD, yt.SCOPE_CAPTIONS])
            posted = []
            self.assertTrue(yt.logout(store, "default", http_post=lambda url, **k: posted.append((url, k))))
            self.assertIsNone(store.get(yt.credentials_key("default")))
            self.assertEqual(posted[0][0], yt.REVOKE_URL)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_login_means_no_upload(self):
        with self.assertRaises(FatalError):
            yt.load_credentials(MemoryStore(), "default", captions=False)

    def test_live_adapter_refused_while_master_switch_off(self):
        from publishers.guard import GuardError
        with self.assertRaises(GuardError):
            yt.get_live_adapter("youtube", ROOT, store=MemoryStore())


if __name__ == "__main__":
    unittest.main()
