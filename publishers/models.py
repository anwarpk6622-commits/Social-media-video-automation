"""Publishing job model and its allowed status transitions."""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any

PENDING, VALIDATED, APPROVED, UPLOADING, PROCESSING, COMPLETED, FAILED = (
    "pending", "validated", "approved", "uploading", "processing", "completed", "failed")
STATUSES = (PENDING, VALIDATED, APPROVED, UPLOADING, PROCESSING, COMPLETED, FAILED)

# The only allowed moves. Anything else is a bug and is refused.
TRANSITIONS: dict[str, set[str]] = {
    PENDING: {VALIDATED, PENDING},
    VALIDATED: {APPROVED, PENDING},                    # pending again: files / metadata changed
    APPROVED: {UPLOADING, PENDING},                    # pending again: approval revoked (fingerprint changed)
    UPLOADING: {UPLOADING, PROCESSING, FAILED},        # uploading → uploading = resume
    PROCESSING: {PROCESSING, COMPLETED, FAILED},
    FAILED: {PENDING, APPROVED},                       # approved again only if fingerprints still match
    COMPLETED: set(),                                  # final: never uploaded twice
}

# Privacy levels per platform. The FIRST one is the safe default.
PRIVACY = {
    "youtube": ("private", "unlisted", "public"),
    "youtube_shorts": ("private", "unlisted", "public"),
    "facebook_reels": ("draft", "public"),
    "tiktok": ("self_only", "public"),
}
PUBLIC_LEVELS = {"public"}


class TransitionError(RuntimeError):
    pass


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    project: str
    platform: str
    status: str = PENDING
    privacy: str = ""
    schedule: str | None = None
    files: dict[str, dict] = field(default_factory=dict)        # role → {path, sha256, bytes}
    metadata: dict[str, Any] = field(default_factory=dict)       # platform section from Phase 5
    metadata_sha256: str = ""
    validation: dict[str, Any] = field(default_factory=dict)
    approval: dict[str, Any] = field(default_factory=dict)
    upload: dict[str, Any] = field(default_factory=dict)         # bytes_sent, attempts, remote_id (no secrets)
    error: dict[str, Any] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    created: str = field(default_factory=now)
    updated: str = field(default_factory=now)
    version: int = 1

    @property
    def is_public(self) -> bool:
        return self.privacy in PUBLIC_LEVELS

    def move(self, to: str, reason: str = "") -> None:
        if to not in STATUSES:
            raise TransitionError(f"Na-maloom status: {to}")
        if to not in TRANSITIONS[self.status]:
            raise TransitionError(f"Status '{self.status}' se '{to}' par jaana mana hai ({self.id}).")
        self.history.append({"from": self.status, "to": to, "time": now(), "reason": reason})
        self.status = to
        self.updated = now()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)
