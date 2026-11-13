"""Video projects + protection of original recordings.

Rule: an original recording is COPIED into input/original/, made read-only and
fingerprinted (SHA-256). No step of the pipeline ever writes to it. `verify`
re-computes the fingerprint at any time to prove it is unchanged.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import shutil
import stat
from pathlib import Path

from .config import PROJECTS_DIR

SUBDIRS = [
    "input/original",   # aap ki asal recordings (read-only)
    "input/clips",      # video clips / B-roll (Phase 4)
    "script",           # AI script
    "audio/processed",  # saaf ki hui awaaz (nayi files)
    "subtitles",        # Phase 3
    "output",           # Phase 5
    "preview",          # preview.html + images
]

AUDIO_VIDEO_EXT = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
    ".mp4", ".mov", ".mkv", ".webm", ".3gp", ".avi",
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    return slug or "video"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class Project:
    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self.meta_file = self.path / "project.json"

    # ---------- creation / loading ----------
    @classmethod
    def create(cls, name: str, topic: str = "", base: Path = PROJECTS_DIR) -> "Project":
        today = _dt.date.today().isoformat()
        path = Path(base) / f"{today}-{slugify(name)}"
        if path.exists():
            raise FileExistsError(f"Project pehle se mojood hai: {path}")
        for sub in SUBDIRS:
            (path / sub).mkdir(parents=True, exist_ok=True)
        proj = cls(path)
        proj.save_meta({
            "name": name,
            "topic": topic,
            "created": _dt.datetime.now().isoformat(timespec="seconds"),
            "recordings": [],
        })
        return proj

    @classmethod
    def open(cls, ref: str | Path, base: Path = PROJECTS_DIR) -> "Project":
        """Accept a full path, or just the folder name inside projects/."""
        candidates = [Path(ref), Path(base) / str(ref)]
        for c in candidates:
            if (c / "project.json").exists():
                return cls(c)
        # allow partial name match, e.g. "my-video"
        matches = sorted(p for p in Path(base).glob(f"*{ref}*") if (p / "project.json").exists())
        if len(matches) == 1:
            return cls(matches[0])
        if len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            raise FileNotFoundError(f"Kai projects milte hain ({names}). Poora naam likhein.")
        raise FileNotFoundError(f"Project nahi mila: {ref}  (pehle 'python run.py new ...' chalayein)")

    def load_meta(self) -> dict:
        return json.loads(self.meta_file.read_text(encoding="utf-8"))

    def save_meta(self, meta: dict) -> None:
        self.meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---------- folders ----------
    @property
    def original_dir(self) -> Path:
        return self.path / "input" / "original"

    @property
    def script_dir(self) -> Path:
        return self.path / "script"

    @property
    def processed_dir(self) -> Path:
        return self.path / "audio" / "processed"

    @property
    def preview_dir(self) -> Path:
        return self.path / "preview"

    # ---------- original recordings ----------
    def add_recording(self, source: Path) -> dict:
        """Copy (never move) a recording into the project and lock it."""
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Recording nahi mili: {source}")
        if source.suffix.lower() not in AUDIO_VIDEO_EXT:
            raise ValueError(f"Yeh format support nahi: {source.suffix}  (WAV, MP3, M4A, MP4 waghera chalein ge)")

        dest = self.original_dir / source.name
        if dest.exists():
            raise FileExistsError(
                f"Isi naam ki recording pehle se mojood hai: {dest.name}. "
                "Original ko overwrite nahi kiya jaata — file ka naam badal kar dobara add karein."
            )
        src_hash = sha256_of(source)
        shutil.copy2(source, dest)
        dest_hash = sha256_of(dest)
        if src_hash != dest_hash:
            dest.unlink()
            raise IOError("Copy ke dauran file kharab hui. Dobara koshish karein.")
        # read-only lock: r--r--r--
        dest.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

        entry = {
            "file": dest.name,
            "sha256": dest_hash,
            "size_bytes": dest.stat().st_size,
            "added": _dt.datetime.now().isoformat(timespec="seconds"),
        }
        meta = self.load_meta()
        meta.setdefault("recordings", []).append(entry)
        self.save_meta(meta)
        return entry

    def recordings(self) -> list[dict]:
        return self.load_meta().get("recordings", [])

    def recording_path(self, name: str | None = None) -> Path:
        recs = self.recordings()
        if not recs:
            raise FileNotFoundError("Is project mein abhi koi recording nahi. 'python run.py add-recording ...' chalayein.")
        if name is None:
            return self.original_dir / recs[-1]["file"]
        for r in recs:
            if r["file"] == name:
                return self.original_dir / r["file"]
        raise FileNotFoundError(f"Recording '{name}' is project mein nahi.")

    def verify_originals(self) -> list[dict]:
        """Return a status per original: ok / CHANGED / MISSING."""
        results = []
        for r in self.recordings():
            p = self.original_dir / r["file"]
            if not p.exists():
                status = "MISSING"
            elif sha256_of(p) != r["sha256"]:
                status = "CHANGED"
            else:
                status = "ok"
            results.append({"file": r["file"], "status": status})
        return results
