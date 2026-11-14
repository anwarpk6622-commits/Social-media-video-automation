"""Robust script ↔ speech alignment for Urdu (word level, sound-aware, global).

Why not simple exact word matching? When Whisper mis-hears a stretch of noisy
audio only a few words match exactly — and one wrongly matched common word
(e.g. «فون» from the NEXT sentence) can shift all following timings by seconds.

How it works:
1. Word similarity: two words are compared letter by letter, where letters that
   sound alike in Urdu count as near-matches (ص≈س≈ث≈ش, ز≈ذ≈ض≈ظ, ت≈ط≈ٹ, ...).
   So «شافہ» is close to «صاف», «راکھے» is close to «رکھیں».
2. Global word alignment (dynamic programming, like Needleman-Wunsch) of the whole
   script against the whole transcript. Allowed steps: 1 script word ↔ 1 spoken
   word, 1 ↔ 2 (Whisper split a word), 2 ↔ 1 (Whisper joined words), a script
   word not spoken (skipped), or a spoken word not in the script (extra).
   Because the WHOLE sequence is optimised together, a single wrong word cannot
   pull the timeline, and a skipped phrase becomes one clean gap.
"""

from __future__ import annotations

from functools import lru_cache

from .urdu_text import ends_sentence, normalize

# Letters that sound alike in Urdu (or that Whisper confuses): near-match.
_SOUND_GROUPS = [
    "سصثش", "زذضظ", "تطٹ", "دڈ", "رڑ", "کقگ", "ہھحۂ", "یےئ", "اآعء", "وؤ", "نں", "بپ", "جچ", "خغ",
]
_GROUP = {ch: gi for gi, g in enumerate(_SOUND_GROUPS) for ch in g}

# word-alignment scores
GAP = -0.30          # cost of a skipped script word / an extra spoken word
MIN_SIM = 0.35       # similarity at which a pairing starts to be "positive"
MERGE_COST = 0.10    # small extra cost for 1↔2 / 2↔1 pairings
_NEG = float("-inf")


def _char_score(a: str, b: str) -> int:
    if a == b:
        return 3
    ga, gb = _GROUP.get(a), _GROUP.get(b)
    return 1 if ga is not None and ga == gb else -2


