"""Video post-processing service powered by ffmpeg.

Two capabilities are exposed:

* ``uniquify``  — apply a bundle of subtle, randomised transformations so the
  output differs (byte-wise and perceptually) from the source: stripped
  metadata, a tiny scale/crop, light colour adjustments, a faint noise layer,
  a micro speed change and a re-encode with a fresh creation timestamp.
* ``watermark`` — burn a text watermark into the bottom-right corner.

ffmpeg is invoked as a subprocess via ``asyncio.create_subprocess_exec`` so the
event loop is never blocked. A global semaphore bounds concurrency.
"""
from __future__ import annotations

import asyncio
import random
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.logging_config import get_logger

log = get_logger(__name__)

# Bounds how many ffmpeg processes run at once across the whole bot.
_semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)


class ProcessingError(Exception):
    """Raised when ffmpeg fails to process a video."""


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


async def _run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with the given arguments, raising on failure."""
    if not _ffmpeg_available():
        raise ProcessingError("ffmpeg is not installed or not on PATH.")

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args]
    log.debug("ffmpeg.run", cmd=" ".join(cmd))

    async with _semaphore:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        log.warning("ffmpeg.failed", returncode=proc.returncode, error=err[-500:])
        raise ProcessingError(err[-300:] or "ffmpeg exited with an error.")


def _output_path(source: Path, suffix: str) -> Path:
    """Build a unique output path next to the source file."""
    token = uuid.uuid4().hex[:8]
    return source.with_name(f"{source.stem}_{suffix}_{token}.mp4")


def _escape_drawtext(text: str) -> str:
    """Escape a string for use inside ffmpeg's drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace(":", r"\:")
    text = text.replace("'", r"’")  # avoid quote-parsing headaches
    text = text.replace("%", r"\%")
    return text


class VideoProcessor:
    """ffmpeg-based video transformations."""

    async def uniquify(self, source: Path) -> Path:
        """Produce a perceptually-similar but distinct copy of the video."""
        out = _output_path(source, "unique")

        # Randomised, subtle parameters — different on every run.
        brightness = round(random.uniform(-0.04, 0.04), 3)
        contrast = round(random.uniform(0.96, 1.05), 3)
        saturation = round(random.uniform(0.94, 1.07), 3)
        gamma = round(random.uniform(0.96, 1.04), 3)
        # Crop a few pixels and scale back up to the original size, which shifts
        # every pixel slightly without visibly changing the framing.
        crop_px = random.choice([2, 4, 6])
        noise_strength = random.choice([2, 3, 4])
        tempo = round(random.uniform(0.98, 1.02), 3)
        fresh_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        vf = (
            f"crop=iw-{crop_px}:ih-{crop_px},"
            f"scale=iw+{crop_px}:ih+{crop_px},"
            f"eq=brightness={brightness}:contrast={contrast}:"
            f"saturation={saturation}:gamma={gamma},"
            f"noise=alls={noise_strength}:allf=t+u,"
            f"setpts={round(1 / tempo, 4)}*PTS"
        )
        # Keep audio in sync with the video speed change.
        af = f"atempo={tempo}"

        args = [
            "-i", str(source),
            "-vf", vf,
            "-af", af,
            "-map_metadata", "-1",
            "-metadata", f"creation_time={fresh_ts}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(out),
        ]
        log.info("uniquify.start", source=str(source))
        await _run_ffmpeg(args)
        log.info("uniquify.done", out=str(out))
        return out

    async def watermark(self, source: Path, text: str) -> Path:
        """Burn a semi-transparent text watermark into the bottom-right corner."""
        out = _output_path(source, "wm")
        safe_text = _escape_drawtext(text)
        font = settings.watermark_font

        fontfile = f"fontfile='{font}':" if Path(font).exists() else ""
        drawtext = (
            f"drawtext={fontfile}text='{safe_text}':"
            "fontcolor=white@0.85:fontsize=h/18:"
            "box=1:boxcolor=black@0.4:boxborderw=8:"
            "x=w-tw-20:y=h-th-20"
        )

        args = [
            "-i", str(source),
            "-vf", drawtext,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ]
        log.info("watermark.start", source=str(source), text=text)
        await _run_ffmpeg(args)
        log.info("watermark.done", out=str(out))
        return out
