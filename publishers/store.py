"""Jobs on disk: projects/<p>/publish/jobs/<job-id>.json

- atomic writes (temp file + rename): a crash never leaves a half-written job
- a simple lock file so two runs cannot work on the same job at once
- nothing secret is ever stored here (upload sessions live in publish/private/,
  which is excluded from Git)
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .models import Job
from .redact import redact


class JobStore:
    def __init__(self, project_root: Path):
        self.root = Path(project_root)
        self.dir = self.root / "publish"
        self.jobs_dir = self.dir / "jobs"
        self.private_dir = self.dir / "private"   # gitignored: resumable session data etc.

    def ensure(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def exists(self, job_id: str) -> bool:
        return self.path(job_id).exists()

    def load(self, job_id: str) -> Job:
        return Job.from_dict(json.loads(self.path(job_id).read_text(encoding="utf-8")))

    def all(self) -> list[Job]:
        if not self.jobs_dir.exists():
            return []
        return [Job.from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(self.jobs_dir.glob("*.json"))]

    def save(self, job: Job) -> None:
        """Atomic write. The job is redacted first as a last safety net."""
        self.ensure()
        data = json.dumps(redact(job.to_dict()), ensure_ascii=False, indent=2) + "\n"
        tmp = self.path(job.id).with_suffix(".json.tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, self.path(job.id))

    @contextmanager
    def lock(self, job_id: str, timeout: float = 10.0):
        self.ensure()
        lock = self.jobs_dir / f"{job_id}.lock"
        start = time.time()
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                break
            except FileExistsError:
                if time.time() - lock.stat().st_mtime > 3600:   # stale lock (crashed run)
                    lock.unlink(missing_ok=True)
                    continue
                if time.time() - start > timeout:
                    raise RuntimeError(f"Job {job_id} par pehle se kaam chal raha hai (lock: {lock.name}).")
                time.sleep(0.1)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    # private, non-git storage for resumable-upload session data (may be sensitive)
    def save_private(self, job_id: str, data: dict) -> None:
        self.private_dir.mkdir(parents=True, exist_ok=True)
        p = self.private_dir / f"{job_id}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def load_private(self, job_id: str) -> dict:
        p = self.private_dir / f"{job_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def clear_private(self, job_id: str) -> None:
        (self.private_dir / f"{job_id}.json").unlink(missing_ok=True)
