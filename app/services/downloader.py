"""Video downloading service built on top of yt-dlp.

The blocking yt-dlp calls are executed in a worker thread so they never block
the asyncio event loop.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.config import settings
from app.logging_config import get_logger
from app.services import tiktok
from app.utils.ffmpeg import ffmpeg_path
from app.utils.helpers import is_tiktok

log = get_logger(__name__)


class DownloadError(Exception):
    """Raised when a video cannot be downloaded."""


class DurationLimitError(DownloadError):
    """Raised when a video exceeds the configured duration limit."""

    def __init__(self, duration: int) -> None:
        self.duration = duration
        super().__init__(f"Video too long: {duration}s")


class PhotoPostError(DownloadError):
    """Raised for image-only posts (e.g. a TikTok photo slideshow)."""

    def __init__(self) -> None:
        super().__init__("This post contains images, not a video.")


@dataclass(slots=True)
class DownloadResult:
    """Metadata about a downloaded video."""

    path: Path
    title: str
    duration: int
    width: int
    height: int
    ext: str

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


@dataclass(slots=True)
class PhotoResult:
    """Result of downloading an image-only post (e.g. a TikTok slideshow)."""

    images: list[Path]
    title: str
    audio: Path | None = None

    def all_paths(self) -> list[Path]:
        paths = list(self.images)
        if self.audio:
            paths.append(self.audio)
        return paths


class VideoDownloader:
    """Thin async wrapper around yt-dlp."""

    def __init__(self, download_dir: Path | None = None) -> None:
        self.download_dir = Path(download_dir or settings.download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _build_opts(self, output_template: str) -> dict:
        """Build yt-dlp options.

        We prefer an mp4/h264 result so the file plays everywhere and is ready
        for ffmpeg post-processing.

        TikTok note: yt-dlp's default "best" selection returns the
        **watermark-free** stream (``play_addr`` / bytevc), not the branded
        ``download_addr`` copy, so no special handling is needed to drop the
        TikTok logo. The ``bestvideo+bestaudio`` branch simply doesn't match
        TikTok's single muxed file and gracefully falls through to ``best``.
        """
        opts = {
            "outtmpl": output_template,
            "format": (
                "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/"
                "best[ext=mp4][height<=1080]/best"
            ),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "retries": 3,
            "socket_timeout": 30,
            "restrictfilenames": True,
            # Follow short-link redirects (vm.tiktok.com / vt.tiktok.com).
            "extractor_args": {"tiktok": {"webpage_download": ["1"]}},
            # Postprocessor guarantees a final mp4 container.
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
            ],
        }
        # Point yt-dlp at our resolved ffmpeg (system or imageio-bundled) so
        # merging/conversion works even when ffmpeg isn't on PATH.
        exe = ffmpeg_path()
        if exe:
            opts["ffmpeg_location"] = exe
        return opts

    @staticmethod
    def _is_photo_post(info: dict) -> bool:
        """Detect an image-only post (e.g. a TikTok photo slideshow)."""
        image_exts = {"jpg", "jpeg", "png", "webp", "heic", "gif"}

        # A slideshow is usually a playlist whose entries carry no video codec.
        entries = info.get("entries")
        if entries:
            first = entries[0] or {}
            formats = first.get("formats") or []
            has_video = any(
                f.get("vcodec") not in (None, "none") for f in formats
            ) or (first.get("vcodec") not in (None, "none"))
            return not has_video and not first.get("duration")

        formats = info.get("formats") or []
        if formats:
            return not any(f.get("vcodec") not in (None, "none") for f in formats)

        # Single-file result with an image extension and no duration.
        return info.get("ext") in image_exts and not info.get("duration")

    def _download_sync(self, url: str) -> DownloadResult:
        """Blocking download — runs in a worker thread."""
        token = uuid.uuid4().hex
        output_template = str(self.download_dir / f"{token}.%(ext)s")
        opts = self._build_opts(output_template)

        with yt_dlp.YoutubeDL(opts) as ydl:
            # First probe metadata so we can enforce the duration limit early.
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise DownloadError("No information returned for this URL.")

            # Reject image-only posts (e.g. TikTok photo slideshows) early.
            if self._is_photo_post(info):
                raise PhotoPostError()

            # A playlist/multi-entry result: take the first entry.
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0]

            duration = int(info.get("duration") or 0)
            limit = settings.max_duration_seconds
            if limit and duration > limit:
                raise DurationLimitError(duration)

            # Now actually download.
            info = ydl.extract_info(url, download=True)
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0]

            filename = ydl.prepare_filename(info)

        path = Path(filename)
        # The convertor may have changed the extension to .mp4.
        if not path.exists():
            mp4_candidate = path.with_suffix(".mp4")
            if mp4_candidate.exists():
                path = mp4_candidate
            else:
                matches = list(self.download_dir.glob(f"{token}.*"))
                if not matches:
                    raise DownloadError("Downloaded file not found on disk.")
                path = matches[0]

        return DownloadResult(
            path=path,
            title=(info.get("title") or "video").strip(),
            duration=int(info.get("duration") or 0),
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            ext=path.suffix.lstrip("."),
        )

    async def download(self, url: str) -> DownloadResult:
        """Download a video asynchronously.

        Raises:
            DurationLimitError: video exceeds the configured limit.
            DownloadError: any other failure.
        """
        log.info("download.start", url=url)

        # TikTok: use the resolver API first (reliable from servers).
        if is_tiktok(url):
            try:
                return await self._download_tiktok(url)
            except (DurationLimitError, PhotoPostError):
                raise
            except tiktok.TikTokError as exc:
                log.warning("tiktok.api_failed", url=url, error=str(exc))
                # fall through to yt-dlp as a backup

        try:
            result = await asyncio.to_thread(self._download_sync, url)
        except (DurationLimitError, PhotoPostError):
            raise
        except yt_dlp.utils.DownloadError as exc:  # type: ignore[attr-defined]
            log.warning("download.failed", url=url, error=str(exc))
            raise DownloadError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface as DownloadError
            log.error("download.error", url=url, error=str(exc))
            raise DownloadError(str(exc)) from exc

        log.info(
            "download.done",
            url=url,
            path=str(result.path),
            size_mb=round(result.size_bytes / (1024 * 1024), 2),
        )
        return result

    async def _download_tiktok(self, url: str) -> DownloadResult:
        """Download a TikTok video via the resolver API.

        Raises PhotoPostError for slideshow posts so the caller routes to the
        image flow, and TikTokError on API failure so the caller can fall back.
        """
        meta = await tiktok.fetch_meta(url)
        if meta.is_images:
            raise PhotoPostError()
        if not meta.video_url:
            raise tiktok.TikTokError("no video url in response")

        limit = settings.max_duration_seconds
        if limit and meta.duration > limit:
            raise DurationLimitError(meta.duration)

        path = await tiktok.download_video(meta.video_url, self.download_dir)
        log.info("tiktok.video.done", url=url, path=str(path))
        return DownloadResult(
            path=path,
            title=meta.title,
            duration=meta.duration,
            width=0,
            height=0,
            ext="mp4",
        )

    # ------------------------------------------------------------------ #
    #  Image-post (TikTok slideshow) support
    # ------------------------------------------------------------------ #
    _IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "heic", "gif"}
    _AUDIO_EXTS = {"mp3", "m4a", "aac", "opus", "ogg", "wav"}

    def _build_photo_opts(self, output_template: str) -> dict:
        """yt-dlp options for image posts.

        No video format selection and no mp4 convertor — we just let yt-dlp
        fetch every image (and the background track, when present) to disk.
        """
        opts = {
            "outtmpl": output_template,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "retries": 3,
            "socket_timeout": 30,
            "restrictfilenames": True,
            "ignoreerrors": True,
            "writethumbnail": False,
        }
        exe = ffmpeg_path()
        if exe:
            opts["ffmpeg_location"] = exe
        return opts

    def _download_photos_sync(self, url: str) -> PhotoResult:
        """Blocking image-post download — runs in a worker thread."""
        token = uuid.uuid4().hex
        output_template = str(self.download_dir / f"{token}.%(autonumber)s.%(ext)s")
        opts = self._build_photo_opts(output_template)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise DownloadError("No information returned for this URL.")
            title = (info.get("title") or "slideshow").strip()
            ydl.extract_info(url, download=True)

        # Collect everything written for this token and split by type.
        files = sorted(self.download_dir.glob(f"{token}.*"))
        images = [p for p in files if p.suffix.lstrip(".").lower() in self._IMAGE_EXTS]
        audio = next(
            (p for p in files if p.suffix.lstrip(".").lower() in self._AUDIO_EXTS),
            None,
        )

        if not images:
            # Clean up any stray files and report failure.
            for p in files:
                p.unlink(missing_ok=True)
            raise DownloadError("No images were found in this post.")

        return PhotoResult(images=images, title=title, audio=audio)

    async def _download_tiktok_photos(self, url: str) -> PhotoResult:
        """Download a TikTok slideshow (images + music) via the resolver API."""
        meta = await tiktok.fetch_meta(url)
        if not meta.image_urls:
            raise tiktok.TikTokError("no images in response")
        images, audio = await tiktok.download_images(
            meta.image_urls, meta.music_url, self.download_dir
        )
        return PhotoResult(images=images, title=meta.title, audio=audio)

    async def download_photos(self, url: str) -> PhotoResult:
        """Download all images (and music) of an image-only post."""
        log.info("photos.start", url=url)

        # TikTok: prefer the resolver API.
        if is_tiktok(url):
            try:
                result = await self._download_tiktok_photos(url)
                log.info("photos.done", url=url, count=len(result.images),
                         audio=bool(result.audio), via="tikwm")
                return result
            except tiktok.TikTokError as exc:
                log.warning("tiktok.photos_api_failed", url=url, error=str(exc))
                # fall through to yt-dlp

        try:
            result = await asyncio.to_thread(self._download_photos_sync, url)
        except DownloadError:
            raise
        except yt_dlp.utils.DownloadError as exc:  # type: ignore[attr-defined]
            log.warning("photos.failed", url=url, error=str(exc))
            raise DownloadError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            log.error("photos.error", url=url, error=str(exc))
            raise DownloadError(str(exc)) from exc

        log.info("photos.done", url=url, count=len(result.images), audio=bool(result.audio))
        return result
