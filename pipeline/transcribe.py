"""Speech → words with timings, using faster-whisper (free, runs on your computer).

The model is downloaded once (from Hugging Face) into the project's models/
folder: small ≈ 0.5 GB, medium ≈ 1.5 GB, large-v3 ≈ 3 GB. After that, no
internet is needed and nothing is uploaded anywhere.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import time
from pathlib import Path

from .config import ROOT

MODELS_DIR = ROOT / "models"
MODEL_SIZES = {"tiny": "75 MB", "base": "145 MB", "small": "0.5 GB", "medium": "1.5 GB", "large-v3": "3 GB"}


def load_audio_16k(path: Path):
    """Decode any audio/video file to 16 kHz mono float32 with FFmpeg.

    (We do this ourselves instead of letting faster-whisper use PyAV, which
    breaks with some PyAV versions.)"""
    import numpy as np

    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0",
         "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Awaaz parhi nahi ja saki: {path}\n{proc.stderr.decode(errors='replace')[-500:]}")
    return np.frombuffer(proc.stdout, np.float32)


def transcribe(audio_path: Path, out_json: Path, *, model: str = "medium", language: str = "ur",
               hint_text: str = "", beam_size: int = 5) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("faster-whisper install nahi. Chalayein: pip install -r requirements.txt") from e

    MODELS_DIR.mkdir(exist_ok=True)
    size = MODEL_SIZES.get(model, "?")
    print(f"   Whisper model '{model}' load ho raha hai (pehli dafa ~{size} download hoga)…")
    t0 = time.time()
    wm = WhisperModel(model, device="cpu", compute_type="int8", download_root=str(MODELS_DIR))
    audio = load_audio_16k(audio_path)
    duration = len(audio) / 16000
    print(f"   Sun raha hai: {duration:.0f} second ki awaaz… (CPU par ~{max(1, round(duration * 0.7 / 60))} minute lag sakte hain)")

    segments, info = wm.transcribe(
        audio,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=beam_size,
        # A little of the script helps Whisper with spelling of names/terms.
        initial_prompt=hint_text[:400] or None,
        condition_on_previous_text=False,  # less risk of repeated / invented lines
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"text": text, "start": round(float(w.start), 3),
                              "end": round(float(w.end), 3), "prob": round(float(w.probability), 3)})
    data = {
        "audio": audio_path.name,
        "model": model,
        "language": info.language,
        "duration": round(duration, 2),
        "seconds_taken": round(time.time() - t0, 1),
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "words": words,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data
