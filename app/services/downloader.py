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

log = get_logger(__name__)


class DownloadError(Exception):
    """Raised when a video cannot be downloaded."""


class DurationLimitError(DownloadError):
    """Raised when a video exceeds the configured duration limit."""

    def __init__(self, duration: int) -> None:
        self.duration = duration
        super().__init__(f"Video too long: {duration}s")


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


class VideoDownloader:
    """Thin async wrapper around yt-dlp."""

    def __init__(self, download_dir: Path | None = None) -> None:
        self.download_dir = Path(download_dir or settings.download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _build_opts(self, output_template: str) -> dict:
        """Build yt-dlp options.

        We prefer an mp4/h264 result so the file plays everywhere and is ready
        for ffmpeg post-processing.
        """
        return {
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
            # Postprocessor guarantees a final mp4 container.
            "postprocessors": [
                {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
            ],
        }

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
        try:
            result = await asyncio.to_thread(self._download_sync, url)
        except DurationLimitError:
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
