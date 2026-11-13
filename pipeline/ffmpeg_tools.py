"""Helpers around ffmpeg / ffprobe (both are free, open-source tools)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise FFmpegError(
                f"'{tool}' nahi mila. Install karein: Ubuntu par 'sudo apt install ffmpeg', "
                "Windows/Mac par https://ffmpeg.org/download.html"
            )


def run_ffmpeg(args: list[str], *, capture: bool = True) -> subprocess.CompletedProcess:
    """Run ffmpeg with safe defaults. Never overwrites by accident: callers pass -y
    only for files inside generated output folders."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", *args]
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-1500:]
        raise FFmpegError(f"FFmpeg fail hua:\n{' '.join(cmd)}\n---\n{tail}")
    return proc


def probe(path: Path) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"File parhi nahi ja saki (shayad kharab ya ghalat format): {path}\n{proc.stderr}")
    return json.loads(proc.stdout)


def audio_info(path: Path) -> dict:
    """Duration, sample rate, channels, codec of the first audio stream."""
    data = probe(path)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if audio is None:
        raise FFmpegError(f"Is file mein koi awaaz (audio track) nahi hai: {path}")
    has_video = any(
        s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic", 0) == 0
        for s in data.get("streams", [])
    )
    return {
        "duration_seconds": round(float(data.get("format", {}).get("duration", 0.0)), 2),
        "sample_rate": int(audio.get("sample_rate", 0) or 0),
        "channels": int(audio.get("channels", 0) or 0),
        "codec": audio.get("codec_name", "?"),
        "has_video": has_video,
    }


_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def parse_loudnorm_json(stderr: str) -> dict:
    """loudnorm prints a JSON block to stderr; take the last one."""
    blocks = _JSON_BLOCK.findall(stderr)
    if not blocks:
        raise FFmpegError("Loudness measurement nahi mili (loudnorm output khaali).")
    return json.loads(blocks[-1])


def has_filter(name: str) -> bool:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in proc.stdout.splitlines() if line.strip())
