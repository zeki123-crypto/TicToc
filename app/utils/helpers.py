"""Small reusable helpers."""
from __future__ import annotations

import re
from pathlib import Path

# Reasonably permissive URL matcher.
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def extract_url(text: str | None) -> str | None:
    """Return the first http(s) URL found in ``text``, or None."""
    if not text:
        return None
    match = _URL_RE.search(text)
    return match.group(0).rstrip(".,);]") if match else None


def format_duration(seconds: float | int | None) -> str:
    """Format a duration in seconds as H:MM:SS or M:SS."""
    if not seconds:
        return "—"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def human_size(num_bytes: int | float) -> float:
    """Return size in megabytes."""
    return num_bytes / (1024 * 1024)


def safe_unlink(path: str | Path | None) -> None:
    """Delete a file if it exists, swallowing errors."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
