"""Locate an ffmpeg binary.

Prefer a system-installed ffmpeg (full build, includes ffprobe). If none is on
PATH — common on auto-build PaaS environments — fall back to the binary bundled
with the ``imageio-ffmpeg`` pip package, so the bot's video features work
everywhere without apt.
"""
from __future__ import annotations

import shutil
from functools import lru_cache


@lru_cache
def ffmpeg_path() -> str | None:
    """Return a path to an ffmpeg executable, or None if unavailable."""
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - package missing or no bundled binary
        return None


@lru_cache
def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None
