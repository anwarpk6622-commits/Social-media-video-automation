"""SHA-256 fingerprints. An approval is valid only for exactly these bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def sha256_json(obj) -> str:
    """Stable hash of metadata (key order and spacing do not matter)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def file_entry(project_root: Path, rel: str) -> dict:
    p = project_root / rel
    if not p.is_file():
        return {"path": rel, "sha256": None, "bytes": 0, "missing": True}
    return {"path": rel, "sha256": sha256_file(p), "bytes": p.stat().st_size}


def current_fingerprints(project_root: Path, job) -> dict:
    """Re-compute what the job points at right now."""
    return {
        "files": {role: (sha256_file(project_root / f["path"]) if (project_root / f["path"]).is_file() else None)
                  for role, f in job.files.items()},
        "metadata": sha256_json(job.metadata),
        "privacy": job.privacy,
        "schedule": job.schedule,
    }


def approved_fingerprints(job) -> dict:
    return {
        "files": {role: f["sha256"] for role, f in job.files.items()},
        "metadata": job.metadata_sha256,
        "privacy": job.privacy,
        "schedule": job.schedule,
    }


def differences(expected: dict, actual: dict) -> list[str]:
    """Human-readable list of what changed since approval (empty = identical)."""
    out = []
    for role, sha in expected.get("files", {}).items():
        now = actual.get("files", {}).get(role)
        if now is None:
            out.append(f"{role}: file ghayab hai")
        elif now != sha:
            out.append(f"{role}: file badal gayi (fingerprint {str(sha)[:10]}… → {now[:10]}…)")
    for k in ("metadata", "privacy", "schedule"):
        if expected.get(k) != actual.get(k):
            out.append(f"{k}: approval ke baad badla")
    return out
