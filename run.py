#!/usr/bin/env python3
"""Urdu Video Automation — command line tool (Phase 1 + 2).

Sab commands dekhne ke liye:   python run.py --help

Yeh tool kuch bhi upload ya publish NAHI karta.
"""

from __future__ import annotations

import argparse
import sys

from pipeline.config import PROJECTS_DIR, load_settings


def _print_report(rep: dict) -> None:
    o, c = rep["original"], rep["clean"]
    print("\n✅ Awaaz tayyar!")
    print(f"   Loudness:  {o['loudness_lufs']} LUFS  →  {c['loudness_lufs']} LUFS (target {rep['settings']['target_lufs']})")
    print(f"   Peak:      {o['true_peak_db']} dB    →  {c['true_peak_db']} dB")
    print(f"   Lambai:    {o['duration_seconds']}s  →  {c['duration_seconds']}s")
    print(f"   Original unchanged: {'✅ haan' if o['unchanged'] else '❌ NAHI'}")
    if rep.get("loudness_note"):
        print(f"   ⚠️ Note: {rep['loudness_note']}")


def cmd_doctor(_a) -> int:
    from pipeline.doctor import run_doctor
    return 0 if run_doctor() else 1


def cmd_new(a) -> int:
    from pipeline.project import Project
    p = Project.create(a.name, a.topic or "")
    print(f"✅ Naya project bana: {p.path}")
    print(f"   Agla qadam: python run.py add-recording {p.path.name} <aap-ki-recording.m4a>")
    print(f"   Ya script:  python run.py script {p.path.name} --topic \"...\"")
    return 0


def cmd_list(_a) -> int:
    projects = sorted(d for d in PROJECTS_DIR.glob("*") if (d / "project.json").exists())
    if not projects:
        print("Abhi koi project nahi. Banayein: python run.py new \"Mera pehla video\"")
    for d in projects:
        print(" •", d.name)
    return 0


def cmd_add_recording(a) -> int:
    from pipeline.project import Project
    p = Project.open(a.project)
    entry = p.add_recording(a.file)
    print(f"✅ Recording mehfooz kar di: input/original/{entry['file']}")
    print(f"   Fingerprint (SHA-256): {entry['sha256'][:16]}…  — file ab read-only hai.")
    print("   Yaad rakhein: apni asal recording ka backup apne phone/computer par bhi rakhein.")
    return 0


def cmd_verify(a) -> int:
    from pipeline.project import Project
    p = Project.open(a.project)
    res = p.verify_originals()
    if not res:
        print("Koi recording nahi.")
    bad = 0
    for r in res:
        ok = r["status"] == "ok"
        bad += not ok
        print(f" {'✅' if ok else '❌'} {r['file']}: {'bilkul unchanged' if ok else r['status']}")
    return 1 if bad else 0


def cmd_script(a) -> int:
    from pipeline.project import Project
    from pipeline.script_writer import ScriptRequest, write_api_mode, write_free_mode
    p = Project.open(a.project)
    s = load_settings()
    topic = a.topic or p.load_meta().get("topic")
    if not topic:
        print("❌ Topic batayein:  --topic \"Mobile se video kaise banayein\"")
        return 1
    req = ScriptRequest(
        topic=topic,
        minutes=a.minutes or s["script"]["default_minutes"],
        audience=a.audience or s["channel"]["audience"],
        tone=a.tone or s["channel"]["tone"],
        call_to_action=s["channel"]["call_to_action"],
        extra_notes=a.notes or "",
    )
    if a.use_api:
        res = write_api_mode(p, req, assume_yes=a.yes)
        if res.get("cancelled"):
            return 0
        print(f"✅ Script save hui: {res['script_file']}")
    else:
        res = write_free_mode(p, req)
        print("✅ FREE mode (koi lagat nahi)")
        print(f"   1. Yeh file kholein aur sara text copy karein:  {res['prompt_file']}")
        print("   2. https://claude.ai par nayi chat mein paste karein.")
        print(f"   3. Claude ka jawab is file mein paste karein:    {res['script_file']}")
        print(f"   4. Check karein:  python run.py script-check {p.path.name}")
    return 0


