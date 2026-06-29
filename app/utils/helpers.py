"""Small reusable helpers."""
from __future__ import annotations

import re
from pathlib import Path

# Reasonably permissive URL matcher.
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Map a host substring to a human-readable platform label. TikTok first,
# since it's the primary target of this bot (including its short-link domains).
_PLATFORMS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("tiktok.com", "vm.tiktok", "vt.tiktok", "douyin.com"), "TikTok"),
    (("youtube.com", "youtu.be", "youtube-nocookie.com"), "YouTube"),
    (("instagram.com", "instagr.am"), "Instagram"),
    (("twitter.com", "x.com", "t.co"), "X / Twitter"),
    (("facebook.com", "fb.watch", "fb.com"), "Facebook"),
    (("vk.com", "vk.ru"), "VK"),
    (("twitch.tv",), "Twitch"),
    (("reddit.com", "redd.it"), "Reddit"),
)


def extract_url(text: str | None) -> str | None:
    """Return the first http(s) URL found in ``text``, or None."""
    if not text:
        return None
    match = _URL_RE.search(text)
    return match.group(0).rstrip(".,);]") if match else None


def detect_platform(url: str | None) -> str | None:
    """Return a friendly platform label for a URL (e.g. "TikTok"), or None."""
    if not url:
        return None
    host = url.lower()
    for needles, label in _PLATFORMS:
        if any(needle in host for needle in needles):
            return label
    return None


def is_tiktok(url: str | None) -> bool:
    """True if the URL points at TikTok (incl. short-link / Douyin domains)."""
    return detect_platform(url) == "TikTok"


def normalize_url(url: str | None) -> str | None:
    """Normalise known URL quirks before handing the URL to yt-dlp.

    TikTok photo (slideshow) posts use a ``/photo/`` path that many yt-dlp
    versions don't match ("Unsupported URL"). The same post is reachable via
    the ``/video/`` form, where yt-dlp returns the image carousel — so we
    rewrite ``/photo/`` to ``/video/`` for TikTok links.
    """
    if not url:
        return url
    if "tiktok.com" in url.lower() and "/photo/" in url:
        url = url.replace("/photo/", "/video/")
    return url


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
