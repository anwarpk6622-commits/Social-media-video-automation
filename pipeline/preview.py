"""Preview page (HTML) + Urdu Nastaliq render test.

preview/preview.html is a single local page: open it in any browser
(double-click on your computer, or `python run.py preview <project> --serve`).
Nothing is uploaded anywhere.
"""

from __future__ import annotations

import datetime as _dt
import html
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import FONTS_DIR, ROOT, load_settings
from .project import Project
from .script_writer import check_script, parse_sections

URDU_SAMPLE_LINES = [
    "السلام علیکم! میرے چینل میں خوش آمدید۔",
    "آج ہم سیکھیں گے کہ موبائل سے پروفیشنل ویڈیو کیسے بنائیں۔",
    "میرا YouTube چینل 2026 میں شروع ہوا۔",
]


RENDERER_JS = Path(__file__).with_name("urdu_text_render.js")

# Why a word is on the "please check" list (shown to the creator)
WHY = {
    "guessed": "saaf sunai nahi diya — waqt andaze se",
    "extra": "bola gaya magar script mein nahi tha (subtitle mein shamil)",
    "unclear": "kuch suna gaya magar samajh nahi aaya (subtitle mein nahi)",
    "fitted": "kam yaqeeni — awaaz script se kam milti hai",
}


def render_urdu_png(out_png: Path, lines: list[str], *, width: int = 1920, height: int = 1080,
                    font_size: int = 72, background: str = "#1d2433", bold: bool = False) -> Path:
    """Render Urdu Nastaliq lines to PNG with Chromium (Playwright via Node.js).

    Why Chromium and not FFmpeg's libass/drawtext: Nastaliq needs very complex
    shaping. Browsers handle it perfectly; some FFmpeg builds (including the
    Ubuntu 24.04 one we tested) draw empty boxes instead. Phase 3 will use this
    same function with background="transparent" to create subtitle overlays.
    """
    fonts = load_settings()["fonts"]
    font = ROOT / fonts["urdu_bold" if bold else "urdu_regular"]
    out_png = Path(out_png).resolve()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    spec = {
        "out": str(out_png), "width": width, "height": height, "fontPath": str(font),
        "fontSize": font_size, "background": background, "lines": lines,
    }
    if shutil.which("node") is None:
        raise RuntimeError("Node.js nahi mila. Install karein: https://nodejs.org (LTS)")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False)
        spec_path = f.name
    try:
        proc = subprocess.run(["node", str(RENDERER_JS), spec_path], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(spec_path)
    if proc.returncode != 0:
        raise RuntimeError(f"Urdu renderer fail hua: {proc.stderr.strip()[-400:]}")
    return out_png


def render_font_test(out_png: Path, lines: list[str] | None = None) -> Path:
    """Full-HD test frame: proves Nastaliq joining + right-to-left + mixed English/numbers."""
    return render_urdu_png(out_png, lines or URDU_SAMPLE_LINES)


# ----------------------------------------------------------------- HTML page
CSS = """
:root{--bg:#f6f7fb;--card:#fff;--text:#1d2433;--muted:#5b6475;--line:#e3e6ee;--ok:#137a3f;--bad:#b3261e;--accent:#2f6fde}
@media (prefers-color-scheme:dark){:root{--bg:#12151c;--card:#1b2029;--text:#e8ebf2;--muted:#a2abbd;--line:#2c3340;--ok:#5fd08f;--bad:#ff8a80;--accent:#7aa7ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1000px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.2rem;margin:0 0 12px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}img{max-width:100%;border-radius:8px;border:1px solid var(--line)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:700px){.grid{grid-template-columns:1fr}}
audio{width:100%}code{background:var(--bg);padding:2px 6px;border-radius:6px;font-size:.9em}
.urdu{font-family:"UrduNastaliq",serif;direction:rtl;text-align:right;font-size:1.35rem;line-height:2.4;white-space:pre-wrap}
.tip{border-left:4px solid var(--accent);padding:4px 12px}
.kv{margin:10px 0}.kvh{display:flex;gap:8px;align-items:center;margin-bottom:4px}
.copy{margin-inline-start:auto;font:600 .85rem system-ui,sans-serif;padding:4px 10px;border-radius:8px;border:1px solid var(--line);
  background:var(--bg);color:var(--text);cursor:pointer}
pre.copytext{margin:0;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px 12px;font-size:1.05rem;
  line-height:2.1;white-space:pre-wrap;word-break:break-word;unicode-bidi:plaintext;text-align:start}
details{border-top:1px solid var(--line);padding:8px 0}summary{cursor:pointer;padding:6px 0}
"""

COPY_JS = """<script>
document.addEventListener('click', async (ev) => {
  const b = ev.target.closest('button.copy'); if (!b) return;
  const pre = b.closest('.kv').querySelector('pre.copytext');
  try { await navigator.clipboard.writeText(pre.innerText); b.textContent = '✅ Copied'; }
  catch (e) { const r = document.createRange(); r.selectNodeContents(pre);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r); b.textContent = 'Ctrl+C dabayein'; }
  setTimeout(() => { b.textContent = '📋 Copy'; }, 1800);
});
</script>"""


def _fmt_time(t: float | None) -> str:
    return "—" if t is None else f"{t:.1f}s"


def _rel(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target, start)).as_posix()


