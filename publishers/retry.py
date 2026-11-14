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


class SessionLost(FatalError):
    """The platform forgot the upload session (e.g. YouTube 404), or the server holds bytes we
    cannot prove were the approved bytes. The upload must restart from byte 0 in a NEW session."""


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


def _range_digest(path: Path, offset: int, length: int) -> str:
    import hashlib
    with open(path, "rb") as f:
        f.seek(offset)
        return hashlib.sha256(f.read(length)).hexdigest()


def verify_sent(path: Path, state: dict) -> None:
    """Security fix 2: prove that every byte already SENT equals the approved file.

    1) the whole file on disk must still match the approved SHA-256, and
    2) every confirmed range must hash to exactly what was sent.
    Together this catches a file that changed mid-upload — even if it was changed
    back afterwards."""
    from .fingerprint import sha256_file
    if not state.get("sha256"):
        raise FatalError("Approved fingerprint mojood nahi — upload roka gaya.")
    if sha256_file(path) != state["sha256"]:
        raise FatalError("File manzoori ke baad badal gayi — upload roka gaya.")
    for r in state.get("sent_ranges", []):
        if _range_digest(path, r["offset"], r["length"]) != r["sha256"]:
            raise FatalError(f"Upload ke dauran bheja gaya hissa (byte {r['offset']}) manzoor shuda file se "
                             "mukhtalif tha — upload roka gaya.")


def resumable_upload(path: Path, sender: ChunkSender, *, state: dict, save_state: Callable[[dict], None],
                     policy: RetryPolicy, chunk_size: int = 8 * 1024 * 1024,
                     sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None,
                     on_event: Callable[..., None] | None = None) -> dict:
    """Upload `path` in chunks, resuming from state['bytes_sent'].

    `state` must hold 'sha256' of the approved file; `save_state` persists progress.
    Every confirmed chunk's own SHA-256 is recorded in state['sent_ranges'] and checked
    again (verify_sent) on resume and before the caller may call finish()."""
    import hashlib

    total = path.stat().st_size
    verify_sent(path, state)            # whole file + anything sent before a crash
    offset = int(state.get("bytes_sent", 0))
    sync = getattr(sender, "sync_offset", None)
    if offset and callable(sync):
        # After a crash the SERVER is the truth: ask how many bytes it really has.
        server = retry_call(lambda: sync(state.setdefault("session", {}), total), policy, sleep=sleep, rng=rng)
        if server > offset:
            # bytes the server got but we never recorded → cannot prove they were the approved
            # bytes → never continue on unverifiable data: restart in a new session
            raise SessionLost(f"Server ke paas {server} bytes, record mein {offset} — tasdeeq na hone ki wajah se "
                              "upload naye session mein shuru se hoga.")
        if server < offset:
            if any(r["offset"] < server < r["offset"] + r["length"] for r in state.get("sent_ranges", [])):
                raise SessionLost("Server ki hadd ek record shuda tukde ke beech mein — tasdeeq ke liye upload "
                                  "naye session mein shuru se hoga.")
            state["sent_ranges"] = [r for r in state.get("sent_ranges", []) if r["offset"] + r["length"] <= server]
            offset = server
            state["bytes_sent"] = offset
            save_state(state)
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
            confirmed = data[: new_offset - offset]          # what the server actually has
            state.setdefault("sent_ranges", []).append(
                {"offset": offset, "length": len(confirmed), "sha256": hashlib.sha256(confirmed).hexdigest()})
            offset = new_offset
            state["bytes_sent"] = offset
            save_state(state)   # progress survives crashes
            if on_event:
                on_event("upload_progress", bytes_sent=offset, total=total)
    verify_sent(path, state)            # nothing may be finished unless every sent byte is the approved byte
    if path.stat().st_size != total or offset != total:
        raise FatalError("Upload ke dauran file ka size badal gaya — upload roka gaya.")
    # every byte the server holds must be covered by a verified range: 0 … total, no gaps
    pos = 0
    for r in sorted(state.get("sent_ranges", []), key=lambda r: r["offset"]):
        if r["offset"] != pos:
            raise FatalError(f"Byte {pos} se {r['offset']} tak ki tasdeeq ka record nahi — upload roka gaya.")
        pos += r["length"]
    if pos != total:
        raise FatalError("Bheje gaye bytes ka record poori file ko nahi dhaanpta — upload roka gaya.")
    return state
