"""Platform adapters.

Every platform implements the same small interface, so the job framework never
needs to know platform details. Phase 6.1 ships ONLY the offline FakeAdapter
(for simulations and tests). Real adapters arrive one by one:
6.2 YouTube · 6.3 Facebook Reels · 6.4 TikTok — each after your approval.
"""

from __future__ import annotations

import hashlib
import random

from .models import Job
from .retry import ChunkSender, FatalError, TransientError


class AdapterNotAvailable(RuntimeError):
    pass


class PlatformAdapter(ChunkSender):
    platform = "base"
    offline = False          # True = never touches the network
    chunk_size = 8 * 1024 * 1024

    def start(self, job: Job) -> dict:
        """Open an upload session; return session data (kept in publish/private/, never logged)."""
        raise NotImplementedError

    def finish(self, job: Job, session: dict) -> dict:
        """Complete the upload (+ metadata, privacy, thumbnail). Return {'remote_id', 'url'}."""
        raise NotImplementedError

    def status(self, job: Job, remote_id: str) -> tuple[str, dict]:
        """Return ('processing'|'completed'|'failed', info)."""
        raise NotImplementedError


class FakeAdapter(PlatformAdapter):
    """Offline simulation of a chunked, resumable upload + processing.

    failures: list of what to raise on successive chunk calls, e.g.
      ["transient", None, "transient"]  → 1st and 3rd chunk calls fail once (retried)
      ["fatal"]                         → first chunk call fails permanently
      ["crash"]                         → simulates the program dying mid-upload
    """
    offline = True

    def __init__(self, platform: str, *, failures: list | None = None, processing_polls: int = 2,
                 final_status: str = "completed", chunk_size: int = 256 * 1024, seed: int = 7,
                 on_chunk=None):
        self.on_chunk = on_chunk          # tests: callback(call_number) after each accepted chunk
        self.platform = platform
        self.failures = list(failures or [])
        self.processing_polls = processing_polls
        self.final_status = final_status
        self.chunk_size = chunk_size
        self.calls = 0
        self.received = hashlib.sha256()
        self.received_bytes = 0
        self.finished = 0
        self._polls = 0
        self._rng = random.Random(seed)

    def start(self, job: Job) -> dict:
        return {"upload_url": f"https://upload.invalid/session/{self._rng.getrandbits(64):x}", "simulated": True}

    def send_chunk(self, data: bytes, offset: int, total: int, session: dict) -> int:
        self.calls += 1
        what = self.failures.pop(0) if self.failures else None
        if what == "transient":
            raise TransientError("simulated network drop")
        if what == "rate_limit":
            raise TransientError("simulated 429", retry_after=0.5)
        if what == "fatal":
            raise FatalError("simulated 403 permission denied")
        if what == "crash":
            raise KeyboardInterrupt("simulated crash")
        if offset != self.received_bytes:
            # a real server would tell us its offset; resuming must start where it stopped
            self.received_bytes = offset
        self.received.update(data)
        self.received_bytes += len(data)
        if self.on_chunk:
            self.on_chunk(self.calls)
        return offset + len(data)

    def finish(self, job: Job, session: dict) -> dict:
        self.finished += 1
        rid = f"sim-{job.platform}-{self._rng.getrandbits(32):08x}"
        return {"remote_id": rid, "url": f"https://example.invalid/{rid}"}

    def status(self, job: Job, remote_id: str) -> tuple[str, dict]:
        self._polls += 1
        if self._polls <= self.processing_polls:
            return "processing", {"poll": self._polls}
        return self.final_status, {"poll": self._polls}


def get_adapter(platform: str, *, live_enabled: bool, simulate: bool = False, **fake_kwargs) -> PlatformAdapter:
    if simulate:
        return FakeAdapter(platform, **fake_kwargs)
    if not live_enabled:
        raise AdapterNotAvailable(
            "Asal publishing band hai (Phase 6.1). Sirf --simulate chal sakta hai. "
            "YouTube integration Phase 6.2 mein, aap ki manzoori ke baad.")
    raise AdapterNotAvailable(f"'{platform}' ka asal adapter abhi bana hi nahi (Phase 6.2+).")