def _status(ok: bool, yes: str = "✅ OK", no: str = "❌") -> str:
    return f'<span class="{"ok" if ok else "bad"}">{yes if ok else no}</span>'


def build_preview(project: Project) -> Path:
    pv = project.preview_dir
    pv.mkdir(parents=True, exist_ok=True)
    meta = project.load_meta()
    settings = load_settings()
    font_url = _rel(FONTS_DIR / Path(settings["fonts"]["urdu_regular"]).name, pv)
    e = html.escape
    parts: list[str] = []

    # --- originals
    verify = project.verify_originals()
    rows = "".join(
        f"<tr><td>{e(v['file'])}</td><td>{_status(v['status'] == 'ok', '✅ Bilkul unchanged', '❌ ' + v['status'])}</td></tr>"
        for v in verify
    ) or '<tr><td colspan="2" class="muted">Abhi koi recording add nahi hui.</td></tr>'
    parts.append(f'<section class="card"><h2>🔒 Original recordings (hifazat)</h2>'
                 f'<table><tr><th>File</th><th>SHA-256 check</th></tr>{rows}</table></section>')

    # --- audio reports
    for rep_file in sorted(project.processed_dir.glob("*_report.json")):
        r = json.loads(rep_file.read_text(encoding="utf-8"))
        o, c = r["original"], r["clean"]
        orig_url = _rel(project.original_dir / o["file"], pv)
        clean_url = _rel(project.processed_dir / c["preview_file"], pv)
        target = r["settings"]["target_lufs"]
        hit = abs(c["loudness_lufs"] - target) <= 1.0
        tp_ok = c["true_peak_db"] <= r["settings"]["true_peak_db"] + 0.5
        img = r["images"]
        parts.append(f"""
<section class="card"><h2>🎙️ Awaaz: {e(o['file'])}</h2>
<div class="grid">
 <div><b>Pehle (original)</b><audio controls preload="metadata" src="{e(orig_url)}"></audio></div>
 <div><b>Baad (saaf)</b><audio controls preload="metadata" src="{e(clean_url)}"></audio></div>
</div>
<p class="tip muted">Headphones laga kar dono sunein. Awaaz <b>aap hi ki</b> honi chahiye — sirf shor kam aur volume barabar.</p>
{f'<p class="tip">⚠️ {e(r["loudness_note"])}</p>' if r.get("loudness_note") else ''}
<table>
<tr><th></th><th>Pehle</th><th>Baad</th><th>Target</th></tr>
<tr><td>Loudness (LUFS)</td><td>{o['loudness_lufs']}</td><td>{c['loudness_lufs']}</td><td>{target} {_status(hit, '✅', '⚠️')}</td></tr>
<tr><td>True peak (dB)</td><td>{o['true_peak_db']}</td><td>{c['true_peak_db']}</td><td>≤ {r['settings']['true_peak_db']} {_status(tp_ok, '✅', '⚠️')}</td></tr>
<tr><td>Lambai (seconds)</td><td>{o['duration_seconds']}</td><td>{c['duration_seconds']}</td><td></td></tr>
<tr><td>Sample rate / channels</td><td>{o['sample_rate']} Hz / {o['channels']}</td><td>{c['sample_rate']} Hz / {c['channels']}</td><td></td></tr>
</table>
<div class="grid" style="margin-top:12px">
 <div><b>Waveform — pehle</b><img alt="waveform original" src="{e(img['original']['waveform'])}"></div>
 <div><b>Waveform — baad</b><img alt="waveform clean" src="{e(img['clean']['waveform'])}"></div>
 <div><b>Spectrogram — pehle</b><img alt="spectrogram original" src="{e(img['original']['spectrogram'])}"></div>
 <div><b>Spectrogram — baad</b><img alt="spectrogram clean" src="{e(img['clean']['spectrogram'])}"></div>
</div>
<p class="muted">Spectrogram mein awaaz ke beech ka halka "dhuan" (background shor) baad wali tasveer mein kam hona chahiye.</p>
<details><summary>Technical settings</summary><p><code>{e(', '.join(r['filter_chain']))}</code></p></details>
</section>""")

    # --- script
    script_file = project.script_dir / "script.md"
    if script_file.exists():
        chk = check_script(script_file, settings["script"]["words_per_minute"])
        if chk["sections_found"]:
            sec = parse_sections(script_file.read_text(encoding="utf-8"))
            missing = ", ".join(chk["missing_sections"]) or "koi nahi"
            facts = "".join(f"<li>{e(f)}</li>" for f in chk["facts_to_check"]) or "<li class='muted'>koi nahi</li>"
            parts.append(f"""
<section class="card"><h2>📝 Script</h2>
<table>
<tr><td>Recording script</td><td>{chk['recording_words']} alfaaz ≈ <b>{chk['recording_minutes']} minute</b></td></tr>
<tr><td>Short version</td><td>{chk['short_words']} alfaaz ≈ <b>{chk['short_seconds']} second</b> {_status(chk['short_seconds'] <= 60, '✅', '⚠️ 60 se zyada')}</td></tr>
<tr><td>Ghayab hisse</td><td>{e(missing)}</td></tr>
</table>
<p><b>In baaton ko khud check karein (facts):</b></p><ul>{facts}</ul>
<h3>Hook</h3><div class="urdu">{e(sec.get('HOOK', ''))}</div>
<h3>Recording script</h3><div class="urdu">{e(sec.get('RECORDING SCRIPT', ''))}</div>
</section>""")
        else:
            parts.append('<section class="card"><h2>📝 Script</h2><p class="muted">script.md abhi khaali hai. '
                         'prompt.txt ko claude.ai mein paste karein aur jawab script.md mein rakhein.</p></section>')

    # --- subtitles (Phase 3)
    words_file = project.path / "subtitles" / "words.json"
    if words_file.exists():
        sr = json.loads(words_file.read_text(encoding="utf-8"))["report"]
        c = sr["counts"]
        if sr["mode"] == "script+speech":
            mode = f"Script + awaaz — <b>{round(sr['match_rate'] * 100)}%</b> alfaaz bilkul match"
        elif sr.get("rejected_match_rate") is not None:
            mode = (f"⚠️ Recording script se sirf {round(sr['rejected_match_rate'] * 100)}% milti thi — "
                    "Whisper ki likhai istemal hui, spelling khud check karein")
        else:
            mode = "Sirf awaaz (script ke baghair) — spelling khud check karein"
        check_rows = "".join(
            f"<tr><td>{_fmt_time(w['time'])}</td>"
            f"<td class='urdu' style='font-size:1.1rem;line-height:1.9'>{e(w['text'])}</td>"
            f"<td>{e(WHY.get(w['why'], w['why']))}</td></tr>"
            for w in sr["to_check"]
        ) or "<tr><td colspan='3' class='ok'>✅ Koi shak wala lafz nahi</td></tr>"
        skipped = (f"<p>⏭️ Script ke yeh alfaaz recording mein nahi mile: <span class='urdu' style='font-size:1.1rem'>"
                   f"{e(' '.join(sr['skipped']))}</span></p>") if sr["skipped"] else ""
        videos = ""
        for name, label in (("subtitles_16x9.mp4", "16:9 — YouTube"), ("subtitles_9x16.mp4", "9:16 — Shorts / TikTok / Reels")):
            if (pv / name).exists():
                videos += (f'<div><b>{label}</b><video controls preload="metadata" src="{name}" '
                           f'style="width:100%;border-radius:8px;background:#000;max-height:640px"></video></div>')
        if not videos:
            videos = f"<p class='muted'>Video abhi nahi bani: <code>python run.py subtitle-video {e(project.path.name)}</code></p>"
        parts.append(f"""
<section class="card"><h2>💬 Urdu subtitles</h2>
<table>
<tr><td>Tareeqa</td><td>{mode}</td></tr>
<tr><td>Alfaaz</td><td>{c['words']} (match {c['matched']}, script se durust {c['fitted']}, andaaza {c['guessed']}, zyada {c['extra']}, chhoote {c['skipped']})</td></tr>
<tr><td>Subtitle hisse</td><td>16:9: {c['cues_landscape']} · 9:16: {c['cues_vertical']}</td></tr>
<tr><td>Whisper model</td><td>{e(str(sr.get('whisper_model')))}</td></tr>
</table>
<div class="grid" style="margin-top:12px">{videos}</div>
<h3>🔎 In alfaaz ko video mein dekh kar check karein</h3>
<table><tr><th>Waqt</th><th>Lafz</th><th>Kyun</th></tr>{check_rows}</table>
{skipped}
<p class="tip muted">Ghalti mile to <code>subtitles/urdu.srt</code> (aur <code>urdu_vertical.srt</code>) Notepad mein kholein, text ya waqt theek karein,
save karein, phir <code>python run.py subtitle-video {e(project.path.name)}</code> chalayein. Aap ki tabdeeliyan mehfooz rehti hain.</p>
</section>""")

    # --- editing preview (Phase 4)
    ep = project.path / "edit_preview.json"
    if ep.exists():
        log = json.loads(ep.read_text(encoding="utf-8"))
        plan = json.loads((project.path / "edit.json").read_text(encoding="utf-8"))
        vids = ""
        for name, label in (("edit_preview_9x16.mp4", "9:16 — TikTok / Reels / Shorts"),
                            ("edit_preview_16x9.mp4", "16:9 — YouTube / Facebook")):
            if (pv / name).exists():
                vids += (f'<div><b>{label}</b><video controls preload="metadata" src="{name}" '
                         f'style="width:100%;border-radius:8px;background:#000;max-height:680px"></video></div>')
        st, gr, tt = plan["stabilize"], plan["grade"], plan.get("title") or {}
        parts.append(f"""
<section class="card"><h2>🎬 Editing preview (Phase 4)</h2>
<div class="grid">{vids}</div>
<table style="margin-top:12px">
<tr><td>Lambai</td><td>{log['duration']} second (shuru se {plan['trim']['start']}s kaata)</td></tr>
<tr><td>Scene cuts / transition</td><td>{', '.join(f'{c}s' for c in plan.get('cuts', [])) or '—'} · {e(str((plan.get('transition') or {}).get('type')))}</td></tr>
<tr><td>Stabilization</td><td>{'on' if st.get('enabled') else 'off'} (smoothing {st.get('smoothing')}, adaptive zoom)</td></tr>
<tr><td>Color grade</td><td>{e(gr.get('look', ''))}{' · chehre par halka: ' + ', '.join(f'{a}–{b}s' for a, b in gr.get('soft_ranges', [])) if gr.get('soft_ranges') else ''}</td></tr>
<tr><td>Title</td><td class="urdu" style="font-size:1.1rem;line-height:1.9">{e(tt.get('text', ''))}</td></tr>
<tr><td>Original video</td><td>{_status(log.get('original_unchanged', False), '✅ Bilkul unchanged', '❌')}</td></tr>
</table>
<p class="tip">Pasand aaye to final high-quality files: <code>python run.py export {e(project.path.name)}</code>
(aap se "yes" poocha jaayega). Kuch badalna ho to <code>edit.json</code> badal kar <code>edit-preview</code> dobara chalayein.</p>
</section>""")

    # --- publishing kit (Phase 5)
    mjson = project.path / "metadata" / "metadata.json"
    if mjson.exists():
        from .publish_kit import LABELS, PLATFORMS, validate
        meta = json.loads(mjson.read_text(encoding="utf-8"))
        checks = validate(meta)
        thumbs = ""
        for name, label in (("youtube_thumbnail_1280x720.jpg", "YouTube thumbnail (1280×720)"),
                            ("cover_9x16_1080x1920.jpg", "TikTok / Reels / Shorts cover (1080×1920)")):
            f = project.path / "output" / "thumbnails" / name
            if f.exists():
                thumbs += f'<div><b>{label}</b><img alt="{e(label)}" src="{e(_rel(f, pv))}"></div>'
        cards = ""
        for pl in PLATFORMS:
            m = meta.get(pl, {})
            blocks = ""
            for field, flabel in (("title", "Title"), ("description", "Description"), ("caption", "Caption")):
                if m.get(field):
                    blocks += (f'<div class="kv"><div class="kvh"><b>{flabel}</b> <span class="muted">({len(m[field])} haroof)</span>'
                               f'<button class="copy" type="button">📋 Copy</button></div>'
                               f'<pre class="urdu copytext">{e(m[field])}</pre></div>')
            if m.get("tags"):
                blocks += (f'<div class="kv"><div class="kvh"><b>Tags</b><button class="copy" type="button">📋 Copy</button></div>'
                           f'<pre class="copytext">{e(", ".join(m["tags"]))}</pre></div>')
            marks = " · ".join(("✅ " if c["ok"] else ("⚠️ " if c["level"] == "warn" else "❌ ")) + e(c["msg"])
                               for c in checks.get(pl, []))
            cards += f'<details open><summary><b>{LABELS[pl]}</b></summary>{blocks}<p class="muted">{marks}</p></details>'
        parts.append(f"""
<section class="card"><h2>📦 Publishing kit (Phase 5)</h2>
<div class="grid">{thumbs}</div>
{cards}
<p class="tip">Yeh sab <b>khud copy-paste</b> karne ke liye hai. Kuch bhi upload / publish NAHI hota.
Badalna ho to <code>metadata/metadata.json</code> edit kar ke <code>python run.py metadata {e(project.path.name)} --refresh</code>.
Thumbnail ka doosra frame: <code>python run.py thumbnail {e(project.path.name)} --time 21.5</code></p>
</section>""")

    # --- publishing (Phase 6) — only shown when publishing jobs exist
    jobs_dir = project.path / "publish" / "jobs"
    if jobs_dir.exists() and any(jobs_dir.glob("*.json")):
        from publishers.fingerprint import current_fingerprints, differences
        from publishers.log import PublishLog
        from publishers.redact import redact
        from publishers.store import JobStore
        icons = {"pending": "⏳", "validated": "🔎", "approved": "✅", "uploading": "⬆️", "processing": "⚙️",
                 "completed": "🎉", "failed": "❌"}
        rows = ""
        for j in JobStore(project.path).all():
            if j.approval:
                d = differences(j.approval["fingerprints"], current_fingerprints(project.path, j))
                fp = _status(not d, "🔒 durust", "⚠️ badla: " + "; ".join(d))
            else:
                fp = "—"
            v = j.validation or {}
            vt = (_status(v.get("ok", False), "✅", "❌") + f" {len(v.get('warnings', []))} warning") if v else "—"
            rows += (f"<tr><td><code>{e(j.id)}</code></td><td>{icons.get(j.status, '')} {e(j.status)}</td>"
                     f"<td>{e(j.privacy)}{' ⚠️' if j.is_public else ''}</td><td>{vt}</td>"
                     f"<td>{e(j.approval.get('time', '—') if j.approval else '—')}</td><td>{fp}</td></tr>")
        logs = "".join(f"<li><code>{e(r.get('time', ''))}</code> {e(str(r.get('event')))} "
                       f"<span class='muted'>{e(str(r.get('job') or ''))}</span></li>"
                       for r in redact(PublishLog(project.path).read(limit=12)))
        parts.append(f"""
<section class="card"><h2>🚀 Publishing (Phase 6)</h2>
<p class="tip">Phase 6.1: sirf framework — <b>koi asal upload mumkin nahi</b>. Default privacy hamesha private / draft / only-me.</p>
<table><tr><th>Job</th><th>Status</th><th>Privacy</th><th>Validation</th><th>Manzoori</th><th>Fingerprints</th></tr>{rows}</table>
<h3>Aakhri log</h3><ul>{logs or '<li class="muted">—</li>'}</ul>
</section>""")

    # --- font test
    ft = pv / "font_test.png"
    try:
        render_font_test(ft)
        parts.append('<section class="card"><h2>🔤 Urdu font test (video frame, 1920×1080)</h2>'
                     '<p class="muted">Yeh tasveer usi engine (Chromium) se bani hai jis se Phase 3 mein subtitles '
                     'banenge. Huroof jude hue aur daayen se baayen hone chahiye.</p>'
                     f'<img alt="Urdu font render test" src="{ft.name}"></section>')
    except Exception as exc:  # keep the page usable even if this fails
        parts.append(f'<section class="card"><h2>🔤 Urdu font test</h2><p class="bad">Fail: {e(str(exc)[:300])}</p></section>')

    page = f"""<!doctype html>
<html lang="ur"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project Preview</title>
<style>@font-face{{font-family:"UrduNastaliq";src:url("{e(font_url)}") format("truetype")}}{CSS}</style></head>
<body><main>
<h1>🎬 {e(meta.get('name', project.path.name))}</h1>
<p class="muted">Topic: {e(meta.get('topic') or '—')} · Preview banaya gaya: {_dt.datetime.now():%Y-%m-%d %H:%M}</p>
{''.join(parts)}
<p class="muted">Yeh page sirf aap ke computer / session par hai. Kuch bhi upload ya publish nahi hua.</p>
</main>{COPY_JS}</body></html>
"""
    out = pv / "preview.html"
    out.write_text(page, encoding="utf-8")
    return out


def serve(port: int = 8000) -> None:
    """Serve the repo folder locally so the preview's audio + fonts load."""
    import functools
    import http.server

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        print(f"Preview server chal raha hai: http://127.0.0.1:{port}/  (band karne ke liye Ctrl+C)")
        httpd.serve_forever()
