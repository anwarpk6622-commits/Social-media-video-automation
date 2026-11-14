"""Small Urdu text helpers: normalisation for matching, and script tokenising."""

from __future__ import annotations

import re
import unicodedata

# Different keyboards / speech models write the "same" Urdu letter with
# different Unicode characters. For MATCHING only, map them to one form.
_CHAR_MAP = str.maketrans({
    "ي": "ی",  # Arabic yeh ي → Farsi/Urdu yeh ی
    "ى": "ی",  # alef maksura ى → ی
    "ك": "ک",  # Arabic kaf ك → keheh ک
    "ه": "ہ",  # heh ه → heh goal ہ
    "ە": "ہ",  # ae ە → ہ
    "ة": "ہ",  # teh marbuta ة → ہ
    "ۃ": "ہ",  # ۃ → ہ
    "آ": "ا",  # alef madda آ → ا  (ASR often drops the madda)
    "أ": "ا",
    "إ": "ا",
    "ۂ": "ہ",
    "ۓ": "ے",
})
_DIACRITICS = re.compile(r"[ً-ٰٟۖ-ۭـ]")  # zabar/zer/pesh, tatweel...
# Everything that is not a letter/digit — including Urdu punctuation, which sits
# inside the Arabic Unicode block: ، ؛ ؟ ۔ ٪ ٫ ٬ ٭ and quote/bracket marks.
_PUNCT = re.compile(r"[^\w؀-ۿ]+|[،؍؛؞؟٪-٭۔۝۞۩]+", re.U)
_DIRECTION_MARKS = re.compile(r"[‎‏‪-‮⁦-⁩]")

SENTENCE_END = ("۔", "؟", "!", "?", ".", "؛")
CLAUSE_END = ("،", ",", ":", "؛")


def strip_direction_marks(text: str) -> str:
    return _DIRECTION_MARKS.sub("", text)


def normalize(word: str) -> str:
    """Matching key: same spoken word → same key, whatever the spelling variant."""
    w = unicodedata.normalize("NFC", strip_direction_marks(word))
    w = _DIACRITICS.sub("", w).translate(_CHAR_MAP)
    w = _PUNCT.sub("", w)
    return w.lower()


def tokenize_script(text: str) -> list[str]:
    """Split the RECORDING SCRIPT into display words (punctuation stays attached).

    [PAUSE] and [CHECK: ...] notes are removed — they are never spoken.
    """
    text = re.sub(r"\[CHECK:[^\]]*\]", " ", text)
    text = re.sub(r"\[PAUSE\]", " ", text)
    text = strip_direction_marks(text)
    tokens = []
    for tok in text.split():
        if normalize(tok):
            tokens.append(tok)
        elif tokens:  # lone punctuation like "۔" → glue to previous word
            tokens[-1] += tok
    return tokens


def ends_sentence(word: str) -> bool:
    return word.rstrip().endswith(SENTENCE_END)


def ends_clause(word: str) -> bool:
    return word.rstrip().endswith(CLAUSE_END)