def cmd_script_check(a) -> int:
    from pipeline.project import Project
    from pipeline.script_writer import check_script, export_reading_script
    p = Project.open(a.project)
    f = p.script_dir / "script.md"
    if not f.exists():
        print("❌ script.md nahi mili. Pehle: python run.py script ...")
        return 1
    wpm = load_settings()["script"]["words_per_minute"]
    r = check_script(f, wpm)
    print("\n📝 Script check")
    print(f"   Hisse mile:   {len(r['sections_found'])}/7")
    if r["missing_sections"]:
        print(f"   ⚠️ Ghayab:     {', '.join(r['missing_sections'])}")
    print(f"   Recording:    {r['recording_words']} alfaaz ≈ {r['recording_minutes']} minute ({r['pauses']} pauses)")
    print(f"   Short:        {r['short_words']} alfaaz ≈ {r['short_seconds']} second" + ("  ⚠️ 60s se zyada" if r["short_seconds"] > 60 else ""))
    if not r["has_urdu"] and r["recording_words"]:
        print("   ⚠️ Recording script mein Urdu huroof nahi mile (kya yeh Roman Urdu hai?)")
    for fact in r["facts_to_check"]:
        print(f"   🔎 Khud check karein: {fact}")
    if r["recording_words"]:
        out = export_reading_script(f, p.script_dir / "read_aloud.txt")
        print(f"   📄 Parhne ke liye saaf text: {out}")
    return 0 if not r["missing_sections"] else 1


def cmd_audio(a) -> int:
    from pipeline.audio import process_voice
    from pipeline.project import Project
    p = Project.open(a.project)
    overrides = {
        "noise_reduction": a.noise,
        "trim_silence": True if a.trim_silence else None,
        "eq": False if a.no_eq else None,
        "compressor": False if a.no_compressor else None,
        "deesser": False if a.no_deesser else None,
        "target_lufs": a.lufs,
    }
    print("🎙️ Awaaz process ho rahi hai (original ko haath nahi lagaya jaata)…")
    rep = process_voice(p, a.recording, overrides)
    _print_report(rep)
    print(f"   Saaf file:    {p.processed_dir / rep['clean']['file']}")
    print(f"   Dekhne ke liye: python run.py preview {p.path.name}")
    return 0


def _clean_audio(p, recording: str | None):
    """The cleaned voice file for a recording (Phase 2 output)."""
    src = p.recording_path(recording)
    clean = p.processed_dir / f"{src.stem}_clean.wav"
    if not clean.exists():
        raise FileNotFoundError(
            f"Saaf awaaz nahi mili ({clean.name}). Pehle chalayein: python run.py audio {p.path.name}"
            + (f" --recording {recording}" if recording else "")
        )
    return clean


