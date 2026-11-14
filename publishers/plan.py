"""Build publishing jobs from the Phase 5 publishing kit (read-only use of Phase 5 files)."""

from __future__ import annotations

import copy
import datetime as _dt
import json
from pathlib import Path

from .fingerprint import file_entry, sha256_json
from .log import PublishLog
from .models import COMPLETED, PENDING, PRIVACY, Job
from .store import JobStore

PLATFORMS = ("youtube", "youtube_shorts", "facebook_reels", "tiktok")


class PlanError(ValueError):
    pass


def parse_schedule(value: str | None) -> str | None:
    if not value:
        return None
    try:
        when = _dt.datetime.fromisoformat(value)
    except ValueError as e:
        raise PlanError(f"Schedule ka waqt samajh nahi aaya: '{value}'. Misaal: 2026-12-02T19:00") from e
    return when.isoformat(timespec="minutes")


def build_job(project_root: Path, platform: str, metadata: dict, privacy: str | None, schedule: str | None) -> Job:
    if platform not in PLATFORMS:
        raise PlanError(f"Na-maloom platform: {platform}. Mumkin: {', '.join(PLATFORMS)}")
    allowed = PRIVACY[platform]
    privacy = privacy or allowed[0]                       # safe default: private / draft / only-me
    if privacy not in allowed:
        raise PlanError(f"{platform} ke liye privacy '{privacy}' nahi. Mumkin: {', '.join(allowed)}")
    m = copy.deepcopy(metadata)
    files = {"video": file_entry(project_root, m["video_file"])}
    if m.get("thumbnail_file"):
        files["thumbnail"] = file_entry(project_root, m["thumbnail_file"])
    return Job(id=platform, project=project_root.name, platform=platform, privacy=privacy,
               schedule=parse_schedule(schedule), files=files, metadata=m, metadata_sha256=sha256_json(m))


def _same_plan(a: Job, b: Job) -> bool:
    return ({r: f["sha256"] for r, f in a.files.items()} == {r: f["sha256"] for r, f in b.files.items()}
            and a.metadata_sha256 == b.metadata_sha256 and a.privacy == b.privacy and a.schedule == b.schedule)


def make_plan(project_root: Path, platforms: list[str] | None = None, *, privacy: dict | None = None,
              schedule: str | None = None) -> list[dict]:
    """Create or update one job per platform. Idempotent: an unchanged plan changes nothing.

    Returns a list of {job, action} where action is created / unchanged / replanned / completed."""
    mfile = project_root / "metadata" / "metadata.json"
    if not mfile.exists():
        raise PlanError(f"Phase 5 metadata nahi mili. Pehle: python run.py publish-kit {project_root.name}")
    meta = json.loads(mfile.read_text(encoding="utf-8"))
    store, log = JobStore(project_root), PublishLog(project_root)
    out = []
    for p in platforms or PLATFORMS:
        if p not in meta:
            raise PlanError(f"metadata.json mein '{p}' ka hissa nahi.")
        new = build_job(project_root, p, meta[p], (privacy or {}).get(p), schedule)
        if store.exists(new.id):
            with store.lock(new.id):
                old = store.load(new.id)
                if old.status == COMPLETED:
                    out.append({"job": old, "action": "completed"})   # never re-publish a finished job
                    continue
                if _same_plan(old, new):
                    out.append({"job": old, "action": "unchanged"})
                    continue
                # something changed → keep history, drop validation + approval, back to pending
                new.history = old.history
                new.created = old.created
                new.version = old.version + 1
                new.status = old.status
                if old.status != PENDING:
                    new.move(PENDING, "plan badla (files / metadata / privacy / schedule)")
                new.validation, new.approval, new.upload = {}, {}, {}
                store.save(new)
                store.clear_private(new.id)
                log.write("job_replanned", new.id, version=new.version, privacy=new.privacy)
                out.append({"job": new, "action": "replanned"})
        else:
            new.history.append({"from": None, "to": PENDING, "time": new.created, "reason": "plan bana"})
            store.save(new)
            log.write("job_created", new.id, platform=p, privacy=new.privacy, schedule=new.schedule,
                      files={r: {"path": f["path"], "sha256": f["sha256"]} for r, f in new.files.items()})
            out.append({"job": new, "action": "created"})
    return out
