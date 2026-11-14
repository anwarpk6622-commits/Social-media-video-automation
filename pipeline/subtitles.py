"""Urdu subtitles: align script ↔ speech, build cues, write/read SRT.

Idea: Whisper is good at WHEN words are spoken but makes Urdu spelling
mistakes. Your script has the correct spelling. So we take the TEXT from the
script and the TIMING from Whisper ("forced alignment" by sequence matching).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path

from .align import align_words
from .urdu_text import ends_clause, ends_sentence, normalize, strip_direction_marks, tokenize_script

RLM = "‏"  # right-to-left mark: keeps punctuation on the correct side in players


# --------------------------------------------------------------- alignment
def _distribute(tokens: list[str], start: float, end: float) -> list[tuple[float, float]]:
    """Split a time span over tokens, proportional to their length."""
    weights = [len(normalize(t)) + 1 for t in tokens]
    total = sum(weights) or 1
    out, t = [], start
    for w in weights:
        d = (end - start) * w / total
        out.append((round(t, 3), round(t + d, 3)))
        t += d
    return out


def align(script_tokens: list[str], asr_words: list[dict]) -> dict:
    """Return words (text from script, timing from speech) + a quality report.

    The real work is in align.py (character-level, sound-aware global alignment)."""
    if not script_tokens:
        words = [{"text": w["text"], "start": w["start"], "end": w["end"], "source": "speech"} for w in asr_words]
        return {"words": words, "match_rate": None, "mode": "speech-only", "unclear": []}
    return align_words(script_tokens, asr_words)


# --------------------------------------------------------------- cues
# Urdu postpositions / helper words that should not START a subtitle line.
_GLUE = {normalize(w) for w in (
    "کا", "کی", "کے", "کو", "میں", "سے", "نے", "پر", "تک", "ہے", "ہیں", "تھا", "تھی", "تھے",
    "گا", "گی", "گے", "ہی", "بھی", "والا", "والی", "والے", "دیں", "کریں", "ہوں",
)}


def _is_glue(word: str) -> bool:
    return normalize(word) in _GLUE


def build_cues(words: list[dict], preset: dict) -> list[dict]:
    """Group timed words into on-screen subtitle cues."""
    timed = [w for w in words if w.get("start") is not None]
    cues: list[list[dict]] = []
    cur: list[dict] = []

    def text_of(ws):
        return " ".join(w["text"] for w in ws)

    for w in timed:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            too_long = len(text_of(cur + [w])) > preset["max_chars"]
            too_many = len(cur) >= preset["max_words"]
            too_slow = w["end"] - cur[0]["start"] > preset["max_seconds"]
            if gap > preset["gap_split"]:
                cues.append(cur)
                cur = []
            elif (ends_sentence(w["text"]) and len(cur) < preset["max_words"] + 1
                  and len(text_of(cur + [w])) <= preset["max_chars"] * 1.3
                  and w["end"] - cur[0]["start"] <= preset["max_seconds"] + 1.5):
                pass  # the sentence ends with this word: keep it, don't leave it alone on screen
            elif too_long or too_many or too_slow:
                # Forced break: don't start the next subtitle with a word that
                # belongs to the previous one (کا، کی، میں، ہے ...). Move a short
                # tail over to the next subtitle instead.
                cut = len(cur)
                nxt = w
                while cut > 1 and _is_glue(nxt["text"]) and len(cur) - cut < 3:
                    cut -= 1
                    nxt = cur[cut]
                if _is_glue(nxt["text"]):
                    cut = len(cur)  # no good place found: keep the simple break
                cues.append(cur[:cut])
                cur = cur[cut:]
        cur.append(w)
        if (ends_sentence(w["text"]) or w.get("break_after")
                or (ends_clause(w["text"]) and len(text_of(cur)) > preset["max_chars"] * 0.5)):
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)

    out = []
    for i, ws in enumerate(cues):
        start = ws[0]["start"]
        end = ws[-1]["end"] + 0.2
        nxt = cues[i + 1][0]["start"] if i + 1 < len(cues) else None
        if end - start < preset["min_seconds"]:
            end = start + preset["min_seconds"]
        if nxt is not None:
            end = min(end, nxt - 0.04)
        out.append({
            "start": round(start, 3), "end": round(max(end, start + 0.3), 3),
            "text": text_of(ws),
            "words": [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in ws],
        })
    return out


# --------------------------------------------------------------- SRT
def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_ts(s: str) -> float:
    h, m, rest = s.strip().replace(".", ",").split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def _wrap(text: str, max_line: int) -> list[str]:
    if len(text) <= max_line:
        return [text]
    words = text.split()
    best, best_diff = 1, 10**9
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        diff = abs(len(a) - len(b))
        if diff < best_diff:
            best, best_diff = k, diff
    return [" ".join(words[:best]), " ".join(words[best:])]


def write_srt(cues: list[dict], path: Path, max_line: int = 42) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        lines = [f"{RLM}{line}{RLM}" for line in _wrap(c["text"], max_line)]
        blocks.append(f"{i}\n{_ts(c['start'])} --> {_ts(c['end'])}\n" + "\n".join(lines))
    content = "\n\n".join(blocks) + "\n"
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_srt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        idx = next((k for k, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        a, b = lines[idx].split("-->")
        body = " ".join(strip_direction_marks(l).strip() for l in lines[idx + 1:])
        if body:
            cues.append({"start": _parse_ts(a), "end": _parse_ts(b.split()[0]), "text": " ".join(body.split())})
    return cues


def attach_word_times(srt_cues: list[dict], words: list[dict]) -> list[dict]:
    """For (possibly hand-edited) SRT cues, find each word's timing.

    If the cue text still matches the aligned words, their exact timings are
    used; otherwise (you edited the text) words are spread evenly over the cue."""
    timed = [w for w in words if w.get("start") is not None]
    out = []
    for c in srt_cues:
        tokens = c["text"].split()
        inside = [w for w in timed if c["start"] - 0.05 <= (w["start"] + w["end"]) / 2 <= c["end"] + 0.05]
        if [normalize(w["text"]) for w in inside] == [normalize(t) for t in tokens]:
            ws = [{"text": t, "start": w["start"], "end": w["end"]} for t, w in zip(tokens, inside)]
        else:
            ws = [{"text": t, "start": s, "end": e} for t, (s, e) in zip(tokens, _distribute(tokens, c["start"], c["end"]))]
        out.append({**c, "words": ws})
    return out


# --------------------------------------------------------------- whole step
def sha256_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_subtitles(sub_dir: Path, transcript: dict, script_text: str, settings: dict, *, force: bool = False) -> dict:
    """Align + make cues + write urdu.srt (16:9) and urdu_vertical.srt (9:16)."""
    sub_dir.mkdir(parents=True, exist_ok=True)
    words_file = sub_dir / "words.json"
    targets = {"landscape": sub_dir / "urdu.srt", "vertical": sub_dir / "urdu_vertical.srt"}

    # Never silently overwrite subtitles the user edited by hand.
    if words_file.exists():
        old = json.loads(words_file.read_text(encoding="utf-8"))
        edited = [p.name for k, p in targets.items()
                  if p.exists() and old.get("srt_hashes", {}).get(k) not in (None, sha256_text(p))]
        if edited and not force:
            raise FileExistsError(
                f"Aap ne {', '.join(edited)} haath se edit ki hai. Dobara banane se aap ki tabdeeliyan mit jaayengi. "
                "Agar phir bhi naya banana hai to --force lagayein (purani file ka backup ban jaayega)."
            )
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        for name in edited:
            p = sub_dir / name
            p.rename(sub_dir / f"{p.stem}.backup-{stamp}.srt")

    tokens = tokenize_script(script_text) if script_text else []
    al = align(tokens, transcript["words"])
    min_match = settings.get("min_script_match", 0.3)
    if al["match_rate"] is not None and al["match_rate"] < min_match:
        # Recording does not follow this script → don't force wrong text onto it.
        al = {**align([], transcript["words"]), "rejected_match_rate": al["match_rate"]}

    cues = {k: build_cues(al["words"], settings[k]) for k in targets}
    hashes = {k: write_srt(cues[k], p, settings[k].get("srt_line_chars", 42)) for k, p in targets.items()}

    flagged = sorted([w for w in al["words"] if w.get("check")] + al.get("unclear", []),
                     key=lambda w: w["start"] if w.get("start") is not None else 1e9)
    report = {
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "mode": al["mode"],
        "match_rate": al.get("match_rate"),
        "aligned_rate": al.get("aligned_rate"),
        "rejected_match_rate": al.get("rejected_match_rate"),
        "whisper_model": transcript.get("model"),
        "audio": transcript.get("audio"),
        "counts": {
            "words": len(al["words"]),
            "matched": sum(w["source"] == "matched" for w in al["words"]),
            "fitted": sum(w["source"] == "fitted" for w in al["words"]),
            "guessed": sum(w["source"] == "guessed" for w in al["words"]),
            "extra": sum(w["source"] == "extra" for w in al["words"]),
            "skipped": sum(w["source"] == "skipped" for w in al["words"]),
            "unclear": len(al.get("unclear", [])),
            "cues_landscape": len(cues["landscape"]),
            "cues_vertical": len(cues["vertical"]),
        },
        "to_check": [{"text": w["text"], "time": w["start"], "why": w["source"]} for w in flagged],
        "skipped": [w["text"] for w in al["words"] if w["source"] == "skipped"],
    }
    words_file.write_text(json.dumps({"report": report, "words": al["words"], "cues": cues, "srt_hashes": hashes},
                                     ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return {"report": report, "files": {k: str(p) for k, p in targets.items()}}
