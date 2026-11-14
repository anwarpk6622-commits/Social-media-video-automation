"""Dry-run validation — checks files and metadata against platform specs. NO network.

The specs below are conservative "safe" values. Platforms change their limits;
the real limits will be confirmed from official docs / the platform's own API
(e.g. TikTok creator_info) when each adapter is built (Phase 6.2+).
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
from pathlib import Path

from .fingerprint import sha256_file
from .log import PublishLog
from .models import PENDING, PRIVACY, VALIDATED, Job

SPECS = {
    "youtube": {
        "containers": {"mov,mp4,m4a,3gp,3g2,mj2"}, "vcodecs": {"h264", "hevc", "vp9", "av1"}, "acodecs": {"aac", "mp3", "opus"},
        "min_duration": 1, "max_duration": 12 * 3600, "warn_duration": 15 * 60, "max_bytes": 256 * 1024 ** 3,
        "orientation": "any", "thumbnail": {"max_bytes": 2_000_000, "min_width": 640, "formats": {"mjpeg", "png"}},
    },
    "youtube_shorts": {
        "containers": {"mov,mp4,m4a,3gp,3g2,mj2"}, "vcodecs": {"h264", "hevc", "vp9", "av1"}, "acodecs": {"aac", "mp3", "opus"},
        "min_duration": 1, "max_duration": 180, "max_bytes": 256 * 1024 ** 3, "orientation": "vertical_or_square",
    },
    "facebook_reels": {
        "containers": {"mov,mp4,m4a,3gp,3g2,mj2"}, "vcodecs": {"h264", "hevc"}, "acodecs": {"aac"},
        "min_duration": 3, "max_duration": 90, "max_bytes": 1024 ** 3, "orientation": "9:16",
        "min_size": (540, 960), "fps": (24, 60),
    },
    "tiktok": {
        "containers": {"mov,mp4,m4a,3gp,3g2,mj2", "matroska,webm"}, "vcodecs": {"h264", "hevc", "vp8", "vp9"},
        "acodecs": {"aac", "mp3", "opus"}, "min_duration": 1, "max_duration": 600, "max_bytes": 4 * 1024 ** 3,
        "orientation": "any", "min_side": 360, "fps": (23, 60),
    },
}

TEXT_LIMITS = {  # field: (max, ideal)
    "youtube": {"title": (100, 70), "description": (5000, None)},
    "youtube_shorts": {"title": (100, 60), "description": (5000, None)},
    "facebook_reels": {"caption": (2200, None)},
    "tiktok": {"caption": (2200, None)},
}
MAX_HASHTAGS = {"youtube": 15, "youtube_shorts": 15, "facebook_reels": 30, "tiktok": 30}


def ffprobe(path: Path) -> dict:
    proc = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip()[-300:] or "ffprobe fail")
    return json.loads(proc.stdout)


def _fps(stream: dict) -> float:
    try:
        n, d = stream.get("avg_frame_rate", "0/1").split("/")
        return float(n) / float(d) if float(d) else 0.0
    except ValueError:
        return 0.0


def check_video(path: Path, platform: str) -> tuple[list[str], list[str], dict]:
    spec, errors, warnings = SPECS[platform], [], []
    try:
        info = ffprobe(path)
    except ValueError as e:
        return [f"Video parhi nahi ja saki: {e}"], [], {}
    fmt = info.get("format", {})
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(fmt.get("duration", 0) or 0)
    size = int(fmt.get("size", 0) or path.stat().st_size)
    facts = {"duration": round(dur, 2), "bytes": size, "container": fmt.get("format_name")}
    if fmt.get("format_name") not in spec["containers"]:
        errors.append(f"Container '{fmt.get('format_name')}' is platform ke liye munasib nahi")
    if v is None:
        errors.append("Video stream nahi mili")
        return errors, warnings, facts
    w, h, fps = int(v.get("width", 0)), int(v.get("height", 0)), _fps(v)
    facts.update({"width": w, "height": h, "fps": round(fps, 2), "vcodec": v.get("codec_name"),
                  "acodec": a.get("codec_name") if a else None, "pix_fmt": v.get("pix_fmt")})
    if v.get("codec_name") not in spec["vcodecs"]:
        errors.append(f"Video codec '{v.get('codec_name')}' munasib nahi")
    if a is None:
        warnings.append("Video mein aawaz nahi")
    elif a.get("codec_name") not in spec["acodecs"]:
        errors.append(f"Audio codec '{a.get('codec_name')}' munasib nahi")
    if not spec["min_duration"] <= dur <= spec["max_duration"]:
        errors.append(f"Lambai {dur:.1f}s — hadd {spec['min_duration']}–{spec['max_duration']}s")
    if spec.get("warn_duration") and dur > spec["warn_duration"]:
        warnings.append("15 minute se lambi video ke liye YouTube channel verified hona chahiye")
    if size > spec["max_bytes"]:
        errors.append(f"File bohat bari: {size / 1024 ** 2:.0f} MB")
    o = spec["orientation"]
    if o == "vertical_or_square" and w > h:
        errors.append(f"Shorts ke liye video khari (vertical) honi chahiye — yeh {w}×{h} hai")
    if o == "9:16" and abs(w / h - 9 / 16) > 0.02:
        errors.append(f"Reels ke liye 9:16 chahiye — yeh {w}×{h} hai")
    if spec.get("min_size") and (w < spec["min_size"][0] or h < spec["min_size"][1]):
        errors.append(f"Resolution kam: {w}×{h} (kam az kam {spec['min_size'][0]}×{spec['min_size'][1]})")
    if spec.get("min_side") and min(w, h) < spec["min_side"]:
        errors.append(f"Resolution kam: {w}×{h}")
    if spec.get("fps") and not spec["fps"][0] <= round(fps) <= spec["fps"][1]:
        errors.append(f"Frame rate {fps:.1f} — hadd {spec['fps'][0]}–{spec['fps'][1]}")
    if v.get("pix_fmt") not in (None, "yuv420p", "yuvj420p"):
        warnings.append(f"Pixel format {v.get('pix_fmt')} — yuv420p sab se mehfooz hai")
    return errors, warnings, facts


def check_thumbnail(path: Path, platform: str) -> tuple[list[str], list[str]]:
    spec = SPECS[platform].get("thumbnail")
    if not spec:
        return [], []
    errors, warnings = [], []
    size = path.stat().st_size
    if size > spec["max_bytes"]:
        errors.append(f"Thumbnail {size / 1e6:.1f} MB — hadd {spec['max_bytes'] / 1e6:.0f} MB")
    try:
        s = next(st for st in ffprobe(path)["streams"] if st.get("codec_type") == "video")
        if s.get("codec_name") not in spec["formats"]:
            errors.append(f"Thumbnail format '{s.get('codec_name')}' — JPG ya PNG chahiye")
        if int(s.get("width", 0)) < spec["min_width"]:
            errors.append("Thumbnail ki chaurai 640px se kam")
        if abs(int(s["width"]) / int(s["height"]) - 16 / 9) > 0.02:
            warnings.append("Thumbnail 16:9 nahi")
    except (ValueError, StopIteration, KeyError, ZeroDivisionError):
        errors.append("Thumbnail parhi nahi ja saki")
    return errors, warnings


def check_metadata(job: Job) -> tuple[list[str], list[str]]:
    errors, warnings, m = [], [], job.metadata
    for field, (mx, ideal) in TEXT_LIMITS[job.platform].items():
        text = m.get(field, "") or ""
        if not text.strip():
            errors.append(f"{field} khaali hai")
        elif len(text) > mx:
            errors.append(f"{field} {len(text)}/{mx} haroof — bohat lamba")
        elif ideal and len(text) > ideal:
            warnings.append(f"{field} {len(text)} haroof — {ideal} se chhota behtar")
        if job.platform.startswith("youtube") and ("<" in text or ">" in text):
            errors.append(f"{field} mein < ya > (YouTube mana karta hai)")
    if len(m.get("hashtags", [])) > MAX_HASHTAGS[job.platform]:
        errors.append(f"Hashtags {len(m['hashtags'])} — hadd {MAX_HASHTAGS[job.platform]}")
    return errors, warnings


def validate_job(project_root: Path, job: Job) -> dict:
    errors, warnings, facts = [], [], {}
    if job.privacy not in PRIVACY[job.platform]:
        errors.append(f"Privacy '{job.privacy}' ghalat")
    if job.is_public:
        warnings.append("PUBLIC publishing — manzoori ke waqt alag tasdeeq maangi jaayegi")
    if job.schedule:
        try:
            when = _dt.datetime.fromisoformat(job.schedule)
            if when <= _dt.datetime.now():
                errors.append("Schedule ka waqt guzar chuka hai")
        except ValueError:
            errors.append("Schedule ka waqt ghalat")
    for role, f in job.files.items():
        p = project_root / f["path"]
        if f.get("missing") or not p.is_file():
            errors.append(f"{role} file nahi mili: {f['path']}")
        elif sha256_file(p) != f["sha256"]:
            errors.append(f"{role} file plan ke baad badal gayi — dobara: publish-plan")
    if not errors:
        e, w, facts = check_video(project_root / job.files["video"]["path"], job.platform)
        errors += e
        warnings += w
        if "thumbnail" in job.files:
            e, w = check_thumbnail(project_root / job.files["thumbnail"]["path"], job.platform)
            errors += e
            warnings += w
    e, w = check_metadata(job)
    errors += e
    warnings += w
    return {"ok": not errors, "errors": errors, "warnings": warnings, "facts": facts,
            "time": _dt.datetime.now().isoformat(timespec="seconds"), "network_calls": 0}


def validate_and_store(project_root: Path, store, job_id: str) -> Job:
    log = PublishLog(project_root)
    with store.lock(job_id):
        job = store.load(job_id)
        if job.status not in (PENDING, VALIDATED):
            raise ValueError(f"Job '{job_id}' ki haalat '{job.status}' hai — sirf pending/validated jobs check hote hain.")
        job.validation = validate_job(project_root, job)
        if job.validation["ok"] and job.status == PENDING:
            job.move(VALIDATED, "dry-run validation kamyab")
        elif not job.validation["ok"] and job.status == VALIDATED:
            job.move(PENDING, "validation nakaam")
        store.save(job)
        log.write("job_validated" if job.validation["ok"] else "job_validation_failed", job_id,
                  errors=job.validation["errors"], warnings=job.validation["warnings"])
    return job
