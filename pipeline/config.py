"""Settings loader.

- config/settings.json  : normal settings (safe to commit)
- .env                  : secrets (NEVER committed, NEVER printed)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = ROOT / "config" / "settings.json"
ENV_FILE = ROOT / ".env"
PROJECTS_DIR = ROOT / "projects"
FONTS_DIR = ROOT / "assets" / "fonts"


def load_settings() -> dict:
    with open(SETTINGS_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_env(path: Path = ENV_FILE) -> None:
    """Very small .env reader. Existing environment variables win.

    Values are put into os.environ only; they are never logged or printed.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def secret_is_set(name: str) -> bool:
    """True if a secret exists, without ever revealing its value."""
    return bool(os.environ.get(name, "").strip())
