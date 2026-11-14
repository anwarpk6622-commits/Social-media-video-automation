"""Manual approval, bound to SHA-256 fingerprints.

- Only a VALIDATED job (validation ok) can be approved.
- The user must type APPROVE. A public job additionally needs PUBLIC typed.
- The approval stores the fingerprints of the video, thumbnail, metadata, privacy
  and schedule. If ANY of them changes afterwards, the approval is revoked
  automatically before anything could be uploaded.
"""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Callable

from .fingerprint import approved_fingerprints, current_fingerprints, differences
from .log import PublishLog
from .models import APPROVED, FAILED, PENDING, VALIDATED, Job, now

APPROVE_WORD = "APPROVE"
PUBLIC_WORD = "PUBLIC"


class ApprovalError(RuntimeError):
    pass


def summary(job: Job) -> str:
    m = job.metadata
    lines = [f"┌─ {job.id}  ({job.platform})",
             f"│  Privacy : {job.privacy}{'   ⚠️ PUBLIC' if job.is_public else '   (mehfooz)'}",
             f"│  Schedule: {job.schedule or 'abhi nahi (approval ke baad chalane par)'}"]
    for field in ("title", "caption"):
        if m.get(field):
            first = m[field].split("\n")[0]
            lines.append(f"│  {field.capitalize():8}: {first[:90]}{'…' if len(first) > 90 else ''}")
    if m.get("hashtags"):
        lines.append(f"│  Hashtags: {' '.join(m['hashtags'])}")
    for role, f in job.files.items():
        lines.append(f"│  {role:8}: {f['path']}  ({f['bytes'] / 1024 ** 2:.1f} MB, sha256 {str(f['sha256'])[:12]}…)")
    v = job.validation or {}
    lines.append(f"│  Validation: {'✅ ok' if v.get('ok') else '❌'}  ·  {len(v.get('warnings', []))} warning(s)")
    for w in v.get("warnings", []):
        lines.append(f"│     ⚠️ {w}")
    lines.append("└─")
    return "\n".join(lines)


def approve(project_root: Path, store, job_id: str, *, input_fn: Callable[[str], str] = input) -> Job:
    log = PublishLog(project_root)
    with store.lock(job_id):
        job = store.load(job_id)
        if job.status != VALIDATED or not (job.validation or {}).get("ok"):
            raise ApprovalError(f"'{job_id}' abhi manzoori ke qabil nahi (haalat: {job.status}). Pehle: publish-check")
        diff = differences(approved_fingerprints(job), current_fingerprints(project_root, job))
        if diff:
            raise ApprovalError("Validation ke baad files badal gayin: " + "; ".join(diff) + " — dobara publish-plan + publish-check")
        print(summary(job))
        if input_fn(f"Is job ko manzoor karne ke liye '{APPROVE_WORD}' likhein: ").strip() != APPROVE_WORD:
            log.write("approval_declined", job_id)
            raise ApprovalError("Manzoori nahi di gayi. Kuch nahi badla.")
        public_ok = False
        if job.is_public:
            ans = input_fn(f"⚠️ Yeh video PUBLIC hogi (sab dekh sakenge). Tasdeeq ke liye '{PUBLIC_WORD}' likhein: ")
            if ans.strip() != PUBLIC_WORD:
                log.write("approval_declined", job_id, reason="public not confirmed")
                raise ApprovalError("Public tasdeeq nahi hui. Manzoori nahi di gayi.")
            public_ok = True
        job.approval = {"time": now(), "by": _who(), "method": "typed-phrase",
                        "fingerprints": approved_fingerprints(job), "privacy": job.privacy,
                        "public_confirmed": public_ok, "schedule": job.schedule}
        job.move(APPROVED, "user ne manzoori di")
        store.save(job)
        log.write("job_approved", job_id, privacy=job.privacy, public_confirmed=public_ok,
                  fingerprints=job.approval["fingerprints"])
    return job


def verify_or_revoke(project_root: Path, store, job: Job) -> list[str]:
    """Check the approved fingerprints against the files NOW. On any change the
    approval is revoked (job → pending) and the differences are returned."""
    if not job.approval:
        return ["koi manzoori nahi"]
    diff = differences(job.approval["fingerprints"], current_fingerprints(project_root, job))
    if job.is_public and not job.approval.get("public_confirmed"):
        diff.append("public tasdeeq mojood nahi")
    if diff:
        revoked = dict(job.approval, revoked=now(), reasons=diff)
        job.approval = {}
        job.validation = {}
        if job.status in (APPROVED, FAILED):
            job.move(PENDING, "manzoori radd: " + "; ".join(diff))
        job.error = {"time": now(), "type": "approval_revoked", "detail": diff, "previous_approval": revoked}
        store.save(job)
        PublishLog(project_root).write("approval_revoked", job.id, reasons=diff)
    return diff


def _who() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "local-user"
