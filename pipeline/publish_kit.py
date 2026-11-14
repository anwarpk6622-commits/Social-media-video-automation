"""Phase 5: platform-specific titles, descriptions, hashtags and thumbnails.

Free and local: no API, no upload. Everything is built from what the project
already has (script.md, edit.json, the edited video) and written as files you
can read, edit and copy-paste:

    metadata/metadata.json        all platforms (edit this if you want)
    metadata/metadata.md          copy-paste ready, per platform
    metadata/prompt.txt           optional: ask claude.ai (free) for more title ideas
    output/thumbnails/youtube_thumbnail_1280x720.jpg
    output/thumbnails/cover_9x16_1080x1920.jpg   (TikTok / Reels / Shorts)
    output/thumbnails/candidates.jpg             (top frames the system considered)

Platform limits used are conservative "safe" values (config/settings.json →
publishing.platforms) — platforms change them from time to time.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path

from .config import load_settings
from .ffmpeg_tools import probe, run_ffmpeg
from .project import Project
from .script_writer import parse_sections

PLATFORMS = ("youtube", "youtube_shorts", "facebook_reels", "tiktok")
LABELS = {
    "youtube": "YouTube (16:9)",
    "youtube_shorts": "YouTube Shorts (9:16)",
    "facebook_reels": "Facebook Reels (9:16)",
    "tiktok": "TikTok (9:16)",
}


# ------------------------------------------------------------------ text helpers
def normalize_hashtags(raw: str | list[str]) -> list[str]:
    """'#Dubai, UAE National Day #دبئی' → ['#Dubai', '#UAENationalDay', '#دبئی'] (no duplicates)."""
    items = raw if isinstance(raw, list) else re.split(r"[\s,،]+(?=#)|\n|,|،", raw)
    out, seen = [], set()
    for it in items:
        it = it.strip()
        if not it:
            continue
        for part in (re.split(r"\s+(?=#)", it) if it.count("#") > 1 else [it]):
            tag = re.sub(r"[^\w؀-ۿ]", "", part.replace(" ", ""), flags=re.U)
            if not tag or tag.isdigit():
                continue
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                out.append("#" + tag)
    return out


def english_phrases(hashtags: list[str]) -> list[str]:
    """#UAENationalDay → 'UAE National Day' (for search-friendly English keywords)."""
    out = []
    for h in hashtags:
        t = h.lstrip("#")
        if re.fullmatch(r"[A-Za-z0-9_]+", t):
            out.append(re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", t).replace("_", " "))
    return out


def clean(text: str) -> str:
    """YouTube rejects '<' and '>' in titles/descriptions; also tidy spaces."""
    text = text.replace("<", "‹").replace(">", "›")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def first_titles(section: str) -> list[str]:
    titles = []
    for line in section.splitlines():
        line = re.sub(r"^\s*(\d+[.)]|[-•*])\s*", "", line).strip()
        if line:
            titles.append(line)
    return titles


def split_two_lines(text: str) -> tuple[str, str]:
    """2-line split for big thumbnail text (2nd line gets the accent colour).

    'A|B' = your own line break. Otherwise: as balanced as possible, but line 2 never
    starts with a tiny word («ڈے»، «کی»، «سے») — that would tear «نیشنل ڈے» apart."""
    if "|" in text:
        a, b = text.split("|", 1)
        return a.strip(), b.strip()
    words = text.split()
    if len(words) < 3:
        return text, ""
    ok = [k for k in range(1, len(words)) if len(re.sub(r"[^\w؀-ۿ]", "", words[k])) > 2] or list(range(1, len(words)))
    best = min(ok, key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
    return " ".join(words[:best]), " ".join(words[best:])


# ------------------------------------------------------------------ gather
def gather(project: Project) -> dict:
    s = load_settings()
    script_file = project.script_dir / "script.md"
    sec = parse_sections(script_file.read_text(encoding="utf-8")) if script_file.exists() else {}
    plan_file = project.path / "edit.json"
    plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.exists() else {}
    titles = first_titles(sec.get("TITLES", ""))
    plan_title = (plan.get("title") or {}).get("text", "")
    if plan_title and plan_title not in titles:
        titles.insert(0, plan_title)
    if not titles:
        titles = [project.load_meta().get("name", project.path.name)]
    hashtags = normalize_hashtags(sec.get("HASHTAGS", "")) + normalize_hashtags(s["publishing"].get("extra_hashtags", []))
    return {
        "titles": titles,
        "hook": sec.get("HOOK", "").strip(),
        "description": sec.get("DESCRIPTION", "").strip(),
        "hashtags": normalize_hashtags(hashtags),
        "location": (plan.get("title") or {}).get("tag", ""),
        "cta": s["publishing"]["call_to_action_ur"],
        "follow": s["publishing"]["follow_line_ur"],
    }


# ------------------------------------------------------------------ metadata
def _join_tags(tags: list[str]) -> str:
    return " ".join(tags)


def build_metadata(info: dict, title_index: int = 0) -> dict:
    cfg = load_settings()["publishing"]["platforms"]
    urdu_title = info["titles"][min(title_index, len(info["titles"]) - 1)]
    tags = info["hashtags"]
    eng = english_phrases(tags)
    loc = f"📍 {info['location']}" if info["location"] else ""

    # YouTube long: Urdu title + English keywords (search) if it stays short enough
    yt_title = urdu_title
    if eng:
        cand = f"{urdu_title} | {' • '.join(eng[:2])}"
        if len(cand) <= cfg["youtube"]["title_ideal"]:
            yt_title = cand
    yt_tags_list, total, seen = [], 0, set()
    for t in [*eng, *(h.lstrip("#") for h in tags), urdu_title]:
        key = re.sub(r"[\s_]", "", t).lower()  # 'UAE National Day' == 'UAENationalDay'
        if t and key not in seen and total + len(t) + 1 <= cfg["youtube"]["tags_chars_max"]:
            seen.add(key)
            yt_tags_list.append(t)
            total += len(t) + 1
    yt_hash = tags[: cfg["youtube"]["hashtags_max"]]
    youtube = {
        "title": clean(yt_title),
        "description": clean("\n\n".join(x for x in [info["hook"], info["description"], loc, info["cta"],
                                                       _join_tags(yt_hash)] if x)),
        "hashtags": yt_hash,
        "tags": yt_tags_list,
        "video_file": "output/final_16x9.mp4",
        "thumbnail_file": "output/thumbnails/youtube_thumbnail_1280x720.jpg",
    }

    shorts_hash = (["#Shorts"] + [t for t in tags if t.lower() != "#shorts"])[: cfg["youtube_shorts"]["hashtags_max"]]
    # '#Shorts' goes in the description only: at the end of an Urdu (right-to-left) title
    # some apps show it as 'Shorts#'. YouTube does not need it in the title.
    shorts_title = urdu_title
    youtube_shorts = {
        "title": clean(shorts_title),
        "description": clean("\n\n".join(x for x in [info["hook"], loc, info["cta"], _join_tags(shorts_hash)] if x)),
        "hashtags": shorts_hash,
        "video_file": "output/final_9x16.mp4",
        "thumbnail_file": "output/thumbnails/cover_9x16_1080x1920.jpg",
    }

    short_tags = tags[: cfg["facebook_reels"]["hashtags_ideal"]]
    facebook_reels = {
        "title": clean(urdu_title),
        "caption": clean("\n\n".join(x for x in [info["hook"], info["description"], loc, info["follow"],
                                                   _join_tags(short_tags)] if x)),
        "hashtags": short_tags,
        "video_file": "output/final_9x16.mp4",
        "thumbnail_file": "output/thumbnails/cover_9x16_1080x1920.jpg",
    }

    tt_tags = tags[: cfg["tiktok"]["hashtags_ideal"]]
    tiktok = {
        "caption": clean("\n".join(x for x in [f"{urdu_title} — {info['hook']}" if info["hook"] else urdu_title,
                                                 loc, _join_tags(tt_tags)] if x)),
        "hashtags": tt_tags,
        "video_file": "output/final_9x16.mp4",
        "thumbnail_file": "output/thumbnails/cover_9x16_1080x1920.jpg",
    }
    return {"youtube": youtube, "youtube_shorts": youtube_shorts, "facebook_reels": facebook_reels, "tiktok": tiktok}


def validate(meta: dict) -> dict:
    """Per platform: list of {ok, level, msg}. level: error (must fix) / warn (better to fix) / ok."""
    cfg = load_settings()["publishing"]["platforms"]
    res: dict[str, list[dict]] = {}

    def add(p, ok, msg, level="error"):
        res.setdefault(p, []).append({"ok": bool(ok), "level": "ok" if ok else level, "msg": msg})

    for p in ("youtube", "youtube_shorts"):
        m, c = meta[p], cfg[p]
        add(p, 0 < len(m["title"]) <= c["title_max"], f"Title {len(m['title'])}/{c['title_max']} haroof")
        add(p, len(m["title"]) <= c["title_ideal"], f"Title {c['title_ideal']} se chhota ho to poora dikhta hai", "warn")
        add(p, len(m["description"]) <= c["description_max"], f"Description {len(m['description'])}/{c['description_max']}")
        add(p, "<" not in m["title"] + m["description"] and ">" not in m["title"] + m["description"],
            "< aur > ke nishaan nahi (YouTube mana karta hai)")
        add(p, len(m["hashtags"]) <= c["hashtags_max"], f"Hashtags {len(m['hashtags'])}/{c['hashtags_max']} (zyada hon to YouTube sab ignore karta hai)")
    if "tags" in meta["youtube"]:
        n = sum(len(t) + 1 for t in meta["youtube"]["tags"])
        add("youtube", n <= cfg["youtube"]["tags_chars_max"], f"Tags {n}/{cfg['youtube']['tags_chars_max']} haroof")
    add("youtube_shorts", "#shorts" in meta["youtube_shorts"]["description"].lower(), "#Shorts description mein mojood", "warn")
    for p in ("facebook_reels", "tiktok"):
        m, c = meta[p], cfg[p]
        add(p, 0 < len(m["caption"]) <= c["caption_max"], f"Caption {len(m['caption'])}/{c['caption_max']} haroof")
        first_line = m["caption"].split("\n")[0]
        add(p, len(first_line) <= c["caption_ideal"], f"Pehli line {len(first_line)}/{c['caption_ideal']} (\"more\" se pehle dikhti hai)", "warn")
        add(p, 1 <= len(m["hashtags"]) <= c["hashtags_ideal"], f"Hashtags {len(m['hashtags'])} (behtar: 3–{c['hashtags_ideal']})", "warn")
    return res


def to_markdown(meta: dict, checks: dict) -> str:
    out = ["# Publishing kit — copy-paste ready", "",
           "> Har platform par khud paste karein. Yeh system KUCH BHI upload / publish nahi karta.", ""]
    for p in PLATFORMS:
        m = meta[p]
        out += [f"## {LABELS[p]}", "", f"**Video:** `{m['video_file']}`  ·  **Thumbnail / cover:** `{m['thumbnail_file']}`", ""]
        if "title" in m:
            out += ["**Title**", "```", m["title"], "```"]
        if "description" in m:
            out += ["**Description**", "```", m["description"], "```"]
        if "caption" in m:
            out += ["**Caption**", "```", m["caption"], "```"]
        if m.get("tags"):
            out += ["**Tags** (YouTube Studio → Show more → Tags)", "```", ", ".join(m["tags"]), "```"]
        if m.get("cover_timestamp_ms") is not None:
            out += [f"**Cover frame:** {m['cover_timestamp_ms'] / 1000:.1f}s"]
        out += ["", "**Jaanch:** " + " · ".join(("✅ " if c["ok"] else ("⚠️ " if c["level"] == "warn" else "❌ ")) + c["msg"]
                                              for c in checks.get(p, [])), ""]
    return "\n".join(out) + "\n"


def claude_prompt(info: dict, meta: dict) -> str:
    return (
        "=== Optional (FREE): yeh text https://claude.ai ki nayi chat mein paste karein ===\n\n"
        "You are a social media expert for Urdu-speaking audiences in Pakistan and the Gulf.\n"
        "Suggest better, honest (no clickbait lies) metadata for this video. Write in Urdu script, "
        "with a few English search keywords where natural.\n\n"
        f"VIDEO HOOK: {info['hook']}\nDESCRIPTION: {info['description']}\nLOCATION: {info['location']}\n"
        f"CURRENT TITLE: {meta['youtube']['title']}\nHASHTAGS: {' '.join(info['hashtags'])}\n\n"
        "Give: 5 YouTube titles (max 70 characters), 3 TikTok captions (first line max 150 characters), "
        "3 Facebook Reels captions, 10 hashtags (Urdu + English), and 3 short thumbnail texts (max 4 Urdu words).\n"
    )


def _hash_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_metadata(project: Project, *, title_index: int = 0, force: bool = False) -> dict:
    mdir = project.path / "metadata"
    mdir.mkdir(exist_ok=True)
    jf, state_f = mdir / "metadata.json", mdir / "state.json"
    if jf.exists() and state_f.exists():
        st = json.loads(state_f.read_text(encoding="utf-8"))
        if st.get("json_hash") != _hash_file(jf):
            if not force:
                raise FileExistsError("Aap ne metadata.json haath se edit ki hai. Dobara banane se tabdeeliyan mit jaayengi — "
                                      "naya banana ho to --force (purani file ka backup ban jaayega). "
                                      "Sirf copy-paste file update karni ho to: python run.py metadata <project> --refresh")
            jf.rename(mdir / f"metadata.backup-{_dt.datetime.now():%Y%m%d-%H%M%S}.json")
    info = gather(project)
    meta = build_metadata(info, title_index)
    # keep the chosen cover time (from `thumbnail`) for platforms that use it
    tj = mdir / "thumbnail.json"
    if tj.exists():
        t = json.loads(tj.read_text(encoding="utf-8"))
        for p in ("youtube_shorts", "facebook_reels", "tiktok"):
            meta[p]["cover_timestamp_ms"] = int(round(t["time"] * 1000))
    return _save(project, meta, info)


def refresh_from_json(project: Project) -> dict:
    """User edited metadata.json → re-check it and rebuild metadata.md (keeps the edits)."""
    mdir = project.path / "metadata"
    meta = json.loads((mdir / "metadata.json").read_text(encoding="utf-8"))
    return _save(project, meta, gather(project), keep_json=True)


def _save(project: Project, meta: dict, info: dict, keep_json: bool = False) -> dict:
    mdir = project.path / "metadata"
    checks = validate(meta)
    jf = mdir / "metadata.json"
    if not keep_json:
        jf.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (mdir / "metadata.md").write_text(to_markdown(meta, checks), encoding="utf-8")
    (mdir / "prompt.txt").write_text(claude_prompt(info, meta), encoding="utf-8")
    (mdir / "state.json").write_text(json.dumps({"json_hash": _hash_file(jf), "checks": checks,
                                                 "time": _dt.datetime.now().isoformat(timespec="seconds")},
                                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"meta": meta, "checks": checks, "dir": mdir}


# ------------------------------------------------------------------ thumbnails
def _frames_rgb(src: Path, times: list[float], w: int = 90, h: int = 160):
    import numpy as np
    out = []
    for t in times:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
                              "-vf", f"scale={w}:{h},format=rgb24", "-f", "rawvideo", "-"], capture_output=True).stdout
        out.append(np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(float) if len(raw) == w * h * 3 else None)
    return out


def score_frame(rgb) -> dict:
    """Higher = better thumbnail: sharp (not motion-blurred), colourful, well exposed."""
    import numpy as np
    g = rgb.mean(axis=2)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    sharp = float(lap.var())
    r, gg, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    rg, yb = r - gg, 0.5 * (r + gg) - b
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    bright = float(g.mean() / 255)
    exposure = 1 - min(1.0, abs(bright - 0.52) / 0.35)
    # Edge intrusion: something very close to the lens (an arm, a shoulder, half a face)
    # shows up as a big, smooth, not-bright area touching the left/right edge.
    gy, gx = np.abs(np.diff(g, axis=0))[:, :-1], np.abs(np.diff(g, axis=1))[:-1, :]
    grad = gy + gx
    w = g.shape[1]
    strip = max(2, int(w * 0.15))
    intrusion = 0.0
    for sl in (slice(0, strip), slice(w - 1 - strip, w - 1)):
        smooth = grad[:, sl] < 6
        darkish = g[:-1, sl] < 0.6 * 255
        intrusion = max(intrusion, float((smooth & darkish).mean()))
    return {"sharpness": sharp, "colorfulness": colorful, "exposure": exposure, "intrusion": intrusion}


def pick_frames(src: Path, duration: float, avoid: list[tuple[float, float]], step: float = 0.5, top: int = 6) -> list[dict]:
    times = [round(t * step, 3) for t in range(int(0.5 / step), int((duration - 0.5) / step))]
    times = [t for t in times if not any(a <= t <= b for a, b in avoid)]
    frames = _frames_rgb(src, times)
    rows = [{"time": t, **score_frame(f)} for t, f in zip(times, frames) if f is not None]
    if not rows:
        raise RuntimeError("Video se frames nahi nikal sake.")

    def norm(key):
        vals = sorted(r[key] for r in rows)
        lo, hi = vals[int(0.05 * (len(vals) - 1))], vals[int(0.95 * (len(vals) - 1))]
        for r in rows:
            r[key + "_n"] = 0.0 if hi <= lo else min(1.0, max(0.0, (r[key] - lo) / (hi - lo)))
    for k in ("sharpness", "colorfulness"):
        norm(k)
    for r in rows:
        r["score"] = round(0.45 * r["sharpness_n"] + 0.35 * r["colorfulness_n"] + 0.20 * r["exposure"]
                           - 0.8 * r["intrusion"], 4)
    rows.sort(key=lambda r: -r["score"])
    picked = []
    for r in rows:  # spread the candidates out (no near-duplicates)
        if all(abs(r["time"] - p["time"]) >= 2.0 for p in picked):
            picked.append(r)
        if len(picked) == top:
            break
    return picked


def _fit_font(lines: list[str], width_px: int, max_px: int) -> int:
    """Nastaliq is wide (~0.5 em per letter): pick a size that keeps each line on one row."""
    longest = max((len(x) for x in lines if x), default=1)
    return max(48, min(max_px, int(width_px / (0.52 * longest))))


def _thumb_css(kind: str, text_w: int = 760, fs: int = 104) -> str:
    if kind == "youtube":
        return f"""
.shade{{position:absolute;inset:0;background:linear-gradient(270deg,rgba(0,0,0,.70) 0%,rgba(0,0,0,.45) 45%,rgba(0,0,0,0) 70%)}}
.box{{position:absolute;right:44px;top:0;bottom:0;width:{text_w}px;display:flex;flex-direction:column;justify-content:center;align-items:center}}
.l1,.l2{{font-size:{fs}px;line-height:1.62;text-align:center;white-space:nowrap;paint-order:stroke fill;-webkit-text-stroke:7px #000;
  text-shadow:0 6px 18px rgba(0,0,0,.7)}}
.l1{{color:#fff}}.l2{{color:#FFD60A}}
.tag{{margin-top:6px;font-size:40px;line-height:1.8;color:#fff;background:#E62117;border-radius:999px;padding:0 26px;
  box-shadow:0 6px 18px rgba(0,0,0,.45)}}
"""
    return f"""
.shade{{position:absolute;left:0;right:0;top:820px;height:760px;
  background:linear-gradient(180deg,rgba(0,0,0,0) 0%,rgba(0,0,0,.6) 30%,rgba(0,0,0,.6) 70%,rgba(0,0,0,0) 100%)}}
.box{{position:absolute;left:60px;right:60px;top:930px;display:flex;flex-direction:column;align-items:center}}
.l1,.l2{{font-size:{fs}px;line-height:1.62;text-align:center;white-space:nowrap;paint-order:stroke fill;-webkit-text-stroke:8px #000;
  text-shadow:0 6px 18px rgba(0,0,0,.7)}}
.l1{{color:#fff}}.l2{{color:#FFD60A}}
.tag{{margin-top:10px;font-size:46px;line-height:1.8;color:#fff;background:#E62117;border-radius:999px;padding:0 30px}}
"""


def _grade_at(plan: dict, t: float) -> str:
    """The same cinematic grade as the video, for one frame at edited time t."""
    from .video_edit import GRADES
    g = GRADES[(plan.get("grade") or {}).get("look", "cinematic_warm")]
    t0 = float(plan["trim"]["start"] or 0)
    soft = any(a - t0 <= t <= b - t0 for a, b in (plan.get("grade") or {}).get("soft_ranges", []))
    return ",".join([*g["base"], *(g["soft"] if soft else g["strong"])])


def make_thumbnails(project: Project, *, time: float | None = None, text: str | None = None) -> dict:
    from .video_edit import PIN_SVG, _render_cards, load_plan, stabilize
    s = load_settings()
    tcfg = s["publishing"]["thumbnail"]
    out_dir = project.path / "output" / "thumbnails"
    work = project.path / "tmp" / "thumbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    plan_file = project.path / "edit.json"
    if plan_file.exists():
        plan = load_plan(project)
        src_video = project.original_dir / plan["recording"]
        duration_src = float(probe(src_video)["format"]["duration"])
        src = stabilize(src_video, plan, project.path / "tmp" / "edit", duration_src)  # cached clean frames
        t0 = float(plan["trim"]["start"] or 0)
        total = float(probe(src)["format"]["duration"])
        avoid = [(c - t0 - 0.6, c - t0 + 0.6) for c in plan.get("cuts", [])]
        if (plan.get("end_card") or {}).get("enabled"):
            avoid.append((total - float(plan["end_card"]["seconds"]) - 0.2, total))
        grade = lambda t: _grade_at(plan, t)  # noqa: E731
        title = text or (plan.get("title") or {}).get("text") or gather(project)["titles"][0]
        tag = (plan.get("title") or {}).get("tag", "")
    else:
        vids = [project.original_dir / r["file"] for r in project.recordings()]
        vids = [v for v in vids if any(st.get("codec_type") == "video" for st in probe(v).get("streams", []))]
        if not vids:
            raise FileNotFoundError("Is project mein koi video nahi — thumbnail ke liye video chahiye.")
        src = vids[-1]
        total = float(probe(src)["format"]["duration"])
        avoid, grade = [], (lambda t: "null")  # noqa: E731
        info = gather(project)
        title, tag = text or info["titles"][0], info["location"]

    candidates = pick_frames(src, total, avoid)
    chosen_t = float(time) if time is not None else candidates[0]["time"]
    l1, l2 = split_two_lines(title)
    e = html.escape
    tag_html = f'<div class="tag">{PIN_SVG} {e(tag)}</div>' if tag else ""
    card = f'<div class="shade"></div><div class="box"><div class="l1">{e(l1)}</div>' + \
           (f'<div class="l2">{e(l2)}</div>' if l2 else "") + f"{tag_html}</div>"

    vs = next(st for st in probe(src)["streams"] if st.get("codec_type") == "video")
    src_ar = int(vs["width"]) / int(vs["height"])
    results = {}
    for kind, (W, H) in (("youtube", tcfg["youtube_size"]), ("cover", tcfg["cover_size"])):
        bg = work / f"bg_{kind}.png"
        g = grade(chosen_t)
        fg_x = 0
        if W > H and src_ar < 1:
            # 16:9 from a vertical video: sharp picture on the LEFT, the right side (blurred)
            # is free for big text — Urdu readers start on the right.
            fg_w = int(round(H * src_ar / 2) * 2)
            fg_x = 56
            text_w = W - fg_w - fg_x - 80
            vf = (f"hqdn3d=1.5:1.2:4:4,{g},split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},gblur=sigma=26,eq=brightness=-0.10:saturation=0.9[bg];"
                  f"[b]scale=-2:{H}:flags=lanczos,unsharp=5:5:0.6[fg];[bg][fg]overlay={fg_x}:0,vignette=angle=PI/5")
            css = _thumb_css(kind, text_w, _fit_font([l1, l2], text_w, 120))
        elif W > H:  # landscape source → normal 16:9 crop, text on the right
            text_w = int(W * 0.55)
            vf = (f"hqdn3d=1.5:1.2:4:4,{g},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"unsharp=5:5:0.6,vignette=angle=PI/6")
            css = _thumb_css(kind, text_w, _fit_font([l1, l2], text_w, 120))
        else:
            vf = (f"hqdn3d=1.5:1.2:4:4,{g},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                  f"scale={W}:{H}:flags=lanczos,unsharp=5:5:0.6,vignette=angle=PI/6")
            css = _thumb_css(kind, W - 120, _fit_font([l1, l2], W - 120, 118))
        run_ffmpeg(["-y", "-ss", f"{chosen_t:.3f}", "-i", str(src), "-frames:v", "1",
                    "-filter_complex", vf, "-update", "1", str(bg)])
        ov = work / f"text_{kind}.png"
        _render_cards([{"out": str(ov), "html": card}], W, H, css)
        name = "youtube_thumbnail_1280x720.jpg" if kind == "youtube" else "cover_9x16_1080x1920.jpg"
        out = out_dir / name
        for q in (2, 3, 4, 6, 8):  # keep under the size limit (YouTube: 2 MB)
            run_ffmpeg(["-y", "-i", str(bg), "-i", str(ov), "-filter_complex", "[0:v][1:v]overlay=0:0,format=yuvj420p",
                        "-frames:v", "1", "-q:v", str(q), "-update", "1", str(out)])
            if out.stat().st_size <= tcfg["max_bytes"]:
                break
        results[kind] = {"file": str(out), "size": [W, H], "bytes": out.stat().st_size}

    # contact sheet of the candidates (to choose another with --time)
    sheet = out_dir / "candidates.jpg"
    inputs, parts = [], []
    for i, c in enumerate(candidates):
        inputs += ["-ss", f"{c['time']:.3f}", "-i", str(src)]
        border = "drawbox=x=0:y=0:w=iw:h=ih:color=0xFFD60A:t=10," if abs(c["time"] - chosen_t) < 0.01 else ""
        parts.append(f"[{i}:v]scale=216:384,{border}setsar=1[c{i}]")
    n = len(candidates)
    graph = ";".join(parts) + ";" + "".join(f"[c{i}]" for i in range(n)) + (f"hstack=inputs={n}" if n > 1 else "null")
    run_ffmpeg(["-y", *inputs, "-filter_complex", graph, "-frames:v", "1", "-q:v", "3", "-update", "1", str(sheet)])

    info = {"time": chosen_t, "auto": time is None, "text": title, "tag": tag, "candidates": candidates,
            "files": results, "candidates_sheet": str(sheet),
            "created": _dt.datetime.now().isoformat(timespec="seconds")}
    (project.path / "metadata").mkdir(exist_ok=True)
    (project.path / "metadata" / "thumbnail.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n",
                                                             encoding="utf-8")
    return info
