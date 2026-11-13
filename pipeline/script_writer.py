"""Urdu script generation.

Two modes:
  FREE  (default) - builds a complete prompt you paste into the claude.ai chat.
                    No API key, no cost.
  API   (opt-in)  - calls the Claude API. Shows a cost estimate first and asks
                    for "yes" before spending anything. Needs ANTHROPIC_API_KEY
                    in .env and `pip install anthropic`.

Both modes use the same section format, so `check_script()` works for both.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .config import load_env, load_settings, secret_is_set

# Section markers. Keep them in English so the parser is reliable;
# the content inside is Urdu.
SECTIONS = [
    ("TITLES", "5 title options (Urdu, with a few English keywords for search)"),
    ("HOOK", "the first 3 seconds — one or two lines that stop the scroll"),
    ("RECORDING SCRIPT", "the exact words the creator will read aloud"),
    ("SHORT VERSION", "a 45–60 second version for YouTube Shorts / TikTok / Facebook Reels"),
    ("VISUAL AND SOUND CUES", "B-roll, sound effects and on-screen text per part of the script"),
    ("DESCRIPTION", "YouTube / Facebook description"),
    ("HASHTAGS", "10–15 hashtags, Urdu + English"),
]

TEMPLATE_HEADER = "<!-- Claude ka jawab is line ke NEECHE paste karein. Headings (## [ ... ]) mat badlein. -->\n"


@dataclass
class ScriptRequest:
    topic: str
    minutes: float
    audience: str
    tone: str
    call_to_action: str
    extra_notes: str = ""


SYSTEM_PROMPT = (
    "You are an experienced Urdu scriptwriter for YouTube, TikTok and Facebook creators in Pakistan. "
    "You write natural, spoken Urdu that sounds like a real person talking to a friend — never stiff, "
    "never like a news bulletin. The creator records the script in their own voice, so it must be easy "
    "to read aloud. You never invent statistics, quotes or facts you are not sure of; when a fact would "
    "help, you write it as a clearly marked [CHECK: ...] note for the creator to verify."
)


def build_prompt(req: ScriptRequest, words_per_minute: int) -> str:
    target_words = int(req.minutes * words_per_minute)
    section_list = "\n".join(f"## [{name}]\n({desc})" for name, desc in SECTIONS)
    notes = f"\nExtra notes from the creator: {req.extra_notes}\n" if req.extra_notes else ""
    return f"""Write a complete video script in Urdu for my channel.

TOPIC: {req.topic}
AUDIENCE: {req.audience}
TONE: {req.tone}
LENGTH: about {req.minutes:g} minutes when read aloud (≈ {target_words} Urdu words in the RECORDING SCRIPT, at ~{words_per_minute} words per minute)
CALL TO ACTION at the end: {req.call_to_action}
{notes}
Writing rules:
1. Write in Urdu script (اردو), not Roman Urdu. Common English tech words (YouTube, mobile, app, video) may stay in English letters.
2. Simple everyday Urdu. Short sentences. One idea per sentence.
3. Structure of the RECORDING SCRIPT: Hook → why this matters to the viewer → 3 to 5 clear main points with a simple example each → quick recap → call to action.
4. Put [PAUSE] where the speaker should take a short breath. Do not put any other stage directions inside the RECORDING SCRIPT — it must be clean text to read.
5. The SHORT VERSION must stand alone, start with the strongest line, and fit in 60 seconds.
6. In VISUAL AND SOUND CUES use one line per script part, in this form:
   - <first few words of the line> → B-roll: ... | SFX: ... | On-screen text: ...
7. Do not invent facts, numbers or quotes. Mark anything that needs checking as [CHECK: ...].
8. Keep the creator's real identity: no fake claims about who they are or what they have done.

Reply with EXACTLY these section headings, in this order, and nothing before the first heading:

