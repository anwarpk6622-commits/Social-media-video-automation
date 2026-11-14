"""Live-publishing guard (security fix 3).

Before this fix ONE switch (`live_enabled`) stood between the framework and a real
upload. Now a real (non-offline) upload needs ALL of these, checked before any
state change and before any adapter call:

1. The platform is not hard-blocked in code (Facebook Reels and TikTok are blocked
   until their own phases are approved — no setting can unblock them).
2. `live_enabled` is true in config/publishing.json AND in config/settings.json.
3. The platform's own switch `platforms_live.<platform>` is true.
4. With `private_only` (default true) the job must use the safest privacy level.
5. A separate typed confirmation at upload time: `UPLOAD <job-id>`, shown together
   with the final video, title, thumbnail and privacy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .models import PRIVACY

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "publishing.json"

# Code-level block: changing a setting cannot enable these.
HARD_BLOCKED = {
    "facebook_reels": "Facebook Reels ka phase (6.3) abhi manzoor nahi hua.",
    "tiktok": "TikTok ka phase (6.4) abhi manzoor nahi hua.",
}

SAFE_DEFAULTS = {"live_enabled": False, "platforms_live": {p: False for p in PRIVACY}, "private_only": True}


class GuardError(RuntimeError):
    pass


def load_config(path: Path | None = None) -> dict:
    p = path or CONFIG
    cfg = json.loads(json.dumps(SAFE_DEFAULTS))
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        cfg["live_enabled"] = data.get("live_enabled") is True          # anything but literal true = off
        cfg["private_only"] = data.get("private_only") is not False     # anything but literal false = on
        for k, v in (data.get("platforms_live") or {}).items():
            if k in cfg["platforms_live"]:
                cfg["platforms_live"][k] = v is True
    return cfg


def settings_live_enabled() -> bool:
    try:
        from pipeline.config import load_settings
        return load_settings().get("publishing", {}).get("live_enabled") is True
    except Exception:
        return False


def check_live(job, cfg: dict | None = None, *, settings_live: bool | None = None) -> None:
    """Raise GuardError unless a REAL upload of this job is allowed right now."""
    cfg = cfg if cfg is not None else load_config()
    settings_live = settings_live_enabled() if settings_live is None else settings_live
    if job.platform in HARD_BLOCKED:
        raise GuardError(f"⛔ {job.platform}: {HARD_BLOCKED[job.platform]} Koi upload koshish nahi hogi.")
    if not (cfg["live_enabled"] and settings_live):
        raise GuardError("⛔ Asal publishing band hai (live_enabled = false).")
    if not cfg["platforms_live"].get(job.platform):
        raise GuardError(f"⛔ {job.platform} ka switch band hai (platforms_live.{job.platform} = false).")
    if cfg["private_only"] and job.privacy != PRIVACY[job.platform][0]:
        raise GuardError(f"⛔ private_only: sirf '{PRIVACY[job.platform][0]}' allowed — yeh job '{job.privacy}' hai.")


def final_preview(project_root: Path, job) -> str:
    """What the user sees right before the separate UPLOAD confirmation."""
    m = job.metadata
    lines = ["══════ AAKHRI TASDEEQ — ASAL UPLOAD ══════",
             f"Job       : {job.id}  ({job.platform})",
             f"Privacy   : {job.privacy}",
             f"Video     : {job.files['video']['path']}  ({job.files['video']['bytes'] / 1024 ** 2:.1f} MB)",
             f"            sha256 {job.files['video']['sha256']}"]
    if "thumbnail" in job.files:
        lines += [f"Thumbnail : {job.files['thumbnail']['path']}", f"            sha256 {job.files['thumbnail']['sha256']}"]
    if m.get("title"):
        lines.append(f"Title     : {m['title']}")
    if m.get("caption"):
        lines.append(f"Caption   : {m['caption'].splitlines()[0]}")
    lines.append(f"Schedule  : {job.schedule or 'foran'}")
    lines.append("══════════════════════════════════════════")
    return "\n".join(lines)


def confirm_upload(project_root: Path, job, confirm_fn: Callable[[str], str] | None) -> None:
    if confirm_fn is None:
        raise GuardError("⛔ Asal upload ke liye alag tasdeeq zaroori hai — koi tasdeeq ka zariya nahi diya gaya.")
    print(final_preview(project_root, job))
    word = f"UPLOAD {job.id}"
    if confirm_fn(f"Asal upload ke liye bilkul yeh likhein: '{word}': ").strip() != word:
        raise GuardError("❎ Upload ki tasdeeq nahi hui. Kuch upload nahi hua.")