@lru_cache(maxsize=200_000)
def similarity(x: str, y: str) -> float:
    """Sound-aware similarity of two normalised words: 1.0 identical, ≤0 unrelated."""
    if not x or not y:
        return -1.0
    if x == y:
        return 1.0
    n, m = len(x), len(y)
    prev = [-2 * j for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [-2 * i] + [0] * m
        xi = x[i - 1]
        for j in range(1, m + 1):
            cur[j] = max(prev[j - 1] + _char_score(xi, y[j - 1]), prev[j] - 2, cur[j - 1] - 2)
        prev = cur
    return prev[m] / (3 * max(n, m))


def _dp(s_keys: list[str], a_keys: list[str]) -> list[tuple[int, int, int, int]]:
    """Global alignment. Returns steps (i, di, j, dj): script[i:i+di] ↔ speech[j:j+dj]."""
    n, m = len(s_keys), len(a_keys)
    band = max(40, int(0.3 * max(n, m)))
    score = [[_NEG] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    score[0][0] = 0.0
    for j in range(1, m + 1):             # speech before the script starts: free
        score[0][j], back[0][j] = 0.0, (0, 1)

    def pair(si: str, aj: str) -> float:
        return similarity(si, aj) - MIN_SIM

    for i in range(0, n + 1):
        center = i * m / n if n else 0
        lo, hi = max(0, int(center - band)), min(m, int(center + band))
        for j in range(lo, hi + 1):
            if i == 0:
                continue
            best, how = _NEG, None
            # script word not spoken
            if score[i - 1][j] > _NEG:
                best, how = score[i - 1][j] + GAP, (1, 0)
            # spoken word not in the script
            if j >= 1 and score[i][j - 1] > _NEG:
                v = score[i][j - 1] + GAP
                if v > best:
                    best, how = v, (0, 1)
            # 1 ↔ 1
            if j >= 1 and score[i - 1][j - 1] > _NEG:
                v = score[i - 1][j - 1] + pair(s_keys[i - 1], a_keys[j - 1])
                if v > best:
                    best, how = v, (1, 1)
            # 1 ↔ 2 (Whisper split one word)
            if j >= 2 and score[i - 1][j - 2] > _NEG:
                v = score[i - 1][j - 2] + pair(s_keys[i - 1], a_keys[j - 2] + a_keys[j - 1]) * 1.5 - MERGE_COST
                if v > best:
                    best, how = v, (1, 2)
            # 2 ↔ 1 (Whisper joined two words)
            if i >= 2 and j >= 1 and score[i - 2][j - 1] > _NEG:
                v = score[i - 2][j - 1] + pair(s_keys[i - 2] + s_keys[i - 1], a_keys[j - 1]) * 1.5 - MERGE_COST
                if v > best:
                    best, how = v, (2, 1)
            score[i][j], back[i][j] = best, how

    # speech after the script ends: free
    j = max(range(m + 1), key=lambda jj: score[n][jj])
    steps = [(n, 0, jj, 1) for jj in range(m - 1, j - 1, -1)]
    i = n
    while i > 0 or j > 0:
        di, dj = back[i][j]
        i, j = i - di, j - dj
        steps.append((i, di, j, dj))
    steps.reverse()
    return steps


def align_words(script_tokens: list[str], asr_words: list[dict], *, extra_min_prob: float = 0.75) -> dict:
    s_keys = [normalize(t) for t in script_tokens]
    a_keys = [normalize(w["text"]) for w in asr_words]
    n = len(script_tokens)
    words: list[dict | None] = [None] * n
    extras: list[dict] = []
    steps = _dp(s_keys, a_keys) if n and asr_words else [(i, 1, 0, 0) for i in range(n)]

    for i, di, j, dj in steps:
        if di and dj:
            span_s, span_e = asr_words[j]["start"], asr_words[j + dj - 1]["end"]
            sk = "".join(s_keys[i:i + di])
            ak = "".join(a_keys[j:j + dj])
            sim = similarity(sk, ak)
            weights = [len(k) + 1 for k in s_keys[i:i + di]]
            tot, t = sum(weights), span_s
            for r, wgt in enumerate(weights):
                d = (span_e - span_s) * wgt / tot
                source = "matched" if sim >= 0.85 else "fitted"
                words[i + r] = {"text": script_tokens[i + r], "start": round(t, 3), "end": round(t + d, 3),
                                "source": source, "check": sim < 0.3, "sim": round(sim, 2)}
                t += d
        elif dj:  # spoken, not in script
            w = asr_words[j]
            sure = w.get("prob", 0) >= extra_min_prob and len(a_keys[j]) >= 2
            extras.append({"text": w["text"], "start": w["start"], "end": w["end"],
                           "source": "extra" if sure else "unclear", "check": True, "prob": w.get("prob")})

    # Script words with no spoken partner: skipped by the speaker — or missed by
    # Whisper? If there is a real silent stretch where they would fit, guess them in.
    timed = sorted([w for w in words if w] + extras, key=lambda w: w["start"])
    rates = [(w["end"] - w["start"]) / (len(normalize(w["text"])) + 1)
             for w in words if w and w["source"] == "matched"]
    rate = sorted(rates)[len(rates) // 2] if rates else 0.08     # seconds per letter
    k = 0
    while k < n:
        if words[k] is not None:
            k += 1
            continue
        e = k
        while e < n and words[e] is None:
            e += 1
        left = words[k - 1]["end"] if k else (asr_words[0]["start"] if asr_words else 0.0)
        right = words[e]["start"] if e < n else (asr_words[-1]["end"] if asr_words else left)
        run = script_tokens[k:e]
        expected = sum(len(normalize(t)) + 1 for t in run) * rate
        # Unmatched spoken words in the same gap = these script words, mis-heard.
        heard = [x for x in extras if left - 0.05 <= x["start"] < right]
        span = None
        if heard:
            span = (heard[0]["start"], max(right, heard[-1]["end"]) if e >= n else right)
            for x in heard:
                x["consumed"] = True
        elif (right - left) >= 0.7 * expected and (right - left) > 0.25:
            # a silent stretch where the words fit: Whisper probably missed them.
            # Speech usually starts just before the next word, after a breath.
            span = (max(left, right - expected * 1.1), right)
        elif len(run) <= 2 and k and words[k - 1] and words[k - 1]["source"] != "matched":
            # 1-2 short words lost inside a badly heard stretch: people skip whole
            # phrases, not a lone «کہ» / «اور» — so share the previous word's time.
            prev = words[k - 1]
            cut = prev["start"] + 0.55 * (prev["end"] - prev["start"])
            span = (cut, prev["end"])
            prev["end"] = round(cut, 3)
        if span:
            weights = [len(normalize(t)) + 1 for t in run]
            tot, t = sum(weights), span[0]
            for r, wgt in enumerate(weights):
                d = (span[1] - span[0]) * wgt / tot
                words[k + r] = {"text": run[r], "start": round(t, 3), "end": round(t + d, 3),
                                "source": "guessed", "check": True}
                t += d
        else:
            for r in range(len(run)):
                words[k + r] = {"text": run[r], "start": None, "end": None, "source": "skipped"}
            if k and any(ends_sentence(t) for t in run):
                words[k - 1]["break_after"] = True  # the sentence ended in the skipped part
        k = e

    out = [w for w in words if w is not None]
    free_extras = [x for x in extras if not x.pop("consumed", False)]
    on_screen = sorted([w for w in out if w["start"] is not None] + [x for x in free_extras if x["source"] == "extra"],
                       key=lambda w: w["start"])
    skipped = [w for w in out if w["start"] is None]
    return {
        "words": on_screen + skipped,
        "unclear": [x for x in free_extras if x["source"] == "unclear"],
        "match_rate": round(sum(w["source"] == "matched" for w in out) / n, 3) if n else None,
        "aligned_rate": round(sum(w["source"] in ("matched", "fitted") for w in out) / n, 3) if n else None,
        "mode": "script+speech",
    }