{section_list}
"""


def _api_cost_estimate(req: ScriptRequest, prompt: str, cfg: dict) -> dict:
    """Honest rough estimate. Real cost is printed after the call from the API's own usage numbers."""
    p_in = cfg["price_per_million_input_usd"] / 1_000_000
    p_out = cfg["price_per_million_output_usd"] / 1_000_000
    # English/Roman text ≈ 4 characters per token; be generous.
    input_tokens = int((len(prompt) + len(SYSTEM_PROMPT)) / 3) + 50
    # Urdu tokenizes heavier than English: assume ~3 tokens per Urdu word.
    words = req.minutes * cfg["words_per_minute"]
    expected_output = int(words * 2.5 * 3) + 2500  # all sections + thinking
    max_output = cfg["max_output_tokens"]
    return {
        "input_tokens": input_tokens,
        "expected_output_tokens": expected_output,
        "max_output_tokens": max_output,
        "expected_usd": round(input_tokens * p_in + expected_output * p_out, 3),
        "max_usd": round(input_tokens * p_in + max_output * p_out, 3),
    }


def write_free_mode(project, req: ScriptRequest) -> dict:
    """FREE mode: save prompt.txt + an empty script.md to paste into."""
    settings = load_settings()
    prompt = build_prompt(req, settings["script"]["words_per_minute"])
    sd = project.script_dir
    sd.mkdir(parents=True, exist_ok=True)
    prompt_file = sd / "prompt.txt"
    prompt_file.write_text(
        "=== 1) Yeh poora text copy karein aur https://claude.ai ki nayi chat mein paste karein ===\n\n"
        + SYSTEM_PROMPT + "\n\n" + prompt,
        encoding="utf-8",
    )
    script_file = sd / "script.md"
    if not script_file.exists():
        script_file.write_text(
            f"# Script: {req.topic}\n\n" + TEMPLATE_HEADER + "\n",
            encoding="utf-8",
        )
    return {"prompt_file": prompt_file, "script_file": script_file}


