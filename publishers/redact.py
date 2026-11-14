"""Remove secrets from anything that is logged, printed or shown on the preview page."""

from __future__ import annotations

import re
from typing import Any

MASK = "***REDACTED***"

# Keys whose VALUES are always secret (case-insensitive substring match on the key).
SECRET_KEY_PARTS = ("token", "secret", "password", "passwd", "authorization", "api_key", "apikey",
                    "client_secret", "refresh", "cookie", "session_uri", "upload_url", "private_key", "credential")

# Value patterns (also inside free text such as error messages).
SECRET_PATTERNS = [
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]{10,}"),                  # Google OAuth access token
    re.compile(r"\b1//[A-Za-z0-9._-]{20,}"),                    # Google OAuth refresh token
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),                    # Google API key
    re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{10,}"),                 # Google OAuth client secret
    re.compile(r"\bEAA[A-Za-z0-9]{20,}"),                       # Meta (Facebook) access token
    re.compile(r"\b(?:act|rft|clt)\.[A-Za-z0-9!*._-]{16,}"),   # TikTok access / refresh / client tokens
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"),                 # Anthropic API key
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),                       # Hugging Face token
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(access_token|refresh_token|client_secret|api_key|password|upload_id|upload_url)"
               r"(\s*[=:]\s*|\"\s*:\s*\")([^\s\"&,}]{6,})"),
    re.compile(r"(?i)(https?://[^\s\"']*[?&](?:upload_id|access_token|key|sig|signature|token)=)[^\s\"'&]+"),
]


def redact_text(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pat in SECRET_PATTERNS:
        if pat.groups >= 3:
            out = pat.sub(lambda m: m.group(1) + m.group(2) + MASK, out)
        elif pat.groups == 1:
            out = pat.sub(lambda m: m.group(1) + MASK, out)
        else:
            out = pat.sub(MASK, out)
    return out


def is_secret_key(key: str) -> bool:
    k = str(key).lower()
    return any(part in k for part in SECRET_KEY_PARTS)


def redact(obj: Any) -> Any:
    """Deep copy of obj with every secret value masked."""
    if isinstance(obj, dict):
        return {k: (MASK if is_secret_key(k) and v not in (None, "", [], {}) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(redact(v) for v in obj)
    if isinstance(obj, str):
        return redact_text(obj)
    return obj
