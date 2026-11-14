"""Retry with exponential backoff + jitter, and a resumable chunked-upload framework.

Rules
-----
- TransientError  (network drop, HTTP 5xx, 429 rate limit)  → retry with backoff
- FatalError      (HTTP 4xx: permission, policy, bad request) → stop at once, never retry
- Any other exception is treated as fatal (unknown problems are not hammered).

Resumable upload: the file is sent in chunks; after every confirmed chunk the
offset is saved. If the process or the connection dies, the next run continues
from the saved offset instead of sending the whole file again. Before resuming,
the file's SHA-256 is checked again — a changed file is never "continued".
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class TransientError(Exception):
    """Temporary problem — safe to retry."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class FatalError(Exception):
    """Permanent problem — do not retry."""


class RetryExhausted(Exception):
    pass


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: float = 0.25        # ±25%

    def delay(self, attempt: int, rng: random.Random, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(self.max_delay, max(0.0, retry_after))
        d = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        return max(0.0, d * (1 + rng.uniform(-self.jitter, self.jitter)))


def retry_call(fn: Callable, policy: RetryPolicy, *, on_retry: Callable | None = None,
               sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None):
    rng = rng or random.Random()
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except TransientError as e:
            if attempt == policy.max_attempts:
                raise RetryExhausted(f"{policy.max_attempts} koshishon ke baad bhi nakaam: {e}") from e
            d = policy.delay(attempt, rng, e.retry_after)
            if on_retry:
                on_retry(attempt, d, e)
            sleep(d)
        except FatalError:
            raise


class ChunkSender:
    """What a platform adapter implements for chunked uploads."""

    def send_chunk(self, data: bytes, offset: int, total: int, session: dict) -> int:
        """Send one chunk; return the confirmed new offset (bytes the server has)."""
        raise NotImplementedError


def resumable_upload(path: Path, sender: ChunkSender, *, state: dict, save_state: Callable[[dict], None],
                     policy: RetryPolicy, chunk_size: int = 8 * 1024 * 1024,
                     sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None,
                     on_event: Callable[..., None] | None = None) -> dict:
    """Upload `path` in chunks, resuming from state['bytes_sent'].

    `state` must hold 'sha256' of the approved file; `save_state` persists progress."""
    from .fingerprint import sha256_file

    total = path.stat().st_size
    if state.get("sha256") and sha256_file(path) != state["sha256"]:
        raise FatalError("File approval ke baad badal gayi — upload roka gaya.")
    offset = int(state.get("bytes_sent", 0))
    if offset and on_event:
        on_event("upload_resumed", offset=offset, total=total)
    with open(path, "rb") as f:
        while offset < total:
            f.seek(offset)
            data = f.read(chunk_size)

            def attempt(data=data, offset=offset):
                return sender.send_chunk(data, offset, total, state.setdefault("session", {}))

            def note(n, d, e):
                state["retries"] = int(state.get("retries", 0)) + 1
                if on_event:
                    on_event("upload_retry", attempt=n, wait_seconds=round(d, 2), error=str(e), offset=offset)

            new_offset = retry_call(attempt, policy, on_retry=note, sleep=sleep, rng=rng)
            if not (offset < new_offset <= total):
                raise FatalError(f"Server ne ghalat offset bataya ({new_offset}).")
            offset = new_offset
            state["bytes_sent"] = offset
            save_state(state)   # progress survives crashes
            if on_event:
                on_event("upload_progress", bytes_sent=offset, total=total)
    return state