def write_api_mode(project, req: ScriptRequest, *, assume_yes: bool = False, input_fn=input) -> dict:
    """PAID mode: estimate → ask → call Claude → save. Nothing is spent without 'yes'."""
    load_env()
    settings = load_settings()
    cfg = settings["script"]
    if not secret_is_set("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY .env file mein nahi mili. Free mode istemal karein (bina --use-api), "
            "ya README ke 'Paid API mode' hisse ke mutabiq key add karein."
        )
    try:
        import anthropic  # optional dependency
    except ImportError as e:
        raise RuntimeError("'anthropic' package install nahi. Chalayein: pip install -r requirements-optional.txt") from e

    model = os.environ.get("CLAUDE_MODEL", "").strip() or cfg["model"]
    prompt = build_prompt(req, cfg["words_per_minute"])
    est = _api_cost_estimate(req, prompt, cfg)

    print("\n💰 LAGAT KA ANDAZA (Claude API — paid service)")
    print(f"   Model: {model}")
    print(f"   Andaazan lagat:  ~${est['expected_usd']}   (zyada se zyada: ${est['max_usd']})")
    print("   Yeh paisay aap ke Anthropic account se katenge.")
    if not assume_yes:
        answer = input_fn("   Kya aage barhein? 'yes' likhein, warna Enter dabayein: ").strip().lower()
        if answer not in ("yes", "y", "haan", "han"):
            print("   ❎ Cancel. Koi paisa kharch nahi hua.")
            return {"cancelled": True, "estimate": est}

    client = anthropic.Anthropic()
    try:
        # Server-side fallback: if the main model declines a request for a safety
        # reason, the API automatically retries on a suitable fallback model.
        response = client.beta.messages.create(
            model=model,
            max_tokens=cfg["max_output_tokens"],
            system=SYSTEM_PROMPT,
            output_config={"effort": cfg.get("effort", "medium")},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("API key ghalat hai. console.anthropic.com se nayi key bana kar .env mein lagayein.")
    except anthropic.PermissionDeniedError:
        raise RuntimeError("Is key ko is model ki ijazat nahi. Anthropic console check karein.")
    except anthropic.RateLimitError:
        raise RuntimeError("Bohat zyada requests / credit khatam. Thori der baad ya billing check karein.")
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude API error ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        raise RuntimeError("Internet / network masla. Connection check kar ke dobara koshish karein.")

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude ne is topic par script likhne se inkar kiya. Topic thora badal kar dekhein.")

    text = "".join(b.text for b in response.content if b.type == "text").strip()
    usage = response.usage
    p_in = cfg["price_per_million_input_usd"] / 1_000_000
    p_out = cfg["price_per_million_output_usd"] / 1_000_000
    actual_usd = round(usage.input_tokens * p_in + usage.output_tokens * p_out, 4)

    sd = project.script_dir
    sd.mkdir(parents=True, exist_ok=True)
    script_file = sd / "script.md"
    if script_file.exists() and _has_content(script_file.read_text(encoding="utf-8")):
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        script_file.rename(sd / f"script.backup-{stamp}.md")  # never lose a previous script
    script_file.write_text(f"# Script: {req.topic}\n\n{text}\n", encoding="utf-8")

    log = {
        "time": _dt.datetime.now().isoformat(timespec="seconds"),
        "model_requested": model,
        "model_served": response.model,
        "stop_reason": response.stop_reason,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "approx_cost_usd": actual_usd,
        "estimate": est,
        "request_id": getattr(response, "_request_id", None),
    }
    with open(sd / "api_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    if response.stop_reason == "max_tokens":
        print("   ⚠️ Script poori nahi hui (lambai ki had). 'script check' se dekhein, ya minutes kam karein.")
    print(f"   ✅ Asal lagat (andaazan): ${actual_usd}  — tafseel: {sd / 'api_log.jsonl'}")
    return {"script_file": script_file, "log": log}


# ---------------------------------------------------------------- checking
# Tolerant: accepts "## [HOOK]", "[HOOK]", "**HOOK**", "### HOOK:" — so it still works
# when the reply is copied by selecting text instead of the Copy button.
_NAMES = "|".join(re.escape(name) for name, _ in SECTIONS)
_HEADING = re.compile(
    rf"^[ \t]*(?:#{{1,6}}[ \t]*)?(?:\*\*)?[ \t]*\[?[ \t]*({_NAMES})[ \t]*\]?[ \t]*(?:\*\*)?[ \t]*:?[ \t]*$",
    re.M | re.I,
)
_URDU_OR_WORD = re.compile(r"[\w؀-ۿ]+", re.U)


def _has_content(text: str) -> bool:
    return bool(_HEADING.search(text))


def parse_sections(text: str) -> dict[str, str]:
    parts = {}
    matches = list(_HEADING.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts[m.group(1).strip().upper()] = text[m.end():end].strip()
    return parts


def count_words(text: str) -> int:
    cleaned = re.sub(r"\[(PAUSE|CHECK:[^\]]*)\]", " ", text)
    return len(_URDU_OR_WORD.findall(cleaned))


def check_script(path: Path, words_per_minute: int) -> dict:
    """Validate sections + estimate how long the recording will be."""
    text = Path(path).read_text(encoding="utf-8")
    sections = parse_sections(text)
    expected = [name for name, _ in SECTIONS]
    missing = [s for s in expected if s not in sections or not sections[s]]
    rec = sections.get("RECORDING SCRIPT", "")
    short = sections.get("SHORT VERSION", "")
    rec_words = count_words(rec)
    short_words = count_words(short)
    checks = re.findall(r"\[CHECK:([^\]]*)\]", text)
    return {
        "sections_found": [s for s in expected if s in sections],
        "missing_sections": missing,
        "recording_words": rec_words,
        "recording_minutes": round(rec_words / words_per_minute, 1) if words_per_minute else 0,
        "short_words": short_words,
        "short_seconds": round(short_words / words_per_minute * 60) if words_per_minute else 0,
        "pauses": rec.count("[PAUSE]"),
        "facts_to_check": [c.strip() for c in checks],
        "has_urdu": bool(re.search(r"[؀-ۿ]", rec)),
    }


def export_reading_script(path: Path, out: Path) -> Path:
    """Write a clean, large-font-friendly text of only the RECORDING SCRIPT."""
    sections = parse_sections(Path(path).read_text(encoding="utf-8"))
    rec = sections.get("RECORDING SCRIPT", "").strip()
    if not rec:
        raise ValueError("script.md mein '## [RECORDING SCRIPT]' hissa khaali hai.")
    rec = re.sub(r"[ \t]*\[CHECK:[^\]]*\]", "", rec)  # notes are for checking, not for reading aloud
    rec = re.sub(r"[ \t]*\[PAUSE\][ \t]*", "\n   ⏸\n", rec)
    out.write_text(rec.strip() + "\n", encoding="utf-8")
    return out
