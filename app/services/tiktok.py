"""TikTok download via a public resolver API (tikwm.com).

yt-dlp's TikTok extractor is unreliable from datacenter IPs ("Unable to extract
webpage video data"). This module uses tikwm.com, which returns the
watermark-free video (or slideshow images + music) and resolves short links
(vm./vt.tiktok.com) and ``/photo/`` posts on its own — so it works from servers.

It is used as the primary path for TikTok URLs; the caller falls back to yt-dlp
if this fails.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp

from app.logging_config import get_logger

log = get_logger(__name__)

_API = "https://www.tikwm.com/api/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TIMEOUT = aiohttp.ClientTimeout(total=60)


class TikTokError(Exception):
    """Raised when the TikTok API cannot resolve a URL."""


@dataclass(slots=True)
class TikTokMeta:
    is_images: bool
    title: str
    duration: int
    video_url: str | None
    image_urls: list[str] = field(default_factory=list)
    music_url: str | None = None


async def fetch_meta(url: str) -> TikTokMeta:
    """Resolve a TikTok URL to direct media links via tikwm."""
    params = {"url": url, "hd": "1"}
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.get(
                _API, params=params, headers={"User-Agent": _UA}
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
    except Exception as exc:  # noqa: BLE001
        raise TikTokError(f"request failed: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("code") != 0:
        msg = (payload or {}).get("msg") if isinstance(payload, dict) else None
        raise TikTokError(msg or "tikwm returned an error")

    data = payload.get("data") or {}
    images = data.get("images") or []
    music = data.get("music") or (data.get("music_info") or {}).get("play")

    return TikTokMeta(
        is_images=bool(images),
        title=(data.get("title") or "tiktok").strip() or "tiktok",
        duration=int(data.get("duration") or 0),
        video_url=data.get("hdplay") or data.get("play") or data.get("wmplay"),
        image_urls=list(images),
        music_url=music,
    )


async def _download_to(session: aiohttp.ClientSession, url: str, dest: Path) -> Path:
    """Stream a remote file to ``dest``."""
    async with session.get(url, headers={"User-Agent": _UA}) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            async for chunk in resp.content.iter_chunked(64 * 1024):
                fh.write(chunk)
    return dest


async def download_video(video_url: str, dest_dir: Path) -> Path:
    """Download a single TikTok video file."""
    dest = dest_dir / f"{uuid.uuid4().hex}.mp4"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            await _download_to(session, video_url, dest)
    except Exception as exc:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        raise TikTokError(f"video download failed: {exc}") from exc
    return dest


async def download_images(
    image_urls: list[str], music_url: str | None, dest_dir: Path
) -> tuple[list[Path], Path | None]:
    """Download all slideshow images and the background track."""
    token = uuid.uuid4().hex
    images: list[Path] = []
    audio: Path | None = None
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            for index, img_url in enumerate(image_urls):
                dest = dest_dir / f"{token}.{index:02d}.jpg"
                images.append(await _download_to(session, img_url, dest))
            if music_url:
                audio = await _download_to(
                    session, music_url, dest_dir / f"{token}.music.mp3"
                )
    except Exception as exc:  # noqa: BLE001
        for path in images:
            path.unlink(missing_ok=True)
        if audio:
            audio.unlink(missing_ok=True)
        raise TikTokError(f"images download failed: {exc}") from exc

    if not images:
        raise TikTokError("no images returned")
    return images, audio
