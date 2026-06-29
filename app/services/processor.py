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
import contextlib
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.logging_config import get_logger
from app.utils.ffmpeg import ffmpeg_path

log = get_logger(__name__)

# Bounds how many ffmpeg processes run at once across the whole bot.
_semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

# Hard cap on a single ffmpeg run so a stuck process can't hang the bot.
_FFMPEG_TIMEOUT = 300


class ProcessingError(Exception):
    """Raised when ffmpeg fails to process a video."""


async def _run_ffmpeg(args: list[str]) -> None:
    """Run ffmpeg with the given arguments, raising on failure."""
    exe = ffmpeg_path()
    if not exe:
        raise ProcessingError("ffmpeg is not available.")

    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    log.debug("ffmpeg.run", cmd=" ".join(cmd))

    async with _semaphore:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_FFMPEG_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            log.warning("ffmpeg.timeout", timeout=_FFMPEG_TIMEOUT)
            raise ProcessingError("processing timed out") from None

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        log.warning("ffmpeg.failed", returncode=proc.returncode, error=err[-500:])
        raise ProcessingError(err[-300:] or "ffmpeg exited with an error.")


def _output_path(source: Path, suffix: str) -> Path:
    """Build a unique output path next to the source file."""
    token = uuid.uuid4().hex[:8]
    return source.with_name(f"{source.stem}_{suffix}_{token}.mp4")


def _render_watermark_png(text: str, dest: Path) -> None:
    """Render watermark text to a transparent PNG using Pillow.

    We draw white text with a dark stroke (so it's readable on any background)
    on a fully transparent canvas. This avoids ffmpeg's ``drawtext`` filter,
    which is absent from the bundled (imageio) ffmpeg build.
    """
    try:
        font = ImageFont.truetype(settings.watermark_font, 96)
    except OSError:
        font = ImageFont.load_default()

    stroke = 4
    pad = 12
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = measure.textbbox(
        (0, 0), text, font=font, stroke_width=stroke
    )
    width = (right - left) + pad * 2
    height = (bottom - top) + pad * 2

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text(
        (pad - left, pad - top),
        text,
        font=font,
        fill=(255, 255, 255, 235),
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 160),
    )
    img.save(dest, "PNG")


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
        tempo = round(random.uniform(0.98, 1.02), 3)
        fresh_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        # NB: no per-pixel `noise` filter here — it's very CPU-heavy and would
        # stall encoding on small (1 vCPU) hosts. The crop/scale + colour tweaks
        # + full re-encode already change every pixel and all perceptual hashes.
        vf = (
            f"crop=iw-{crop_px}:ih-{crop_px},"
            f"scale=iw+{crop_px}:ih+{crop_px},"
            f"eq=brightness={brightness}:contrast={contrast}:"
            f"saturation={saturation}:gamma={gamma},"
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
            "-preset", "superfast",
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
        """Overlay a semi-transparent text watermark in the bottom-right corner.

        The text is rendered to a PNG with Pillow and composited via the
        ``overlay`` filter (sized to ~7% of the video height with ``scale2ref``),
        so it works even with the bundled ffmpeg that lacks ``drawtext``.
        """
        out = _output_path(source, "wm")
        wm_png = source.with_name(f"{source.stem}_wm_{uuid.uuid4().hex[:8]}.png")

        # Pillow is blocking — render off the event loop.
        await asyncio.to_thread(_render_watermark_png, text, wm_png)

        # Scale the watermark to ~7% of the video height and overlay it in the
        # bottom-right corner. Notes for the (minimal, bundled) ffmpeg:
        #   * "-loop 1" turns the single PNG into a continuous stream and
        #     "shortest=1" ends output with the video — without these the
        #     overlay produced "No filtered frames" (audio-only / black) output;
        #   * the result is labelled [out] and mapped explicitly, since with a
        #     complex filtergraph ffmpeg won't auto-map the video;
        #   * "0:a?" keeps the audio if the source has any.
        filter_complex = (
            "[1:v][0:v]scale2ref=w=-1:h=main_h*0.07[wm][base];"
            "[base][wm]overlay=W-w-25:H-h-25:shortest=1[out]"
        )
        args = [
            "-i", str(source),
            "-loop", "1", "-i", str(wm_png),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "superfast",
            "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(out),
        ]
        log.info("watermark.start", source=str(source), text=text)
        try:
            await _run_ffmpeg(args)
        finally:
            wm_png.unlink(missing_ok=True)
        log.info("watermark.done", out=str(out))
        return out
