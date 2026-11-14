"""Secret scanning before commits.

    python run.py secret-scan --staged     # what is about to be committed (used by the git hook)
    python run.py secret-scan --all        # every file tracked by git

Looks for real-looking tokens/keys (Google, Meta, TikTok, Anthropic, Hugging Face,
private keys, JWTs) and for files that must never be committed (.env, client
secrets, token files). Findings are shown MASKED — the scanner never prints a secret.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .redact import MASK

PATTERNS = {
    "Google OAuth access token": re.compile(r"ya29\.[A-Za-z0-9._-]{20,}"),
    "Google OAuth refresh token": re.compile(r"\b1//[A-Za-z0-9._-]{30,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "Google OAuth client secret": re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}"),
    "Meta access token": re.compile(r"\bEAA[A-Za-z0-9]{30,}"),
    "TikTok token": re.compile(r"\b(?:act|rft)\.[A-Za-z0-9!*._-]{30,}"),
    "Anthropic API key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    "Private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}"),
    "Secret assignment": re.compile(r"(?i)\b(client_secret|refresh_token|access_token|api_key)\b\s*[:=]\s*[\"']?"
                                    r"(?!\s|$|\"\"|''|None|null|<|\$\{|os\.|xxx)[A-Za-z0-9._/+=-]{16,}"),
}
FORBIDDEN_FILES = [re.compile(p) for p in (r"(^|/)\.env$", r"(^|/)\.env\.(?!example$)[^/]+$", r"client_secret[^/]*\.json$",
                                           r"(^|/)token[^/]*\.json$", r"\.pem$", r"\.p12$", r"(^|/)secrets/",
                                           r"(^|/)publish/private/")]
ALLOW_MARKER = "secret-scan: allow"


def _mask(s: str) -> str:
    return s[:6] + MASK if len(s) > 6 else MASK


def scan_text(text: str, name: str) -> list[dict]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line:
            continue
        for label, pat in PATTERNS.items():
            m = pat.search(line)
            if m:
                out.append({"file": name, "line": n, "type": label, "match": _mask(m.group(0))})
    return out


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _read_staged(path: str, cwd: Path) -> bytes:
    return subprocess.run(["git", "show", f":{path}"], cwd=cwd, capture_output=True).stdout


def scan(repo: Path, *, staged: bool) -> list[dict]:
    if staged:
        names = [n for n in _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"], repo).splitlines() if n]
    else:
        names = [n for n in _git(["ls-files"], repo).splitlines() if n]
    findings = []
    for name in names:
        if any(p.search(name) for p in FORBIDDEN_FILES):
            findings.append({"file": name, "line": 0, "type": "Yeh file kabhi commit nahi honi chahiye", "match": name})
            continue
        data = _read_staged(name, repo) if staged else (repo / name).read_bytes() if (repo / name).is_file() else b""
        if not data or b"\0" in data[:8192] or len(data) > 5_000_000:
            continue   # binary or very large (videos, fonts, images)
        findings += scan_text(data.decode("utf-8", errors="replace"), name)
    return findings


HOOK = """#!/bin/sh
# Secret scan before every commit (installed by: python run.py install-hooks)
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
exec "$PY" run.py secret-scan --staged
"""
