"""System check: is everything installed and set up correctly?"""

from __future__ import annotations

import shutil
import subprocess
import sys

from .config import FONTS_DIR, ROOT, load_env, load_settings, secret_is_set
from .ffmpeg_tools import has_filter


def run_doctor() -> bool:
    load_env()
    ok_all = True

    def line(ok: bool, label: str, detail: str = "", required: bool = True) -> None:
        nonlocal ok_all
        icon = "✅" if ok else ("❌" if required else "➖")
        if not ok and required:
            ok_all = False
        print(f"  {icon} {label}" + (f"  — {detail}" if detail else ""))

    print("\n🩺 System check\n")
    line(sys.version_info >= (3, 10), "Python 3.10+", sys.version.split()[0])

    ff = shutil.which("ffmpeg")
    line(bool(ff), "FFmpeg installed", ff or "install karein: https://ffmpeg.org/download.html")
    line(bool(shutil.which("ffprobe")), "FFprobe installed")
    if ff:
        ver = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.split("\n")[0]
        print(f"     {ver[:70]}")
        for f in ("loudnorm", "afftdn", "acompressor", "deesser", "silenceremove", "showwavespic"):
            line(has_filter(f), f"FFmpeg filter: {f}")

    # Urdu Nastaliq renderer (Chromium via Node.js Playwright)
    node = shutil.which("node")
    line(bool(node), "Node.js (Urdu text renderer ke liye)", node or "install: https://nodejs.org (LTS)")
    if node:
        pw = subprocess.run([node, "-e", "require('playwright');console.log('ok')"], capture_output=True, text=True)
        line(pw.stdout.strip() == "ok", "Playwright + Chromium (Urdu Nastaliq rendering)",
             "" if pw.stdout.strip() == "ok" else "install: npm install playwright && npx playwright install chromium")

    fonts = load_settings()["fonts"]
    for key in ("urdu_regular", "urdu_bold"):
        p = ROOT / fonts[key]
        line(p.exists(), f"Font: {p.name}")
    line((FONTS_DIR / "OFL.txt").exists(), "Font license (OFL.txt)")

    # Phase 3: subtitles
    try:
        import faster_whisper
        line(True, "faster-whisper (Urdu subtitles)", faster_whisper.__version__)
    except ImportError:
        line(False, "faster-whisper (Urdu subtitles)", "install: pip install -r requirements.txt")
    models = ROOT / "models"
    downloaded = sorted(p.name.split("--")[-1] for p in models.glob("models--*")) if models.exists() else []
    line(bool(downloaded), "Whisper model downloaded",
         ", ".join(downloaded) if downloaded else "pehli dafa 'python run.py subtitles ...' par khud download hoga (~1.5 GB)",
         required=False)

    try:
        import anthropic  # noqa: F401
        have_sdk = True
    except ImportError:
        have_sdk = False
    print("\n  Optional (sirf PAID API script mode ke liye):")
    line(have_sdk, "anthropic package", "" if have_sdk else "zaroorat ho to: pip install -r requirements-optional.txt", required=False)
    line(secret_is_set("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY .env mein",
         "set hai (value kabhi dikhayi nahi jaati)" if secret_is_set("ANTHROPIC_API_KEY") else "khaali — FREE mode chalega",
         required=False)

    print("\n" + ("🎉 Sab theek hai! System tayyar hai." if ok_all else "⚠️ Upar ❌ wali cheezein theek karein."))
    return ok_all
