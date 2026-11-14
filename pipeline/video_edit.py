"""Phase 4: cinematic editing of a real phone video (free tools only: FFmpeg + Chromium).

Flow
----
edit.json (the edit plan, plain text you can change)
    ↓  edit-preview
1. Audio: the voice is cleaned by Phase 2 (noise, wind rumble, clipping → -14 LUFS).
2. Subtitles: Phase 3 (Whisper timing + your script spelling).
3. Video: trim → split at scene cuts → stabilise each clip (vidstab, 2-pass)
   → denoise → cinematic grade (lighter on faces) → upscale (lanczos) → sharpen
   → zoom-punch transition at each cut → vignette.
4. Overlays (rendered by Chromium in Nastaliq): title card, subtitles, end card.
5. Formats: 9:16 (TikTok/Reels/Shorts) and 16:9 (YouTube/Facebook, blurred sides).
    ↓  you watch the preview and approve
export → output/final_9x16.mp4, output/final_16x9.mp4 (higher quality, no label)

The ORIGINAL video is only ever read. Its SHA-256 is checked before and after.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import ROOT, load_settings
from .ffmpeg_tools import probe, run_ffmpeg
from .project import Project, sha256_of

RENDERER_JS = Path(__file__).with_name("urdu_text_render.js")

FORMATS = {
    "vertical": {"w": 1080, "h": 1920, "suffix": "9x16", "label": "9:16 — TikTok / Reels / Shorts"},
    "landscape": {"w": 1920, "h": 1080, "suffix": "16x9", "label": "16:9 — YouTube / Facebook"},
}

# "Cinematic warm": gentle S-curve with soft highlight roll-off (keeps the sky),
# teal shadows / warm highlights, vibrance (boosts dull colours like the flags
# more than already-saturated skin), a little saturation and contrast.
GRADES = {
    "cinematic_warm": {
        "base": [
            "curves=master='0/0.03 0.25/0.21 0.5/0.5 0.78/0.81 1/0.96'",
            "colorbalance=rs=-0.04:gs=0.0:bs=0.05:rh=0.05:gh=0.01:bh=-0.05",
        ],
        "strong": ["vibrance=intensity=0.45", "eq=saturation=1.12:contrast=1.04"],
        "soft": ["vibrance=intensity=0.15", "eq=saturation=1.03"],
    },
    "natural": {
        "base": ["curves=master='0/0.02 0.5/0.5 1/0.97'"],
        "strong": ["vibrance=intensity=0.25"],
        "soft": ["vibrance=intensity=0.1"],
    },
}


# ------------------------------------------------------------------ plan
def default_plan(project: Project, recording: str, title: str, tag: str = "") -> dict:
    src = project.original_dir / recording
    info = probe(src)
    duration = float(info["format"]["duration"])
    return {
        "recording": recording,
        "trim": {"start": 0.0, "end": None},
        "cuts": detect_cuts(src),
        "stabilize": {"enabled": True, "shakiness": 6, "smoothing": 20, "zoom_percent": 1, "zoom_speed": 0.2},
        "grade": {"look": "cinematic_warm", "soft_ranges": []},
        "transition": {"type": "zoom_punch", "strength": 0.16, "duration": 0.45},
        "title": {"text": title, "tag": tag, "start": 0.3, "end": 4.2},
        "end_card": {"enabled": True, "line1": "ویڈیو پسند آئے تو", "line2": "لائک اور سبسکرائب کریں", "seconds": 3.0},
        "subtitles": {"enabled": True},
        "audio": {"clean": True, "noise_reduction": "medium", "highpass_hz": 100, "music": None},
        "formats": ["vertical", "landscape"],
        "fade_out_seconds": 0.6,
        "_source_duration": round(duration, 3),
        "_note": "Sab waqt (seconds) ASAL video ke hisaab se hain. Badal kar 'edit-preview' dobara chalayein.",
    }


def detect_cuts(src: Path, threshold: float = 0.3) -> list[float]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(src), "-an",
         "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    import re
    return [round(float(x), 3) for x in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def plan_path(project: Project) -> Path:
    return project.path / "edit.json"


def load_plan(project: Project) -> dict:
    p = plan_path(project)
    if not p.exists():
        raise FileNotFoundError(f"edit.json nahi mili. Pehle: python run.py edit-init {project.path.name} --title \"...\"")
    return json.loads(p.read_text(encoding="utf-8"))


def plan_hash(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ helpers
def _render_cards(items: list[dict], width: int, height: int, css: str) -> None:
    fonts = load_settings()["fonts"]
    spec = {"width": width, "height": height, "background": "transparent",
            "fontPath": str(ROOT / fonts["urdu_bold"]), "css": css, "items": items}
    if shutil.which("node") is None:
        raise RuntimeError("Node.js nahi mila (Urdu title ke liye zaroori).")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
        spec_path = f.name
    try:
        proc = subprocess.run(["node", str(RENDERER_JS), spec_path], capture_output=True, text=True, timeout=180)
    finally:
        os.unlink(spec_path)
    if proc.returncode != 0:
        raise RuntimeError(f"Title / card render fail: {proc.stderr.strip()[-400:]}")


PIN_SVG = ('<svg viewBox="0 0 24 24" width="1em" height="1em" style="vertical-align:-0.12em">'
           '<path fill="#FFD60A" d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5'
           'A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5z"/></svg>')


def _card_css(fmt: str) -> str:
    v = fmt == "vertical"
    return f"""