def cmd_subtitles(a) -> int:
    import json

    from pipeline.project import Project
    from pipeline.script_writer import parse_sections
    from pipeline.subtitles import build_subtitles
    from pipeline.transcribe import transcribe
    p = Project.open(a.project)
    cfg = load_settings()["subtitles"]
    clean = _clean_audio(p, a.recording)
    sub_dir = p.path / "subtitles"
    model = a.model or cfg["model"]

    script_text = ""
    script_file = p.script_dir / "script.md"
    if not a.no_script and script_file.exists():
        script_text = parse_sections(script_file.read_text(encoding="utf-8")).get("RECORDING SCRIPT", "")
    if not script_text:
        print("ℹ️ Script istemal nahi ho rahi — subtitles sirf Whisper ki suni hui likhai se banenge (spelling khud check karein).")

    tr_file = sub_dir / f"transcript_{clean.stem}.json"
    old = json.loads(tr_file.read_text(encoding="utf-8")) if tr_file.exists() else None
    if a.retranscribe or old is None or old.get("model") != model:
        print("🎧 Whisper AI awaaz sun raha hai (sab kuch aap ke computer par, koi upload nahi)…")
        hint = script_text if cfg.get("use_script_hint", True) else ""
        old = transcribe(clean, tr_file, model=model, hint_text=hint)
        print(f"   ✅ {len(old['words'])} alfaaz suney gaye ({old['seconds_taken']} second mein)")
    else:
        print(f"🎧 Pehle wala transcript istemal ho raha hai ({tr_file.name}). Naya chahiye to --retranscribe")

    res = build_subtitles(sub_dir, old, script_text, cfg, force=a.force)
    r = res["report"]
    c = r["counts"]
    print("\n📝 Subtitles tayyar!")
    if r["mode"] == "script+speech":
        print(f"   Script se match:  {round(r['match_rate'] * 100)}% alfaaz bilkul wahi suney gaye")
        print(f"   Alfaaz: {c['words']}  (match {c['matched']}, script se durust {c['fitted']}, "
              f"andaaza {c['guessed']}, script se zyada {c['extra']}, chhoote {c['skipped']})")
    elif r.get("rejected_match_rate") is not None:
        print(f"   ⚠️ Recording script se sirf {round(r['rejected_match_rate'] * 100)}% milti hai — shayad kisi aur script ki "
              "recording hai. Is liye Whisper ki likhai istemal hui. Spelling zaroor check karein.")
    print(f"   16:9 (YouTube):           {res['files']['landscape']}  ({c['cues_landscape']} hisse)")
    print(f"   9:16 (Shorts/TikTok/Reel): {res['files']['vertical']}  ({c['cues_vertical']} hisse)")
    if r["to_check"]:
        print(f"   🔎 {len(r['to_check'])} alfaaz khud check karein (preview page par list hai), jaise:")
        for w in r["to_check"][:5]:
            print(f"      {w['time']:>6}s  {w['text']}  ({w['why']})")
    if r["skipped"]:
        print(f"   ⏭️ Script ke yeh alfaaz recording mein nahi mile (subtitle mein nahi): {' '.join(r['skipped'][:12])}")
    print(f"   Agla qadam: python run.py subtitle-video {p.path.name}")
    print("   (Ghalti ho to .srt file Notepad mein theek karein, phir subtitle-video dobara chalayein.)")
    return 0


def cmd_subtitle_video(a) -> int:
    import json
    from pathlib import Path

    from pipeline.project import Project
    from pipeline.subtitle_render import make_subtitle_video
    from pipeline.subtitles import attach_word_times, read_srt
    p = Project.open(a.project)
    s = load_settings()["subtitles"]
    sub_dir = p.path / "subtitles"
    words_file = sub_dir / "words.json"
    if not words_file.exists():
        print(f"❌ Pehle subtitles banayein: python run.py subtitles {p.path.name}")
        return 1
    data = json.loads(words_file.read_text(encoding="utf-8"))
    audio = p.processed_dir / data["report"]["audio"]
    if not audio.exists():
        print(f"❌ Awaaz ki file nahi mili: {audio}. Dobara: python run.py audio {p.path.name}")
        return 1
    bg = Path(a.background).expanduser().resolve() if a.background else None
    if bg and not bg.exists():
        print(f"❌ Background video nahi mili: {bg}")
        return 1
    highlight = s.get("highlight_words", True) and not a.no_highlight
    formats = ["landscape", "vertical"] if a.format == "both" else [a.format]
    srt_names = {"landscape": "urdu.srt", "vertical": "urdu_vertical.srt"}
    out_names = {"landscape": "subtitles_16x9.mp4", "vertical": "subtitles_9x16.mp4"}
    for fmt in formats:
        cues = attach_word_times(read_srt(sub_dir / srt_names[fmt]), data["words"])
        print(f"🎬 {fmt}: {len(cues)} subtitle hisse — tasveerein aur video ban rahi hain…")
        out = make_subtitle_video(audio, cues, s[fmt], p.preview_dir / out_names[fmt],
                                  p.path / "tmp" / f"subs_{fmt}", background=bg, highlight=highlight)
        print(f"   ✅ {out}")
    print(f"   Dekhne ke liye: python run.py preview {p.path.name} --serve")
    return 0


def cmd_font_test(a) -> int:
    from pathlib import Path

    from pipeline.preview import render_font_test
    out = Path(a.out) if a.out else PROJECTS_DIR / "font_test.png"
    path = render_font_test(out)
    print(f"✅ Urdu font test tasveer: {path}")
    print("   Is tasveer ko kholein: Urdu huroof jude hue aur daayen se baayen hone chahiye.")
    return 0


