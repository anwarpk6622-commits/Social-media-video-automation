"""Original-voice cleanup with FFmpeg.

The creator's ORIGINAL recording is only ever READ. Its SHA-256 fingerprint is
checked before and after processing. All results are new files in
audio/processed/. The voice itself is not changed (no pitch shift, no voice
cloning, no AI voice) — only noise, tone balance and loudness are improved.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
from pathlib import Path

from .config import load_settings
from .ffmpeg_tools import audio_info, parse_loudnorm_json, require_ffmpeg, run_ffmpeg
from .project import Project, sha256_of

NOISE_LEVELS = {"off": 0, "light": 6, "medium": 12, "strong": 20}  # afftdn noise reduction in dB


def build_filter_chain(opts: dict) -> list[str]:
    """Voice-friendly filter chain (before loudness normalisation)."""
    # Voice is mono. Downmix FIRST: loudness of stereo is measured over both
    # channels, so normalising stereo and then downmixing would end ~3 dB too quiet.
    chain: list[str] = ["aformat=channel_layouts=mono"]

    if opts.get("trim_silence"):
        thr = opts["silence_threshold_db"]
        chain.append(
            "silenceremove="
            f"start_periods=1:start_threshold={thr}dB:start_silence=0.25:"
            f"stop_periods=-1:stop_duration={opts['max_silence_seconds']}:"
            f"stop_threshold={thr}dB:stop_silence={opts['keep_silence_seconds']}"
        )

    if opts.get("highpass_hz"):
        chain.append(f"highpass=f={int(opts['highpass_hz'])}")

    nr = NOISE_LEVELS.get(str(opts.get("noise_reduction", "medium")), 12)
    if nr:
        # tn=1: track the noise floor continuously (good for fans / traffic)
        chain.append(f"afftdn=nr={nr}:nf=-50:tn=1")

    if opts.get("eq"):
        chain += [
            "equalizer=f=250:t=q:w=1.0:g=-2",    # less "muddy / boxy" room sound
            "equalizer=f=3500:t=q:w=1.2:g=2.5",  # clearer, more present voice
            "lowpass=f=16000",
        ]

    if opts.get("deesser"):
        chain.append("deesser=i=0.3")

    if opts.get("compressor"):
        # threshold 0.1 = -20 dBFS, gentle 3:1 ratio
        chain.append("acompressor=threshold=0.1:ratio=3:attack=15:release=200:makeup=1.5")

    return chain


def _measure(path: Path, pre_chain: list[str] | None = None, opts: dict | None = None) -> dict:
    """Run loudnorm in analysis mode and return its JSON measurement."""
    o = opts or {}
    ln = (
        f"loudnorm=I={o.get('target_lufs', -14)}:TP={o.get('true_peak_db', -1.5)}:"
        f"LRA={o.get('loudness_range', 11)}:print_format=json"
    )
    af = ",".join([*(pre_chain or []), ln])
    proc = run_ffmpeg(["-i", str(path), "-map", "0:a:0", "-af", af, "-f", "null", "-"])
    return parse_loudnorm_json(proc.stderr)


def _summary(m: dict) -> dict:
    return {
        "loudness_lufs": float(m["input_i"]),
        "true_peak_db": float(m["input_tp"]),
        "loudness_range": float(m["input_lra"]),
    }


def measure_delay_ms(reference: Path, processed: Path, *, windows: int = 3) -> float | None:
    """How many ms `processed` lags behind `reference` (cross-correlation, 8 kHz).

    Returns None if it cannot be measured reliably (numpy missing, silence)."""
    try:
        import numpy as np
    except ImportError:
        return None

    def load(p: Path):
        raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(p), "-map", "0:a:0",
                              "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True).stdout
        return np.frombuffer(raw, np.float32)

    a, b = load(reference), load(processed)
    n = min(len(a), len(b))
    max_lag, win = 800, 8000 * 4  # ±100 ms, 4-second windows
    if n < win + 2 * max_lag:
        return None
    lags = []
    for k in range(windows):
        s = max_lag + (n - win - 2 * max_lag) * (k + 1) // (windows + 1)
        x = a[s:s + win] - a[s:s + win].mean()
        if float(np.std(x)) < 1e-4:
            continue
        scores = [float(np.dot(x, b[s + L:s + L + win])) for L in range(-max_lag, max_lag + 1)]
        best = int(np.argmax(scores)) - max_lag
        y = b[s + best:s + best + win]
        corr = scores[best + max_lag] / (float(np.std(x)) * float(np.std(y)) * win + 1e-9)
        if corr > 0.5:
            lags.append(best / 8.0)
    if not lags:
        return None
    lags.sort()
    return lags[len(lags) // 2]


def _fix_delay(src: Path, master: Path, rate: int) -> float:
    """Shift `master` earlier by its measured delay; same length. Returns ms fixed."""
    lag = measure_delay_ms(src, master)
    if lag is None or abs(lag) < 1.0:
        return 0.0
    tmp = master.with_name(master.stem + ".sync.wav")
    if lag > 0:   # processed is late → cut the start, pad the end
        af = f"atrim=start={lag / 1000:.4f},asetpts=PTS-STARTPTS,apad=pad_dur={lag / 1000:.4f}"
    else:         # processed is early → delay it, trim the end
        af = f"adelay={-lag:.2f}:all=1"
    dur = audio_info(master)["duration_seconds"]
    run_ffmpeg(["-y", "-i", str(master), "-af", af, "-t", f"{dur:.4f}", "-ar", str(rate), "-ac", "1",
                "-c:a", "pcm_s24le", str(tmp)])
    tmp.replace(master)
    return round(lag, 1)


def process_voice(project: Project, recording: str | None = None, overrides: dict | None = None) -> dict:
    require_ffmpeg()
    opts = {**load_settings()["audio"], **{k: v for k, v in (overrides or {}).items() if v is not None}}

    src = project.recording_path(recording)
    meta_entry = next(r for r in project.recordings() if r["file"] == src.name)

    # 1) original must be exactly as when it was added
    if sha256_of(src) != meta_entry["sha256"]:
        raise RuntimeError(f"KHABARDAR: original recording badli hui lagti hai: {src.name}. Processing roki gayi.")

    info_before = audio_info(src)
    out_dir = project.processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    master = out_dir / f"{stem}_clean.wav"
    preview = out_dir / f"{stem}_clean_preview.m4a"
    report_file = out_dir / f"{stem}_report.json"

    chain = build_filter_chain(opts)

    # 2) measure original (for the before/after report)
    before = _measure(src, None, opts)

    # 3) Loudness: measure → one static gain → true-peak-safe limiter → re-measure.
    #    A single static gain keeps the voice natural (no "pumping" like dynamic
    #    normalisation). The limiter runs at 192 kHz (4x) so it also catches
    #    in-between-sample ("true") peaks. 2 small correction rounds hit the target
    #    within ~0.3 LU.
    #    Very "peaky" recordings would need heavy limiting to reach the target,
    #    which makes a voice sound squashed. Quality wins: extra limiting is capped
    #    at `max_limiting_db`, and the report says honestly if the target was missed.
    target = float(opts["target_lufs"])
    limit_db = float(opts["true_peak_db"]) - 0.5
    # latency=1: the limiter compensates its own look-ahead delay (keeps lip-sync)
    limiter = f"alimiter=limit={10 ** (limit_db / 20):.4f}:attack=5:release=60:level=0:latency=1"
    base_gain = target - float(_measure(src, chain, opts)["input_i"])
    max_extra = float(opts.get("max_limiting_db", 3.0))
    gain = base_gain
    final_chain = chain
    got = None
    for _ in range(6):
        final_chain = [*chain, "aresample=192000", f"volume={gain:.2f}dB", limiter]
        got = float(_measure(src, final_chain, opts)["input_i"])
        if abs(got - target) <= 0.3 or gain - base_gain >= max_extra:
            break
        gain = min(gain + (target - got) * 1.5, base_gain + max_extra)
    chain = final_chain
    loudness_note = None
    if got is not None and abs(got - target) > 1.0:
        loudness_note = (
            f"Target {target} LUFS tak poori tarah nahi pahunche ({got:.1f}) kyunke recording mein "
            "bohat tez peaks hain; zyada dabane se awaaz kharab hoti. Yeh theek hai — Phase 4 ka final mix "
            "dobara balance karega. Agli dafa mic ko munh se thora door (15–20 cm) rakhein."
        )

    # 4) render the final master
    af = ",".join(chain)
    run_ffmpeg([
        "-y", "-i", str(src), "-map", "0:a:0", "-af", af,
        "-ar", str(opts["sample_rate"]), "-ac", "1", "-c:a", "pcm_s24le", str(master),
    ])
    # 4b) Lip-sync: some filters (noise reduction) delay the sound by a few ms.
    #     Measure the delay against the original and remove it exactly.
    sync_fix_ms = _fix_delay(src, master, int(opts["sample_rate"]))
    # small AAC copy for quick listening on phone / browser
    run_ffmpeg(["-y", "-i", str(master), "-c:a", "aac", "-b:a", "192k", str(preview)])

    after = _measure(master, None, opts)
    info_after = audio_info(master)

    # 5) pictures for the preview page
    images = {}
    for label, path in (("original", src), ("clean", master)):
        wave = project.preview_dir / f"{stem}_{label}_waveform.png"
        spec = project.preview_dir / f"{stem}_{label}_spectrogram.png"
        project.preview_dir.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(["-y", "-i", str(path), "-filter_complex",
                    "[0:a:0]aformat=channel_layouts=mono,showwavespic=s=1200x200:colors=0x2f80ed[v]",
                    "-map", "[v]", "-frames:v", "1", "-update", "1", str(wave)])
        run_ffmpeg(["-y", "-i", str(path), "-filter_complex",
                    "[0:a:0]aformat=channel_layouts=mono,showspectrumpic=s=1200x300:legend=0:color=intensity[v]",
                    "-map", "[v]", "-frames:v", "1", "-update", "1", str(spec)])
        images[label] = {"waveform": wave.name, "spectrogram": spec.name}

    # 6) original must STILL be unchanged
    original_ok = sha256_of(src) == meta_entry["sha256"]
    if not original_ok:
        raise RuntimeError("KHABARDAR: processing ke baad original ka fingerprint badal gaya!")

    report = {
        "time": _dt.datetime.now().isoformat(timespec="seconds"),
        "original": {"file": src.name, "sha256": meta_entry["sha256"], "unchanged": original_ok,
                     **info_before, **_summary(before)},
        "clean": {"file": master.name, "preview_file": preview.name, **info_after, **_summary(after)},
        "settings": opts,
        "gain_db": round(gain, 2),
        "sync_fix_ms": sync_fix_ms,
        "extra_limiting_db": round(gain - base_gain, 2),
        "loudness_note": loudness_note,
        "filter_chain": chain,
        "images": images,
    }
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
