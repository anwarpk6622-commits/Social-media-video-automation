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


def _transcript_quality(data: dict, script_text: str) -> float:
    """0..1 — how usable a transcript looks. With a script: share of script words
    matched exactly. Without: share of words that are Urdu script (Whisper sometimes
    'hallucinates' Latin or Chinese text)."""
    from pipeline.subtitles import align
    from pipeline.urdu_text import tokenize_script
    words = data["words"]
    if not words:
        return 0.0
    odd = sum(1 for w in words if any(("a" <= ch.lower() <= "z") or ord(ch) > 0x3000 for ch in w["text"]))
    clean_share = 1 - odd / len(words)
    if script_text:
        return min(align(tokenize_script(script_text), words)["match_rate"] or 0.0, clean_share)
    return clean_share


def _transcribe_checked(audio, out_file, model: str, script_text: str, use_hint: bool) -> dict:
    """Transcribe, check the result, and retry the other way if it looks wrong.

    Lesson from a real 40-second video: giving Whisper the script as a 'hint' can make
    it invent text on real voices (18% match instead of 83%). So: no hint by default,
    and if a result is poor, the other setting is tried and the better one kept."""
    import json

    from pipeline.transcribe import transcribe
    tries = [use_hint and bool(script_text), not (use_hint and bool(script_text))]
    if not script_text:
        tries = [False]
    best, best_q = None, -1.0
    for k, hint_on in enumerate(tries):
        data = transcribe(audio, out_file, model=model, hint_text=script_text if hint_on else "")
        q = _transcript_quality(data, script_text)
        data["quality"] = round(q, 3)
        data["script_hint"] = hint_on
        if q > best_q:
            best, best_q = data, q
        if q >= 0.5:
            break
        if k + 1 < len(tries):
            print(f"   ⚠️ Natija kamzor laga (quality {q:.0%}) — doosre tareeqe se dobara sun raha hai…")
    out_file.write_text(json.dumps(best, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return best


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
        old = _transcribe_checked(clean, tr_file, model, script_text, cfg.get("use_script_hint", False))
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
            print(f"      {w['time']:>6.1f}s  {w['text']}  ({w['why']})")
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


def cmd_edit_init(a) -> int:
    import json

    from pipeline.project import Project
    from pipeline.video_edit import default_plan, plan_path
    p = Project.open(a.project)
    rec = p.recording_path(a.recording).name
    path = plan_path(p)
    if path.exists() and not a.force:
        print(f"❌ {path.name} pehle se mojood hai (aap ki tabdeeliyan ho sakti hain). Naya banana ho to --force")
        return 1
    plan = default_plan(p, rec, a.title, a.tag or "")
    if a.trim_start is not None:
        plan["trim"]["start"] = a.trim_start
    if a.trim_end is not None:
        plan["trim"]["end"] = a.trim_end
    for r in a.soft_range or []:
        s, e = (float(x) for x in r.split("-"))
        plan["grade"]["soft_ranges"].append([s, e])
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ Editing plan bana: {path}")
    print(f"   Scene cuts mile: {plan['cuts']}  ·  Shuru se kaat: {plan['trim']['start']}s")
    print(f"   Agla qadam: python run.py edit-preview {p.path.name}")
    return 0


def cmd_edit_preview(a) -> int:
    from pipeline.preview import build_preview
    from pipeline.project import Project
    from pipeline.video_edit import render
    p = Project.open(a.project)
    print("🎬 Editing preview ban raha hai (original ko haath nahi lagaya jaata)…")
    log = render(p, preview=True, formats=None if a.format == "both" else [a.format])
    build_preview(p)
    print(f"\n✅ Preview tayyar ({log['duration']}s). Original unchanged: ✅")
    print(f"   Dekhein: python run.py preview {p.path.name} --serve")
    print(f"   Pasand aaye to final file: python run.py export {p.path.name}")
    return 0


def cmd_export(a) -> int:
    import json

    from pipeline.project import Project
    from pipeline.video_edit import load_plan, plan_hash, render
    p = Project.open(a.project)
    pv = p.path / "edit_preview.json"
    if not pv.exists():
        print(f"❌ Pehle preview banayein aur dekhein: python run.py edit-preview {p.path.name}")
        return 1
    if json.loads(pv.read_text(encoding="utf-8"))["plan_hash"] != plan_hash(load_plan(p)):
        print("❌ edit.json preview ke baad badla hai. Pehle naya preview banayein aur dekhein (edit-preview).")
        return 1
    if not a.yes:
        ans = input("Kya aap ne preview dekh kar approve kar diya hai? Final export ke liye 'yes' likhein: ").strip().lower()
        if ans not in ("yes", "y", "haan", "han"):
            print("❎ Export cancel.")
            return 0
    print("📦 Final export (high quality, bina PREVIEW label)…")
    log = render(p, preview=False)
    print("\n✅ Final files tayyar (kuch bhi upload / publish NAHI hua):")
    for fmt, path in log["outputs"].items():
        print(f"   {fmt}: {path}")
    return 0


def _print_checks(checks: dict) -> int:
    from pipeline.publish_kit import LABELS, PLATFORMS
    errors = 0
    for p in PLATFORMS:
        marks = []
        for c in checks.get(p, []):
            icon = "✅" if c["ok"] else ("⚠️" if c["level"] == "warn" else "❌")
            errors += c["level"] == "error"
            marks.append(f"{icon} {c['msg']}")
        print(f"   {LABELS[p]}:")
        for m in marks:
            print(f"      {m}")
    return errors


def cmd_metadata(a) -> int:
    from pipeline.project import Project
    from pipeline.publish_kit import refresh_from_json, write_metadata
    p = Project.open(a.project)
    res = refresh_from_json(p) if a.refresh else write_metadata(p, title_index=(a.title or 1) - 1, force=a.force)
    print("📝 Platform metadata tayyar (title, description, hashtags):")
    errors = _print_checks(res["checks"])
    print(f"\n   Copy-paste file: {res['dir'] / 'metadata.md'}")
    print(f"   Badalna ho to:   {res['dir'] / 'metadata.json'}  phir: python run.py metadata {p.path.name} --refresh")
    return 1 if errors else 0


def cmd_thumbnail(a) -> int:
    from pipeline.project import Project
    from pipeline.publish_kit import make_thumbnails
    p = Project.open(a.project)
    print("🖼️ Thumbnail ban raha hai (behtareen frame khud chuna ja raha hai)…")
    info = make_thumbnails(p, time=a.time, text=a.text)
    how = "khud chuna" if info["auto"] else "aap ne chuna"
    print(f"   Frame: {info['time']:.1f}s ({how})  ·  Text: {info['text']}")
    for kind, f in info["files"].items():
        print(f"   ✅ {f['file']}  ({f['size'][0]}×{f['size'][1]}, {f['bytes'] // 1024} KB)")
    print("   Doosre achhe frames: " + ", ".join(f"{c['time']:.1f}s" for c in info["candidates"][1:]))
    print(f"   Koi aur frame chahiye: python run.py thumbnail {p.path.name} --time <second>")
    return 0


def cmd_publish_kit(a) -> int:
    from pipeline.preview import build_preview
    from pipeline.project import Project
    from pipeline.publish_kit import write_metadata
    p = Project.open(a.project)
    a.refresh = False
    rc_t = cmd_thumbnail(a)
    try:
        res = write_metadata(p, title_index=(a.title or 1) - 1, force=a.force)
    except FileExistsError as e:
        print(f"ℹ️ {e}")
        from pipeline.publish_kit import refresh_from_json
        res = refresh_from_json(p)
    print("\n📝 Platform metadata:")
    errors = _print_checks(res["checks"])
    out = build_preview(p)
    print(f"\n📦 Publishing kit tayyar. Kuch bhi upload / publish NAHI hua.\n   Dekhein: {out}")
    return 1 if (errors or rc_t) else 0


# ----------------------------------------------------------------- Phase 6.1 (no network)
def _pub(project_ref):
    from pipeline.project import Project
    from publishers.store import JobStore
    p = Project.open(project_ref)
    return p, JobStore(p.path)


def _pub_ids(store, platforms):
    jobs = store.all()
    if platforms:
        jobs = [j for j in jobs if j.id in platforms]
    if not jobs:
        raise FileNotFoundError("Koi publishing job nahi mila. Pehle: python run.py publish-plan <project>")
    return [j.id for j in jobs]


def cmd_publish_plan(a) -> int:
    from publishers.plan import make_plan
    p, _ = _pub(a.project)
    privacy = {}
    for item in a.privacy or []:
        k, _, v = item.partition("=")
        privacy[k.strip()] = v.strip()
    res = make_plan(p.path, a.platform, privacy=privacy, schedule=a.schedule)
    print("🗂️ Publishing plan (kuch upload NAHI hota):")
    labels = {"created": "naya bana", "unchanged": "koi tabdeeli nahi", "replanned": "badla → dobara check/approve",
              "completed": "pehle hi mukammal (dobara nahi)"}
    for r in res:
        j = r["job"]
        print(f"   • {j.id:15} privacy={j.privacy:9} status={j.status:10} ({labels[r['action']]})")
    print(f"   Agla qadam: python run.py publish-check {p.path.name}")
    return 0


def cmd_publish_check(a) -> int:
    from publishers.validate import validate_and_store
    p, store = _pub(a.project)
    bad = 0
    print("🔎 Dry-run validation (koi API call nahi):")
    for jid in _pub_ids(store, a.platform):
        job = validate_and_store(p.path, store, jid)
        v = job.validation
        bad += not v["ok"]
        f = v.get("facts", {})
        facts = f"{f.get('width')}×{f.get('height')}, {f.get('duration')}s, {f.get('vcodec')}/{f.get('acodec')}" if f else ""
        print(f"   {'✅' if v['ok'] else '❌'} {jid:15} {job.status:10} {facts}")
        for e in v["errors"]:
            print(f"        ❌ {e}")
        for w in v["warnings"]:
            print(f"        ⚠️ {w}")
    print(f"   Agla qadam: python run.py publish-approve {p.path.name}")
    return 1 if bad else 0


def cmd_publish_approve(a) -> int:
    from publishers.approval import ApprovalError, approve
    from publishers.models import VALIDATED
    p, store = _pub(a.project)
    ids = [j for j in _pub_ids(store, a.platform) if store.load(j).status == VALIDATED]
    if not ids:
        print("ℹ️ Manzoori ke liye koi validated job nahi. Pehle: publish-check")
        return 1
    print("✋ Manzoori — har job alag se. (Phase 6.1: manzoori ke baad bhi asal upload mumkin nahi.)\n")
    rc = 0
    for jid in ids:
        try:
            approve(p.path, store, jid)
            print(f"   ✅ {jid} manzoor. Fingerprints mohr ho gaye.\n")
        except ApprovalError as e:
            print(f"   ❎ {jid}: {e}\n")
            rc = 1
    return rc


def cmd_publish_status(a) -> int:
    from publishers.fingerprint import current_fingerprints, differences
    p, store = _pub(a.project)
    jobs = store.all()
    if not jobs:
        print("Koi publishing job nahi.")
        return 0
    print(f"📋 Publishing status — {p.path.name}")
    for j in jobs:
        note = ""
        if j.approval:
            d = differences(j.approval["fingerprints"], current_fingerprints(p.path, j))
            note = "  ⚠️ manzoori ke baad tabdeeli: " + "; ".join(d) if d else "  🔒 fingerprints durust"
        up = j.upload.get("remote_id") or (f"{j.upload.get('bytes_sent', 0)} bytes" if j.upload else "")
        print(f"   • {j.id:15} {j.status:10} privacy={j.privacy:9} {up}{note}")
    return 0


def cmd_publish_run(a) -> int:
    from publishers.adapters import AdapterNotAvailable, get_adapter
    from publishers.retry import RetryPolicy
    from publishers.runner import RunError, run_job
    p, store = _pub(a.project)
    live = bool(load_settings()["publishing"].get("live_enabled", False))
    if not a.simulate:
        print("⛔ Asal publishing Phase 6.1 mein band hai. Sirf simulation: python run.py publish-run "
              f"{p.path.name} --simulate")
        return 1
    failures = [x for x in (a.fail or "").split(",") if x]
    rc = 0
    print("🧪 SIMULATION — internet istemal nahi hota, asal job ki haalat nahi badalti.")
    for jid in _pub_ids(store, a.platform):
        try:
            adapter = get_adapter(store.load(jid).platform, live_enabled=live, simulate=True,
                                  failures=list(failures), chunk_size=4 * 1024 * 1024)
            job = run_job(p.path, store, jid, adapter, simulate=True, policy=RetryPolicy(max_attempts=4, base_delay=0.01),
                          sleep=lambda s: None, poll_interval=0)
            sent = job.upload.get("bytes_sent", 0)
            print(f"   {'✅' if job.status == 'completed' else '❌'} {jid:15} → {job.status}  "
                  f"({sent / 1024 ** 2:.1f} MB, {job.upload.get('retries', 0)} retry){'  ' + job.error.get('message', '') if job.error else ''}")
            rc |= job.status != "completed"
        except (RunError, AdapterNotAvailable) as e:
            print(f"   ❎ {jid}: {e}")
            rc = 1
    print("   Asal jobs ki haalat: python run.py publish-status " + p.path.name)
    return rc


def cmd_publish_report(a) -> int:
    from pipeline.preview import build_preview
    from publishers.log import PublishLog, report_markdown
    p, store = _pub(a.project)
    out = p.path / "publish" / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report_markdown(store.all(), PublishLog(p.path).read()), encoding="utf-8")
    build_preview(p)
    print(f"📄 Report: {out}\n   Preview page bhi update hua.")
    return 0


def cmd_secret_scan(a) -> int:
    from pipeline.config import ROOT
    from publishers.secret_scan import scan
    findings = scan(ROOT, staged=not a.all)
    if not findings:
        print(f"✅ Secret scan: kuch nahi mila ({'staged files' if not a.all else 'saari tracked files'}).")
        return 0
    print("⛔ Secret scan ne yeh pakda (commit roka gaya):")
    for f in findings:
        print(f"   {f['file']}:{f['line']}  {f['type']}  {f['match']}")
    print("   Secret ko file se hatayein (.env ya OS keyring mein rakhein). Ghalat alarm ho to line mein 'secret-scan: allow' likhein.")
    return 1


def cmd_install_hooks(_a) -> int:
    import subprocess

    from pipeline.config import ROOT
    from publishers.secret_scan import HOOK
    d = ROOT / ".githooks"
    d.mkdir(exist_ok=True)
    hook = d / "pre-commit"
    hook.write_text(HOOK, encoding="utf-8")
    hook.chmod(0o755)
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=ROOT, check=True)
    print("✅ Har commit se pehle secret scan chalega (.githooks/pre-commit).")
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

    s = sub.add_parser("edit-init", help="Phase 4: video editing ka plan (edit.json) banayein")
    s.add_argument("project")
    s.add_argument("--title", required=True, help="Urdu title (Nastaliq mein video par)")
    s.add_argument("--tag", help="chhota location tag, jaise 'برج العرب، دبئی'")
    s.add_argument("--recording", help="kaun si video (default: aakhri add ki hui)")
    s.add_argument("--trim-start", type=float, help="shuru se itne second kaatein")
    s.add_argument("--trim-end", type=float, help="is second par video khatam")
    s.add_argument("--soft-range", action="append", help="halka grade (chehre), jaise 29.7-35.5")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_edit_init)

    s = sub.add_parser("edit-preview", help="Phase 4: editing ka PREVIEW (9:16 + 16:9)")
    s.add_argument("project")
    s.add_argument("--format", choices=["both", "vertical", "landscape"], default="both")
    s.set_defaults(fn=cmd_edit_preview)

    s = sub.add_parser("export", help="Phase 4: final high-quality files (preview approve karne ke BAAD)")
    s.add_argument("project")
    s.add_argument("--yes", action="store_true", help="tasdeeq ka sawal skip")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("metadata", help="Phase 5: har platform ka title / description / hashtags")
    s.add_argument("project")
    s.add_argument("--title", type=int, help="script ke TITLES mein se kaun sa (1, 2, 3…)")
    s.add_argument("--refresh", action="store_true", help="haath se badli metadata.json ko check kar ke .md dobara banayein")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_metadata)

    s = sub.add_parser("thumbnail", help="Phase 5: YouTube thumbnail + TikTok/Reels/Shorts cover")
    s.add_argument("project")
    s.add_argument("--time", type=float, help="kis second ka frame (default: behtareen khud chunein)")
    s.add_argument("--text", help="thumbnail par text (default: video ka title)")
    s.set_defaults(fn=cmd_thumbnail)

    s = sub.add_parser("publish-kit", help="Phase 5: metadata + thumbnails ek saath (kuch upload nahi hota)")
    s.add_argument("project")
    s.add_argument("--title", type=int)
    s.add_argument("--time", type=float)
    s.add_argument("--text")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_publish_kit)

    pf = ["youtube", "youtube_shorts", "facebook_reels", "tiktok"]
    s = sub.add_parser("publish-plan", help="Phase 6.1: har platform ka publishing job (kuch upload nahi)")
    s.add_argument("project")
    s.add_argument("--platform", action="append", choices=pf, help="sirf yeh platform (dobara likh sakte hain)")
    s.add_argument("--privacy", action="append", help="jaise youtube=unlisted (default: private/draft/only-me)")
    s.add_argument("--schedule", help="jaise 2026-12-02T19:00")
    s.set_defaults(fn=cmd_publish_plan)

    s = sub.add_parser("publish-check", help="Phase 6.1: dry-run validation (koi API call nahi)")
    s.add_argument("project")
    s.add_argument("--platform", action="append", choices=pf)
    s.set_defaults(fn=cmd_publish_check)

    s = sub.add_parser("publish-approve", help="Phase 6.1: manzoori (APPROVE likhna, public ke liye PUBLIC)")
    s.add_argument("project")
    s.add_argument("--platform", action="append", choices=pf)
    s.set_defaults(fn=cmd_publish_approve)

    s = sub.add_parser("publish-status", help="Phase 6.1: jobs ki haalat + fingerprint check")
    s.add_argument("project")
    s.set_defaults(fn=cmd_publish_status)

    s = sub.add_parser("publish-run", help="Phase 6.1: sirf --simulate (offline nakal; asal upload band)")
    s.add_argument("project")
    s.add_argument("--simulate", action="store_true")
    s.add_argument("--platform", action="append", choices=pf)
    s.add_argument("--fail", help="simulation mein masle: transient,rate_limit,fatal")
    s.set_defaults(fn=cmd_publish_run)

    s = sub.add_parser("publish-report", help="Phase 6.1: publishing report + preview page")
    s.add_argument("project")
    s.set_defaults(fn=cmd_publish_report)

    s = sub.add_parser("secret-scan", help="commit se pehle secrets dhoondein")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="saari tracked files")
    g.add_argument("--staged", action="store_true", help="sirf commit hone wali files (default; git hook yahi chalata hai)")
    s.set_defaults(fn=cmd_secret_scan)

    sub.add_parser("install-hooks", help="har commit se pehle khud secret scan").set_defaults(fn=cmd_install_hooks)

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