def cmd_preview(a) -> int:
    from pipeline.preview import build_preview, serve
    from pipeline.project import Project
    p = Project.open(a.project)
    out = build_preview(p)
    print(f"✅ Preview page: {out}")
    if a.serve:
        rel = out.relative_to(PROJECTS_DIR.parent).as_posix()
        print(f"   Browser mein kholein: http://127.0.0.1:{a.port}/{rel}")
        serve(a.port)
    else:
        print("   Apne computer par is file ko double-click karein, ya:  python run.py preview <project> --serve")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows terminals may not be UTF-8: never crash on emoji / Urdu text in messages.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="run.py", description="Urdu video automation (Phase 1-3). Kuch bhi publish nahi karta.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="system check").set_defaults(fn=cmd_doctor)

    s = sub.add_parser("new", help="naya video project")
    s.add_argument("name")
    s.add_argument("--topic")
    s.set_defaults(fn=cmd_new)

    sub.add_parser("list", help="sab projects").set_defaults(fn=cmd_list)

    s = sub.add_parser("add-recording", help="apni recording project mein (mehfooz copy) daalein")
    s.add_argument("project")
    s.add_argument("file")
    s.set_defaults(fn=cmd_add_recording)

    s = sub.add_parser("verify", help="check karein ke original recordings unchanged hain")
    s.add_argument("project")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("script", help="Urdu script (FREE prompt mode, ya --use-api PAID)")
    s.add_argument("project")
    s.add_argument("--topic")
    s.add_argument("--minutes", type=float)
    s.add_argument("--audience")
    s.add_argument("--tone")
    s.add_argument("--notes", help="extra hidayat, jaise 'beginners ke liye'")
    s.add_argument("--use-api", action="store_true", help="PAID: Claude API se seedha likhwayein (pehle lagat dikhayega)")
    s.add_argument("--yes", action="store_true", help="lagat ka sawal skip (sirf agar aap ko pata ho)")
    s.set_defaults(fn=cmd_script)

    s = sub.add_parser("script-check", help="script ke hisse aur lambai check karein")
    s.add_argument("project")
    s.set_defaults(fn=cmd_script_check)

    s = sub.add_parser("audio", help="apni awaaz saaf karein (FFmpeg)")
    s.add_argument("project")
    s.add_argument("--recording", help="file ka naam (default: aakhri add ki hui)")
    s.add_argument("--noise", choices=["off", "light", "medium", "strong"])
    s.add_argument("--trim-silence", action="store_true", help="lambi khamoshi chhoti karein")
    s.add_argument("--no-eq", action="store_true")
    s.add_argument("--no-compressor", action="store_true")
    s.add_argument("--no-deesser", action="store_true")
    s.add_argument("--lufs", type=float, help="loudness target (default -14)")
    s.set_defaults(fn=cmd_audio)

    s = sub.add_parser("subtitles", help="Phase 3: awaaz sun kar Urdu subtitles (.srt) banayein")
    s.add_argument("project")
    s.add_argument("--recording", help="kis recording ki saaf awaaz (default: aakhri)")
    s.add_argument("--model", choices=["tiny", "base", "small", "medium", "large-v3"],
                   help="Whisper model (default settings.json: medium)")
    s.add_argument("--no-script", action="store_true", help="script se match na karein")
    s.add_argument("--retranscribe", action="store_true", help="awaaz dobara sunein")
    s.add_argument("--force", action="store_true", help="haath se edit ki hui .srt ko bhi naya banayein (backup ke saath)")
    s.set_defaults(fn=cmd_subtitles)

    s = sub.add_parser("subtitle-video", help="Phase 3: subtitles wali test video (16:9 + 9:16)")
    s.add_argument("project")
    s.add_argument("--format", choices=["both", "landscape", "vertical"], default="both")
    s.add_argument("--background", help="apni video clip background ke liye (optional)")
    s.add_argument("--no-highlight", action="store_true", help="bolta hua lafz peela na karein")
    s.set_defaults(fn=cmd_subtitle_video)

    s = sub.add_parser("font-test", help="Urdu Nastaliq render test tasveer")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_font_test)

    s = sub.add_parser("preview", help="preview.html banayein (sun kar / dekh kar check)")
    s.add_argument("project")
    s.add_argument("--serve", action="store_true", help="local browser server chalayein")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_preview)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, IOError) as e:
        print(f"❌ {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
