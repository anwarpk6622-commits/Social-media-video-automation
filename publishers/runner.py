"""Idempotent job execution: verify approval → upload (resumable) → processing → completed.

Idempotency guarantees
----------------------
- A COMPLETED job is never uploaded again.
- If an upload already finished (remote_id saved) but the program died before
  marking processing, the next run only checks status — no second upload.
- An interrupted upload continues from the last confirmed byte.

Simulation (`simulate=True`) works on a COPY of the job: the real job file and
its status are never changed; results go to publish/simulations/.
"""

from __future__ import annotations

import copy
import json
import random
import time
from pathlib import Path
from typing import Callable

from .adapters import PlatformAdapter
from .approval import verify_or_revoke
from .log import PublishLog
from .models import APPROVED, COMPLETED, FAILED, PROCESSING, UPLOADING, Job, now
from .redact import redact
from .retry import FatalError, RetryExhausted, RetryPolicy, TransientError, resumable_upload, retry_call


class RunError(RuntimeError):
    pass


class _SimStore:
    """In-memory stand-in for JobStore during simulations (the real job stays untouched)."""

    def __init__(self, job: Job):
        self.job = job
        self.private: dict = {}

    def save(self, job: Job) -> None:
        self.job = job

    def save_private(self, job_id: str, data: dict) -> None:
        self.private = dict(data)

    def load_private(self, job_id: str) -> dict:
        return dict(self.private)

    def clear_private(self, job_id: str) -> None:
        self.private = {}


def run_job(project_root: Path, store, job_id: str, adapter: PlatformAdapter, *, simulate: bool,
            live_enabled: bool = False, policy: RetryPolicy | None = None,
            sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None,
            poll_interval: float = 5.0, max_polls: int = 120) -> Job:
    if not simulate and not live_enabled and not adapter.offline:
        raise RunError("Asal publishing band hai (Phase 6.1).")
    policy = policy or RetryPolicy()
    log = PublishLog(project_root)
    tag = "sim_" if simulate else ""

    def event(name, job, **data):
        log.write(tag + name, job.id, **data)

    with store.lock(job_id):
        real = store.load(job_id)
        if real.status == COMPLETED:
            event("run_skipped_completed", real, remote_id=real.upload.get("remote_id"))
            return real
        if real.status not in (APPROVED, UPLOADING, PROCESSING, FAILED):
            raise RunError(f"'{job_id}' ki haalat '{real.status}' hai — pehle publish-check aur publish-approve.")
        if real.status == FAILED and not real.approval:
            raise RunError(f"'{job_id}' nakaam hua tha aur manzoori mojood nahi — dobara plan/check/approve.")

        # Approval must still match the files exactly (checked on the REAL job).
        diff = verify_or_revoke(project_root, store, real) if not simulate else _diff_only(project_root, real)
        if diff:
            raise RunError("Manzoori radd: " + "; ".join(diff))

        job = copy.deepcopy(real) if simulate else real
        jstore = _SimStore(job) if simulate else store
        try:
            if job.status == FAILED:
                # fingerprints were verified above, so the old approval still covers these exact files
                job.move(APPROVED, "nakaami ke baad dobara koshish (manzoori abhi bhi durust)")
            if job.status == APPROVED:
                job.move(UPLOADING, "upload shuru")
                job.upload.setdefault("attempts", 0)
                job.upload["attempts"] += 1
                jstore.save(job)
                event("upload_started", job, privacy=job.privacy, attempt=job.upload["attempts"])

            if job.status == UPLOADING and not job.upload.get("remote_id"):
                video = project_root / job.files["video"]["path"]
                state = jstore.load_private(job.id) or {}
                state.setdefault("sha256", job.approval["fingerprints"]["files"]["video"])
                if not state.get("session"):
                    state["session"] = retry_call(lambda: adapter.start(job), policy, sleep=sleep, rng=rng)
                    jstore.save_private(job.id, state)

                def save_state(st):
                    jstore.save_private(job.id, st)
                    job.upload["bytes_sent"] = st.get("bytes_sent", 0)
                    job.upload["retries"] = st.get("retries", 0)
                    jstore.save(job)

                resumable_upload(video, adapter, state=state, save_state=save_state, policy=policy,
                                 chunk_size=adapter.chunk_size, sleep=sleep, rng=rng,
                                 on_event=lambda name, **d: event(name, job, **d))
                done = retry_call(lambda: adapter.finish(job, state.get("session", {})), policy, sleep=sleep, rng=rng)
                job.upload.update({"remote_id": done["remote_id"], "url": done.get("url"), "uploaded": now()})
                jstore.clear_private(job.id)          # session data is no longer needed
                job.move(PROCESSING, "upload mukammal, platform processing")
                jstore.save(job)
                event("upload_finished", job, remote_id=done["remote_id"])
            elif job.status == UPLOADING and job.upload.get("remote_id"):
                job.move(PROCESSING, "upload pehle hi mukammal tha (resume)")
                jstore.save(job)

            for _ in range(max_polls):
                st, info = retry_call(lambda: adapter.status(job, job.upload["remote_id"]), policy, sleep=sleep, rng=rng)
                if st == "processing":
                    sleep(poll_interval)
                    continue
                if st == "completed":
                    job.move(COMPLETED, "platform par mukammal")
                    job.error = {}
                    jstore.save(job)
                    event("job_completed", job, remote_id=job.upload["remote_id"], url=job.upload.get("url"))
                    break
                raise FatalError(f"Platform processing nakaam: {info}")
            else:
                event("processing_still_running", job)
        except (FatalError, RetryExhausted, TransientError) as e:
            if job.status in (UPLOADING, PROCESSING):
                job.move(FAILED, str(e)[:200])
            job.error = redact({"time": now(), "type": type(e).__name__, "message": str(e)})
            jstore.save(job)
            event("job_failed", job, error=job.error)
        if simulate:
            _save_simulation(project_root, job)
        return job


def _diff_only(project_root: Path, job: Job) -> list[str]:
    from .fingerprint import current_fingerprints, differences
    if not job.approval:
        return ["koi manzoori nahi"]
    d = differences(job.approval["fingerprints"], current_fingerprints(project_root, job))
    if job.is_public and not job.approval.get("public_confirmed"):
        d.append("public tasdeeq mojood nahi")
    return d


def _save_simulation(project_root: Path, job: Job) -> None:
    d = project_root / "publish" / "simulations"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{job.id}-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
        json.dumps(redact(job.to_dict()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