.title-wrap{{position:absolute;left:0;right:0;top:0;display:flex;flex-direction:column;align-items:center;
  padding:{200 if v else 70}px 40px {110 if v else 70}px;
  background:linear-gradient(180deg,rgba(0,0,0,.62) 0%,rgba(0,0,0,.45) 55%,rgba(0,0,0,0) 100%)}}
.title{{font-size:{92 if v else 78}px;line-height:1.75;color:#fff;text-align:center;
  text-shadow:0 4px 18px rgba(0,0,0,.65),0 2px 3px rgba(0,0,0,.8);paint-order:stroke fill;-webkit-text-stroke:2px rgba(0,0,0,.35)}}
.bar{{width:{220 if v else 200}px;height:6px;border-radius:3px;margin-top:{4 if v else 2}px;
  background:linear-gradient(90deg,rgba(255,214,10,0),#FFD60A 25%,#FFD60A 75%,rgba(255,214,10,0))}}
.tag{{margin-top:{16 if v else 10}px;font-size:{54 if v else 44}px;line-height:1.9;color:#fff;
  text-shadow:0 2px 10px rgba(0,0,0,.9),0 0 2px rgba(0,0,0,.9)}}
.end-wrap{{position:absolute;left:0;right:0;top:{620 if v else 250}px;display:flex;flex-direction:column;align-items:center;
  gap:{14 if v else 8}px;padding:{70 if v else 50}px 0;
  background:radial-gradient(ellipse at center,rgba(0,0,0,.55) 0%,rgba(0,0,0,.35) 45%,rgba(0,0,0,0) 72%)}}
.end1{{font-size:{76 if v else 62}px;line-height:1.85;color:#fff;
  text-shadow:0 3px 14px rgba(0,0,0,.9),0 0 3px rgba(0,0,0,.9);paint-order:stroke fill;-webkit-text-stroke:2px rgba(0,0,0,.5)}}
.end2{{font-size:{66 if v else 54}px;line-height:1.8;color:#fff;background:#E62117;border-radius:999px;
  padding:0 {48 if v else 40}px;box-shadow:0 8px 24px rgba(0,0,0,.45)}}
.label{{position:absolute;top:24px;left:24px;font:700 26px system-ui,sans-serif;color:#fff;background:rgba(220,0,0,.75);
  padding:4px 12px;border-radius:6px;direction:ltr}}
"""


def _render_overlays(plan: dict, fmt: str, work: Path, preview: bool) -> dict:
    W, H = FORMATS[fmt]["w"], FORMATS[fmt]["h"]
    e = html.escape
    items, out = [], {}
    t = plan.get("title") or {}
    if t.get("text"):
        tag = f'<div class="tag">{PIN_SVG} {e(t["tag"])}</div>' if t.get("tag") else ""
        out["title"] = work / f"title_{fmt}.png"
        items.append({"out": str(out["title"]), "html":
                      f'<div class="title-wrap"><div class="title">{e(t["text"])}</div><div class="bar"></div>{tag}</div>'})
    ec = plan.get("end_card") or {}
    if ec.get("enabled"):
        out["end"] = work / f"end_{fmt}.png"
        items.append({"out": str(out["end"]), "html":
                      f'<div class="end-wrap"><div class="end1">{e(ec["line1"])}</div><div class="end2">{e(ec["line2"])}</div></div>'})
    if preview:
        out["label"] = work / f"label_{fmt}.png"
        items.append({"out": str(out["label"]), "html": '<div class="label">PREVIEW</div>'})
    if items:
        _render_cards(items, W, H, _card_css(fmt))
    return out


# ------------------------------------------------------------------ steps
def _segments(plan: dict, duration: float) -> list[tuple[float, float]]:
    start = float(plan["trim"]["start"] or 0)
    end = float(plan["trim"]["end"] or duration)
    pts = [start] + [c for c in plan.get("cuts", []) if start + 0.3 < c < end - 0.3] + [end]
    return list(zip(pts[:-1], pts[1:]))


def stabilize(src: Path, plan: dict, work: Path, duration: float) -> Path:
    """Trim + per-clip stabilisation → one constant-30fps intermediate (video only)."""
    st = plan["stabilize"]
    key = hashlib.sha256(json.dumps(["v2", plan["trim"], plan.get("cuts"), st], sort_keys=True).encode()).hexdigest()[:12]
    out = work / f"stab_{key}.mp4"
    if out.exists():
        return out  # cached: the slow part only runs again when trim/cuts/stabilise change
    clips = []
    for k, (a, b) in enumerate(_segments(plan, duration)):
        cut = ["-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(src)]
        clip = work / f"clip{k}.mp4"
        vf = "fps=30"
        if st.get("enabled", True):
            trf = work / f"clip{k}.trf"
            run_ffmpeg(["-y", *cut, "-an", "-vf",
                        f"fps=30,vidstabdetect=shakiness={st['shakiness']}:accuracy=15:result={trf}", "-f", "null", "-"])
            # optzoom=2 = adaptive zoom: zooms in only as much as each moment needs,
            # changing slowly, so the frame edges are never empty or smeared.
            # (A fixed 6% zoom left a smeared strip at the edge in fast selfie moves.)
            vf = (f"fps=30,vidstabtransform=input={trf}:smoothing={st['smoothing']}"
                  f":optzoom=2:zoomspeed={st.get('zoom_speed', 0.2)}:zoom={st.get('zoom_percent', 1)}"
                  ":interpol=bicubic:crop=black")
        run_ffmpeg(["-y", *cut, "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
                    "-pix_fmt", "yuv420p", str(clip)])
        clips.append(clip)
    lst = work / "clips.txt"
    lst.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")
    run_ffmpeg(["-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
    return out


def _grade_chain(plan: dict) -> str:
    g = GRADES[plan["grade"].get("look", "cinematic_warm")]
    t0 = float(plan["trim"]["start"] or 0)
    soft = [(a - t0, b - t0) for a, b in plan["grade"].get("soft_ranges", [])]
    in_soft = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in soft) or "0"
    parts = list(g["base"])
    parts += [f"{f}:enable='not({in_soft})'" for f in g["strong"]]
    if soft:
        parts += [f"{f}:enable='{in_soft}'" for f in g["soft"]]
    return ",".join(parts)


def _transition(plan: dict, W: int, H: int) -> str:
    tr = plan.get("transition") or {}
    t0 = float(plan["trim"]["start"] or 0)
    cuts = [c - t0 for c in plan.get("cuts", []) if c > t0 + 0.3]
    if tr.get("type") != "zoom_punch" or not cuts:
        return ""
    s, w = float(tr.get("strength", 0.16)), float(tr.get("duration", 0.45)) / 3
    bump = "+".join(f"exp(-pow((it-{c:.3f})/{w:.3f},2))" for c in cuts)
    blur = "+".join(f"between(t,{c - 0.08:.3f},{c + 0.08:.3f})" for c in cuts)
    # Note: no `tmix` here — when it is switched on mid-video its frame buffer starts
    # empty, and an empty YUV frame is bright GREEN (found in the first preview).
    # A short Gaussian blur at the cut gives the "whip" feel safely.
    return (f",zoompan=z='1+{s}*({bump})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30"
            f",gblur=sigma=10:enable='{blur}'")


def _shift_cues(cues: list[dict], t0: float, total: float) -> list[dict]:
    """Move subtitles to the edited timeline. Words spoken in the part that was cut
    away (before t0) are removed from the text too — not just hidden."""
    out = []
    for c in cues:
        kept = [w for w in c["words"] if (w["start"] + w["end"]) / 2 >= t0]
        if not kept:
            continue
        s = max(c["start"], kept[0]["start"]) - t0
        e = c["end"] - t0
        if e <= 0.05 or s >= total:
            continue
        ws = [{**w, "start": max(0.0, w["start"] - t0), "end": max(0.0, w["end"] - t0)} for w in kept]
        out.append({**c, "start": max(0.0, s), "end": min(e, total), "words": ws,
                    "text": " ".join(w["text"] for w in kept)})
    return out


def render(project: Project, *, preview: bool = True, formats: list[str] | None = None) -> dict:
    from .audio import process_voice
    from .subtitle_render import render_overlay
    from .subtitles import attach_word_times, read_srt

    plan = load_plan(project)
    src = project.original_dir / plan["recording"]
    entry = next(r for r in project.recordings() if r["file"] == plan["recording"])
    if sha256_of(src) != entry["sha256"]:
        raise RuntimeError("KHABARDAR: original video badli hui lagti hai. Editing roki gayi.")

    work = project.path / "tmp" / "edit"
    work.mkdir(parents=True, exist_ok=True)
    duration = float(probe(src)["format"]["duration"])
    t0 = float(plan["trim"]["start"] or 0)
    t1 = float(plan["trim"]["end"] or duration)
    total = round(t1 - t0, 3)
    log: dict = {"time": _dt.datetime.now().isoformat(timespec="seconds"), "preview": preview,
                 "plan_hash": plan_hash(plan), "duration": total, "outputs": {}}

    # 1) audio (Phase 2) — the whole recording, trimmed later (keeps sync exact)
    a = plan["audio"]
    clean = project.processed_dir / f"{src.stem}_clean.wav"
    if a.get("clean", True):
        print("   🎙️ Aawaz saaf ho rahi hai…")
        process_voice(project, plan["recording"], {"noise_reduction": a.get("noise_reduction"),
                                                   "highpass_hz": a.get("highpass_hz"), "trim_silence": False})
        audio_in = clean
    else:
        audio_in = src

    # 2) subtitles (Phase 3)
    cues_all = None
    if plan["subtitles"].get("enabled"):
        words_file = project.path / "subtitles" / "words.json"
        if not words_file.exists():
            raise FileNotFoundError(f"Subtitles abhi nahi bane. Pehle: python run.py subtitles {project.path.name}")
        words = json.loads(words_file.read_text(encoding="utf-8"))["words"]
        cues_all = {k: attach_word_times(read_srt(project.path / "subtitles" / n), words)
                    for k, n in (("vertical", "urdu_vertical.srt"), ("landscape", "urdu.srt"))}

    # 3) stabilised, trimmed intermediate
    print("   🎥 Stabilization (camera ke jhatke kam)…")
    stab = stabilize(src, plan, work, duration)

    s_cfg = load_settings()["subtitles"]
    fade = float(plan.get("fade_out_seconds") or 0)
    for fmt in formats or plan["formats"]:
        W, H = FORMATS[fmt]["w"], FORMATS[fmt]["h"]
        print(f"   🎨 {FORMATS[fmt]['label']}: grade + title + subtitles…")
        cards = _render_overlays(plan, fmt, work, preview)
        inputs = ["-i", str(stab), "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", str(audio_in)]
        idx = 2
        grade = _grade_chain(plan)
        pre = f"[0:v]hqdn3d=1.5:1.2:4:4,{grade}"
        if fmt == "vertical":
            fc = f"{pre},scale={W}:{H}:flags=lanczos,unsharp=5:5:0.55{_transition(plan, W, H)},vignette=angle=PI/6[base]"
        else:
            fg_h = H
            fc = (f"{pre},split[g1][g2];"
                  f"[g1]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=28,"
                  f"eq=brightness=-0.10:saturation=0.85[bg];"
                  f"[g2]scale=-2:{fg_h}:flags=lanczos,unsharp=5:5:0.55[fg];"
                  f"[bg][fg]overlay=(W-w)/2:0{_transition(plan, W, H)},vignette=angle=PI/5[base]")
        last = "base"
        if cues_all is not None:
            cues = _shift_cues(cues_all[fmt], t0, total)
            concat = render_overlay(cues, s_cfg[fmt], work / f"subs_{fmt}", total,
                                    highlight=s_cfg.get("highlight_words", True))
            inputs += ["-f", "concat", "-safe", "0", "-i", str(concat)]
            fc += f";[{idx}:v]format=rgba[subs];[{last}][subs]overlay=0:0:eof_action=repeat[v{idx}]"
            last, idx = f"v{idx}", idx + 1
        if "title" in cards:
            ts, te = plan["title"]["start"], plan["title"]["end"]
            inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(cards["title"])]
            fc += (f";[{idx}:v]format=rgba,fade=t=in:st={ts}:d=0.6:alpha=1,fade=t=out:st={te - 0.6:.2f}:d=0.6:alpha=1[t{idx}]"
                   f";[{last}][t{idx}]overlay=0:0[v{idx}]")
            last, idx = f"v{idx}", idx + 1
        if "end" in cards:
            es = max(0.0, total - float(plan["end_card"]["seconds"]))
            inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(cards["end"])]
            fc += (f";[{idx}:v]format=rgba,fade=t=in:st={es:.2f}:d=0.5:alpha=1[e{idx}]"
                   f";[{last}][e{idx}]overlay=0:0[v{idx}]")
            last, idx = f"v{idx}", idx + 1
        if "label" in cards:
            inputs += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(cards["label"])]
            fc += f";[{last}][{idx}:v]overlay=0:0[v{idx}]"
            last, idx = f"v{idx}", idx + 1
        if fade:
            fc += f";[{last}]fade=t=out:st={total - fade:.2f}:d={fade}[vf]"
            last = "vf"
        fc += f";[{last}]format=yuv420p[vout]"
        # audio: mono voice → centred stereo (-3 dB keeps the same -14 LUFS), soft edges
        fc += (f";[1:a]aformat=channel_layouts=mono,afade=t=in:d=0.03,"
               f"afade=t=out:st={total - max(fade, 0.3):.2f}:d={max(fade, 0.3)},"
               f"pan=stereo|c0=c0|c1=c0,volume=-3.01dB,aresample=48000[aout]")

        name = f"edit_preview_{FORMATS[fmt]['suffix']}.mp4" if preview else f"final_{FORMATS[fmt]['suffix']}.mp4"
        out = (project.preview_dir if preview else project.path / "output") / name
        out.parent.mkdir(parents=True, exist_ok=True)
        enc = (["-preset", "veryfast", "-crf", "21"] if preview
               else ["-preset", "slow", "-crf", "17", "-profile:v", "high", "-level", "4.2"])
        run_ffmpeg(["-y", *inputs, "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
                    "-t", f"{total:.3f}", "-r", "30", "-c:v", "libx264", *enc,
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
        log["outputs"][fmt] = str(out)
        print(f"   ✅ {out}")

    # original must still be untouched
    if sha256_of(src) != entry["sha256"]:
        raise RuntimeError("KHABARDAR: editing ke baad original ka fingerprint badal gaya!")
    log["original_unchanged"] = True
    (project.path / ("edit_preview.json" if preview else "export.json")).write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return log
