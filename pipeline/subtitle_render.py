"""Burned-in (on-screen) Urdu subtitles.

1. Chromium renders every subtitle state as a transparent full-frame PNG
   (one per cue, or one per spoken word when word-highlighting is on).
2. An FFmpeg "concat" list says how long each PNG stays on screen.
3. FFmpeg overlays that PNG stream on the video in one pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import ROOT, load_settings
from .ffmpeg_tools import audio_info, run_ffmpeg

RENDERER_JS = Path(__file__).with_name("urdu_text_render.js")


def _timeline(cues: list[dict], total: float, highlight: bool) -> list[tuple[tuple, float, float]]:
    """List of (state, start, end). state = (words tuple, highlighted index) or () for blank."""
    out: list[tuple[tuple, float, float]] = []
    t = 0.0
    for c in cues:
        start, end = max(c["start"], t), c["end"]
        if end <= start:
            continue
        if start > t:
            out.append(((), t, start))
        words = tuple(w["text"] for w in c["words"]) or tuple(c["text"].split())
        if highlight and c["words"]:
            ws = c["words"]
            for k, w in enumerate(ws):
                s = start if k == 0 else max(start, min(w["start"], end))
                e = end if k == len(ws) - 1 else max(s, min(ws[k + 1]["start"], end))
                if e - s > 0.001:
                    out.append(((words, k), s, e))
        else:
            out.append(((words, -1), start, end))
        t = end
    if total > t:
        out.append(((), t, total))
    return out


def render_overlay(cues: list[dict], preset: dict, work_dir: Path, total: float, *, highlight: bool = True) -> Path:
    """Render all subtitle PNGs + write the FFmpeg concat list. Returns the list path."""
    s = load_settings()
    sub_cfg, fonts = s["subtitles"], s["fonts"]
    work_dir.mkdir(parents=True, exist_ok=True)
    for old in work_dir.glob("*.png"):
        old.unlink()

    timeline = _timeline(cues, total, highlight)
    names: dict[tuple, str] = {}
    items = []
    for state, _, _ in timeline:
        if state not in names:
            names[state] = f"s{len(names):05d}.png"
            words, hl = state if state else ((), -1)
            items.append({"out": str((work_dir / names[state]).resolve()), "words": list(words), "highlight": hl})

    spec = {
        "width": preset["width"], "height": preset["height"], "background": "transparent",
        "fontPath": str(ROOT / fonts["urdu_bold" if preset.get("bold", True) else "urdu_regular"]),
        "style": {
            "fontSize": preset["font_size"], "bottom": preset["bottom"], "maxWidth": preset["max_width"],
            "box": preset.get("box", False), "color": sub_cfg["colors"]["text"],
            "highlight": sub_cfg["colors"]["highlight"], "outline": sub_cfg["colors"]["outline"],
        },
        "items": items,
    }
    if shutil.which("node") is None:
        raise RuntimeError("Node.js nahi mila (Urdu subtitles ke liye zaroori). https://nodejs.org")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
        spec_path = f.name
    try:
        proc = subprocess.run(["node", str(RENDERER_JS), spec_path], capture_output=True, text=True,
                              timeout=60 + 2 * len(items))
    finally:
        os.unlink(spec_path)
    if proc.returncode != 0:
        raise RuntimeError(f"Subtitle images nahi ban sakin: {proc.stderr.strip()[-400:]}")

    lines = ["ffconcat version 1.0"]
    for state, a, b in timeline:
        lines += [f"file '{names[state]}'", f"duration {b - a:.3f}"]
    lines.append(f"file '{names[timeline[-1][0]]}'")  # concat demuxer needs the last file twice
    concat = work_dir / "overlay.ffconcat"
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat


def make_subtitle_video(audio: Path, cues: list[dict], preset: dict, out_mp4: Path, work_dir: Path,
                        *, background: Path | None = None, highlight: bool = True) -> Path:
    """Preview video: background (colour or your clip) + clean voice + Urdu subtitles."""
    total = audio_info(audio)["duration_seconds"]
    concat = render_overlay(cues, preset, work_dir, total, highlight=highlight)
    w, h = preset["width"], preset["height"]
    if background:
        bg_in = ["-stream_loop", "-1", "-i", str(background)]
        bg_fx = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,setsar=1[bg]"
    else:
        bg_in = ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0=0x101826:c1=0x2a3b58:x0=0:y0=0:x1={w}:y1={h}:speed=0.002:r=30"]
        bg_fx = "[0:v]setsar=1[bg]"
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-y", *bg_in,
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-i", str(audio),
        "-filter_complex",
        f"{bg_fx};[1:v]format=rgba[sub];[bg][sub]overlay=0:0:format=auto:eof_action=repeat,format=yuv420p[v]",
        "-map", "[v]", "-map", "2:a:0", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-r", "30",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_mp4),
    ])
    return out_mp4
