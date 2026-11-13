"""Urdu social media video automation pipeline (Phase 1 + 2).

Modules:
    config         - settings.json + .env loading (keys never printed)
    ffmpeg_tools   - small helpers around ffmpeg / ffprobe
    project        - project folders + protected original recordings
    script_writer  - Urdu script generation (free prompt mode / optional paid API mode)
    audio          - original-voice cleanup with FFmpeg (originals never modified)
    preview        - HTML preview report + Urdu font (RTL) render test
    doctor         - system check
"""

__version__ = "0.2.0"
