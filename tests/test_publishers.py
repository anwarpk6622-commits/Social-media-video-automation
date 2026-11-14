"""Phase 6.1 tests — publishing framework. NO network: every socket connection is blocked
for the whole module, so any accidental real API call fails the tests.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import random
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
from publishers.adapters import AdapterNotAvailable, FakeAdapter, PlatformAdapter, get_adapter  # noqa: E402
from publishers.fingerprint import sha256_file  # noqa: E402
from publishers.log import PublishLog  # noqa: E402
from publishers.plan import PlanError, make_plan  # noqa: E402
from publishers.redact import MASK, redact, redact_text  # noqa: E402
from publishers.retry import (FatalError, RetryExhausted, RetryPolicy, TransientError,  # noqa: E402
                              retry_call)
from publishers.runner import RunError, run_job  # noqa: E402
from publishers.secret_scan import FORBIDDEN_FILES, scan, scan_text  # noqa: E402
from publishers.secrets import DisabledStore, MemoryStore, SecretStoreDisabled, get_store, secret_key  # noqa: E402
from publishers.store import JobStore  # noqa: E402
from publishers.signing import Signer  # noqa: E402
from publishers.validate import validate_and_store  # noqa: E402

# Fake secrets are BUILT at runtime so the secret scanner never sees them as literals.
FAKE_GOOGLE = "ya29." + "A1b2C3d4E5f6G7h8I9j0K" * 2
FAKE_META = "EAA" + "Bcd3fGh1jKlMn0pQr5tUv7" * 2
FAKE_TIKTOK = "act." + "x9Y8z7W6v5U4t3S2r1Q0p9" * 2
FAKE_ANTHROPIC = "sk-" + "ant-" + "api03-" + "Zz9" * 10

_real_connect = socket.socket.connect
_real_create = socket.create_connection


def _blocked(*a, **k):
    raise AssertionError("NETWORK CALL attempted during Phase 6.1 tests!")


def setUpModule():
    socket.socket.connect = _blocked
    socket.create_connection = _blocked


def tearDownModule():
    socket.socket.connect = _real_connect
    socket.create_connection = _real_create


HAVE_FFMPEG = shutil.which("ffmpeg") is not None

# Tests sign approvals with an in-memory key (the real signer needs the OS keyring).
SIGNER = Signer(MemoryStore())


def APPROVE(*a, **k):
    k.setdefault("signer", SIGNER)
    return ap.approve(*a, **k)


def RUN(*a, **k):
    k.setdefault("signer", SIGNER)
    return run_job(*a, **k)
NO_SLEEP = dict(sleep=lambda s: None, rng=random.Random(1))
FAST = RetryPolicy(max_attempts=4, base_delay=0.01)


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_project(tmp: Path) -> Path:
    """A project that looks like the output of Phases 1–5 (small synthetic files)."""
    from pipeline.project import Project
    from pipeline.publish_kit import build_metadata
    p = Project.create("pub", base=tmp / "projects")
    out = p.path / "output"
    (out / "thumbnails").mkdir(parents=True)
    _ff("-f", "lavfi", "-i", "testsrc2=s=540x960:r=30:d=4", "-f", "lavfi", "-i", "sine=d=4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out / "final_9x16.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc2=s=960x540:r=30:d=4", "-f", "lavfi", "-i", "sine=d=4",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out / "final_16x9.mp4"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=1280x720", "-frames:v", "1", str(out / "thumbnails" / "youtube_thumbnail_1280x720.jpg"))
    _ff("-f", "lavfi", "-i", "color=c=blue:s=1080x1920", "-frames:v", "1", str(out / "thumbnails" / "cover_9x16_1080x1920.jpg"))
    info = {"titles": ["دبئی نیشنل ڈے کی تیاری"], "hook": "ہک۔", "description": "تفصیل۔",
            "hashtags": ["#Dubai", "#دبئی"], "location": "دبئی", "cta": "سبسکرائب کریں۔", "follow": "فالو کریں۔"}
    (p.path / "metadata").mkdir()
    (p.path / "metadata" / "metadata.json").write_text(json.dumps(build_metadata(info), ensure_ascii=False), encoding="utf-8")
    return p.path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pub-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ------------------------------------------------------------------ redaction / secrets
class TestRedaction(unittest.TestCase):
    def test_tokens_in_text_are_masked(self):
        for tok in (FAKE_GOOGLE, FAKE_META, FAKE_TIKTOK, FAKE_ANTHROPIC):
            out = redact_text(f"error from server: token={tok} please retry")
            self.assertNotIn(tok, out)
            self.assertIn(MASK, out)
        self.assertNotIn("abc123secretvalue", redact_text("Authorization: Bearer abc123secretvalue"))
        self.assertNotIn("SIGNATURE123", redact_text("https://up.example/x?upload_id=SIGNATURE123&a=1"))

    def test_secret_keys_masked_in_nested_data(self):
        data = {"access_token": "plain", "nested": [{"client_secret": "s", "refresh_token": "r"}],
                "session": {"upload_url": "https://u/1"}, "title": "عنوان", "remote_id": "abc"}
        out = redact(data)
        self.assertEqual(out["access_token"], MASK)
        self.assertEqual(out["nested"][0]["client_secret"], MASK)
        self.assertEqual(out["session"]["upload_url"], MASK)
        self.assertEqual(out["title"], "عنوان")
        self.assertEqual(out["remote_id"], "abc")

    def test_log_never_contains_secret(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            log = PublishLog(tmp)
            log.write("upload_failed", "youtube", error=f"401 for {FAKE_GOOGLE}", access_token=FAKE_GOOGLE)
            raw = (tmp / "publish" / "log.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(FAKE_GOOGLE, raw)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_secret_store_disabled_in_6_1(self):
        store = get_store(live_enabled=False)
        self.assertIsInstance(store, DisabledStore)
        with self.assertRaises(SecretStoreDisabled):
            store.set(secret_key("youtube"), FAKE_GOOGLE)
        self.assertIsNone(store.get(secret_key("youtube")))

    def test_memory_store_never_prints_values(self):
        m = MemoryStore()
        m.set("k", FAKE_META)
        self.assertNotIn(FAKE_META, str(m) + repr(m) + m.describe("k"))


class TestSecretScan(unittest.TestCase):
    def test_finds_and_masks(self):
        f = scan_text(f'token = "{FAKE_GOOGLE}"\nkey={FAKE_ANTHROPIC}\nok line', "x.py")
        self.assertEqual({x["type"] for x in f}, {"Google OAuth access token", "Anthropic API key"})
        self.assertTrue(all(FAKE_GOOGLE not in x["match"] and FAKE_ANTHROPIC not in x["match"] for x in f))

    def test_allow_marker_and_placeholders(self):
        self.assertEqual(scan_text(f"x = '{FAKE_META}'  # secret-scan: allow", "a"), [])
        self.assertEqual(scan_text("ANTHROPIC_API_KEY=\naccess_token = None", "a"), [])

    def test_forbidden_files(self):
        for name in (".env", "config/.env.local", "client_secret_123.json", "token.json", "secrets/x",
                     "projects/p/publish/private/youtube.json"):
            self.assertTrue(any(p.search(name) for p in FORBIDDEN_FILES), name)
        self.assertFalse(any(p.search(".env.example") for p in FORBIDDEN_FILES))

    def test_git_hook_command_is_valid(self):
        """The pre-commit hook calls `run.py secret-scan --staged` — that exact command must parse and run."""
        from publishers.secret_scan import HOOK
        self.assertIn("run.py secret-scan --staged", HOOK)
        r = subprocess.run([sys.executable, str(ROOT / "run.py"), "secret-scan", "--staged"],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertNotIn("unrecognized arguments", r.stderr)
        self.assertIn(r.returncode, (0, 1))

    def test_staged_scan_blocks_env_file(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
            (tmp / ".env").write_text("X=1\n")
            (tmp / "ok.py").write_text("print('hi')\n")
            subprocess.run(["git", "add", "-f", ".env", "ok.py"], cwd=tmp, check=True)
            found = scan(tmp, staged=True)
            self.assertEqual([f["file"] for f in found], [".env"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ models / retry
class TestModels(unittest.TestCase):
    def test_allowed_and_forbidden_transitions(self):
        j = md.Job(id="youtube", project="p", platform="youtube", privacy="private")
        for to in (md.VALIDATED, md.APPROVED, md.UPLOADING, md.PROCESSING, md.COMPLETED):
            j.move(to)
        self.assertEqual([h["to"] for h in j.history], ["validated", "approved", "uploading", "processing", "completed"])
        with self.assertRaises(md.TransitionError):
            j.move(md.UPLOADING)                     # completed is final
        j2 = md.Job(id="t", project="p", platform="tiktok")
        with self.assertRaises(md.TransitionError):
            j2.move(md.APPROVED)                     # cannot skip validation
        with self.assertRaises(md.TransitionError):
            j2.move(md.UPLOADING)

    def test_safe_privacy_defaults(self):
        self.assertEqual({p: v[0] for p, v in md.PRIVACY.items()},
                         {"youtube": "private", "youtube_shorts": "private", "facebook_reels": "draft", "tiktok": "self_only"})


class TestRetry(unittest.TestCase):
    def test_backoff_grows_and_respects_retry_after(self):
        pol, rng = RetryPolicy(base_delay=1, max_delay=60, jitter=0.25), random.Random(3)
        d = [pol.delay(n, rng) for n in (1, 2, 3, 4)]
        for n, x in enumerate(d, 1):
            self.assertTrue(0.75 * 2 ** (n - 1) <= x <= 1.25 * 2 ** (n - 1), d)
        self.assertEqual(pol.delay(1, rng, retry_after=7), 7)

    def test_transient_retried_then_success(self):
        calls, waits = [], []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise TransientError("drop")
            return "ok"
        self.assertEqual(retry_call(fn, FAST, sleep=waits.append, rng=random.Random(1)), "ok")
        self.assertEqual((len(calls), len(waits)), (3, 2))

    def test_exhausted_and_fatal(self):
        def always():
            raise TransientError("down")
        with self.assertRaises(RetryExhausted):
            retry_call(always, FAST, **NO_SLEEP)
        calls = []

        def fatal():
            calls.append(1)
            raise FatalError("403")
        with self.assertRaises(FatalError):
            retry_call(fatal, FAST, **NO_SLEEP)
        self.assertEqual(len(calls), 1, "fatal errors must never be retried")


# ------------------------------------------------------------------ plan / validate / approve / run
@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class TestWorkflow(Base):
    def setUp(self):
        super().setUp()
        self.root = make_project(self.tmp)
        self.store = JobStore(self.root)

    def approve_all(self, ids=None, extra=()):
        for jid in ids or [j.id for j in self.store.all()]:
            answers = iter(["APPROVE", *extra])
            APPROVE(self.root, self.store, jid, input_fn=lambda _: next(answers))

    def validated(self, platforms=None):
        make_plan(self.root, platforms)
        for j in self.store.all():
            validate_and_store(self.root, self.store, j.id)

    # ---- plan
    def test_plan_creates_safe_jobs_and_is_idempotent(self):
        res = make_plan(self.root)
        self.assertEqual({r["job"].id: (r["action"], r["job"].privacy) for r in res},
                         {"youtube": ("created", "private"), "youtube_shorts": ("created", "private"),
                          "facebook_reels": ("created", "draft"), "tiktok": ("created", "self_only")})
        before = {p.name: p.read_bytes() for p in (self.root / "publish" / "jobs").glob("*.json")}
        self.assertEqual({r["action"] for r in make_plan(self.root)}, {"unchanged"})
        after = {p.name: p.read_bytes() for p in (self.root / "publish" / "jobs").glob("*.json")}
        self.assertEqual(before, after, "re-planning without changes must not touch job files")

    def test_plan_rejects_bad_privacy_and_schedule(self):
        with self.assertRaises(PlanError):
            make_plan(self.root, ["tiktok"], privacy={"tiktok": "unlisted"})
        with self.assertRaises(PlanError):
            make_plan(self.root, ["youtube"], schedule="kal shaam")

    def test_phase5_files_are_only_read(self):
        snap = {p: sha256_file(p) for p in (self.root / "output").rglob("*") if p.is_file()}
        snap[self.root / "metadata" / "metadata.json"] = sha256_file(self.root / "metadata" / "metadata.json")
        self.validated()
        self.approve_all()
        for jid in ("youtube", "tiktok"):
            RUN(self.root, self.store, jid, FakeAdapter(jid), simulate=True, policy=FAST, poll_interval=0, **NO_SLEEP)
        self.assertEqual(snap, {p: sha256_file(p) for p in snap})

    # ---- validation
    def test_dry_run_validation(self):
        self.validated()
        for j in self.store.all():
            self.assertTrue(j.validation["ok"], (j.id, j.validation["errors"]))
            self.assertEqual(j.status, md.VALIDATED)
            self.assertEqual(j.validation["network_calls"], 0)

    def test_validation_catches_wrong_aspect_and_changed_files(self):
        meta_f = self.root / "metadata" / "metadata.json"
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        meta["facebook_reels"]["video_file"] = "output/final_16x9.mp4"      # 16:9 is not a Reel
        meta_f.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        make_plan(self.root, ["facebook_reels", "tiktok"])
        j = validate_and_store(self.root, self.store, "facebook_reels")
        self.assertFalse(j.validation["ok"])
        self.assertTrue(any("9:16" in e for e in j.validation["errors"]))
        self.assertEqual(j.status, md.PENDING)
        _ff("-f", "lavfi", "-i", "testsrc=s=540x960:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(self.root / "output" / "final_9x16.mp4"))                  # file changes after plan
        j = validate_and_store(self.root, self.store, "tiktok")
        self.assertTrue(any("badal gayi" in e for e in j.validation["errors"]))

    def test_past_schedule_rejected(self):
        make_plan(self.root, ["youtube"], schedule="2020-01-01T10:00")
        self.assertTrue(any("guzar" in e for e in validate_and_store(self.root, self.store, "youtube").validation["errors"]))

    # ---- approval
    def test_approval_needs_validation_and_exact_phrase(self):
        make_plan(self.root, ["youtube"])
        with self.assertRaises(ap.ApprovalError):
            APPROVE(self.root, self.store, "youtube", input_fn=lambda _: "APPROVE")   # not validated yet
        validate_and_store(self.root, self.store, "youtube")
        with self.assertRaises(ap.ApprovalError):
            APPROVE(self.root, self.store, "youtube", input_fn=lambda _: "approve")   # wrong case = no
        self.assertEqual(self.store.load("youtube").status, md.VALIDATED)
        self.approve_all(["youtube"])
        j = self.store.load("youtube")
        self.assertEqual(j.status, md.APPROVED)
        self.assertEqual(j.approval["fingerprints"]["files"]["video"], sha256_file(self.root / "output" / "final_16x9.mp4"))

    def test_public_needs_separate_confirmation(self):
        make_plan(self.root, ["youtube"], privacy={"youtube": "public"})
        validate_and_store(self.root, self.store, "youtube")
        answers = iter(["APPROVE", "yes"])
        with self.assertRaises(ap.ApprovalError):
            APPROVE(self.root, self.store, "youtube", input_fn=lambda _: next(answers))
        self.assertEqual(self.store.load("youtube").status, md.VALIDATED)
        self.approve_all(["youtube"], extra=["PUBLIC"])
        self.assertTrue(self.store.load("youtube").approval["public_confirmed"])

    def test_fingerprint_mismatch_revokes_approval_and_blocks_run(self):
        self.validated(["tiktok"])
        self.approve_all(["tiktok"])
        _ff("-f", "lavfi", "-i", "testsrc=s=540x960:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(self.root / "output" / "final_9x16.mp4"))
        with self.assertRaises(RunError):
            RUN(self.root, self.store, "tiktok", FakeAdapter("tiktok"), simulate=False, policy=FAST, **NO_SLEEP)
        j = self.store.load("tiktok")
        self.assertEqual(j.status, md.PENDING)
        self.assertFalse(j.approval)
        self.assertEqual(j.error["type"], "approval_revoked")

    def test_metadata_or_privacy_change_after_approval_revokes(self):
        self.validated(["youtube"])
        self.approve_all(["youtube"])
        meta_f = self.root / "metadata" / "metadata.json"
        meta = json.loads(meta_f.read_text(encoding="utf-8"))
        meta["youtube"]["title"] += " نیا"
        meta_f.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        res = make_plan(self.root, ["youtube"])
        self.assertEqual(res[0]["action"], "replanned")
        self.assertEqual(self.store.load("youtube").status, md.PENDING)
        self.assertFalse(self.store.load("youtube").approval)

    # ---- running (offline FakeAdapter only)
    def test_offline_run_completes_and_is_idempotent(self):
        self.validated(["youtube"])
        self.approve_all(["youtube"])
        fa = FakeAdapter("youtube", failures=["transient", None, "rate_limit"], chunk_size=64 * 1024)
        j = RUN(self.root, self.store, "youtube", fa, simulate=False, policy=FAST, poll_interval=0, **NO_SLEEP)
        self.assertEqual(j.status, md.COMPLETED)
        self.assertEqual(fa.received.hexdigest(), sha256_file(self.root / "output" / "final_16x9.mp4"))
        self.assertEqual(j.upload["retries"], 2)
        fa2 = FakeAdapter("youtube")
        j2 = RUN(self.root, self.store, "youtube", fa2, simulate=False, policy=FAST, **NO_SLEEP)
        self.assertEqual(j2.status, md.COMPLETED)
        self.assertEqual((fa2.calls, fa2.finished), (0, 0), "a completed job must never upload again")
        events = [r["event"] for r in PublishLog(self.root).read("youtube")]
        self.assertIn("upload_retry", events)
        self.assertIn("run_skipped_completed", events)

    def test_fatal_error_fails_without_retry(self):
        self.validated(["tiktok"])
        self.approve_all(["tiktok"])
        fa = FakeAdapter("tiktok", failures=["fatal"])
        j = RUN(self.root, self.store, "tiktok", fa, simulate=False, policy=FAST, **NO_SLEEP)
        self.assertEqual(j.status, md.FAILED)
        self.assertEqual(fa.calls, 1)
        self.assertEqual(j.error["type"], "FatalError")

    def test_crash_mid_upload_resumes_from_saved_offset(self):
        self.validated(["facebook_reels"])
        self.approve_all(["facebook_reels"])
        size = (self.root / "output" / "final_9x16.mp4").stat().st_size
        chunk = 32 * 1024
        fa = FakeAdapter("facebook_reels", failures=[None, None, "crash"], chunk_size=chunk)
        with self.assertRaises(KeyboardInterrupt):
            RUN(self.root, self.store, "facebook_reels", fa, simulate=False, policy=FAST, **NO_SLEEP)
        j = self.store.load("facebook_reels")
        self.assertEqual(j.status, md.UPLOADING)
        self.assertEqual(j.upload["bytes_sent"], 2 * chunk)
        self.assertTrue((self.root / "publish" / "private" / "facebook_reels.json").exists())
        fa2 = FakeAdapter("facebook_reels", chunk_size=chunk)
        j = RUN(self.root, self.store, "facebook_reels", fa2, simulate=False, policy=FAST, poll_interval=0, **NO_SLEEP)
        self.assertEqual(j.status, md.COMPLETED)
        remaining = -(-(size - 2 * chunk) // chunk)
        self.assertEqual(fa2.calls, remaining, "resume must not resend already confirmed chunks")
        self.assertEqual(fa2.received_bytes, size)
        self.assertFalse((self.root / "publish" / "private" / "facebook_reels.json").exists())

    def test_failed_job_can_retry_with_same_approval(self):
        self.validated(["youtube_shorts"])
        self.approve_all(["youtube_shorts"])
        RUN(self.root, self.store, "youtube_shorts", FakeAdapter("youtube_shorts", failures=["fatal"]),
                simulate=False, policy=FAST, **NO_SLEEP)
        self.assertEqual(self.store.load("youtube_shorts").status, md.FAILED)
        j = RUN(self.root, self.store, "youtube_shorts", FakeAdapter("youtube_shorts"), simulate=False,
                    policy=FAST, poll_interval=0, **NO_SLEEP)
        self.assertEqual(j.status, md.COMPLETED)
        self.assertEqual([h["to"] for h in j.history][-4:], ["approved", "uploading", "processing", "completed"])

    def test_simulation_never_changes_real_job(self):
        self.validated(["tiktok"])
        self.approve_all(["tiktok"])
        before = (self.root / "publish" / "jobs" / "tiktok.json").read_bytes()
        sim = RUN(self.root, self.store, "tiktok", FakeAdapter("tiktok"), simulate=True, policy=FAST,
                      poll_interval=0, **NO_SLEEP)
        self.assertEqual(sim.status, md.COMPLETED)
        self.assertEqual((self.root / "publish" / "jobs" / "tiktok.json").read_bytes(), before)
        self.assertEqual(self.store.load("tiktok").status, md.APPROVED)
        self.assertTrue(list((self.root / "publish" / "simulations").glob("tiktok-*.json")))

    def test_real_publishing_is_impossible_in_6_1(self):
        self.validated(["youtube"])
        self.approve_all(["youtube"])
        with self.assertRaises(AdapterNotAvailable):
            get_adapter("youtube", live_enabled=False)

        class OnlineAdapter(PlatformAdapter):
            offline = False
        with self.assertRaises(RunError):
            RUN(self.root, self.store, "youtube", OnlineAdapter(), simulate=False, live_enabled=False, **NO_SLEEP)
        self.assertEqual(self.store.load("youtube").status, md.APPROVED)

    def test_job_files_contain_no_secrets(self):
        self.validated(["tiktok"])
        self.approve_all(["tiktok"])
        j = self.store.load("tiktok")
        j.error = {"message": f"401 {FAKE_TIKTOK}"}
        j.upload = {"session": {"upload_url": "https://x/?upload_id=SECRET1234"}}
        self.store.save(j)
        raw = (self.root / "publish" / "jobs" / "tiktok.json").read_text(encoding="utf-8")
        self.assertNotIn(FAKE_TIKTOK, raw)
        self.assertNotIn("SECRET1234", raw)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg needed")
class TestCLI(Base):
    def test_cli_flow_and_live_run_refused(self):
        root = make_project(self.tmp)
        env_proj = str(root)

        def cli(*args, stdin=""):
            return subprocess.run([sys.executable, str(ROOT / "run.py"), *args], input=stdin, capture_output=True,
                                  text=True, cwd=ROOT)
        self.assertEqual(cli("publish-plan", env_proj).returncode, 0)
        self.assertEqual(cli("publish-check", env_proj).returncode, 0)
        # Without a working OS keyring the CLI must FAIL CLOSED: no approval, nothing changes.
        from publishers.signing import SigningUnavailable, get_signer
        try:
            get_signer()
            have_keyring = True
        except SigningUnavailable:
            have_keyring = False
        r = cli("publish-approve", env_proj, "--platform", "tiktok", stdin="APPROVE\n")
        if not have_keyring:
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("sign nahi ho sakti", r.stdout)
            self.assertEqual(JobStore(root).load("tiktok").status, md.VALIDATED)
            # approve in-process with the test signer so the remaining CLI steps can be exercised
            APPROVE(root, JobStore(root), "tiktok", input_fn=lambda _: "APPROVE")
        r = cli("publish-run", env_proj)
        self.assertEqual(r.returncode, 1)
        self.assertIn("band", r.stdout)
        r = cli("publish-run", env_proj, "--simulate", "--platform", "tiktok", "--fail", "transient")
        if not have_keyring:
            # the CLI cannot verify the signature without the keyring → refuses, changes nothing
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("dastakhat", r.stdout)
        self.assertEqual(JobStore(root).load("tiktok").status, md.APPROVED)
        self.assertEqual(cli("publish-status", env_proj).returncode, 0)
        self.assertEqual(cli("publish-report", env_proj).returncode, 0)
        html = (root / "preview" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("Publishing (Phase 6)", html)


if __name__ == "__main__":
    unittest.main()
