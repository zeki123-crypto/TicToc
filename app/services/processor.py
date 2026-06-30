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
import re
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


def _cap_scale() -> str:
    """ffmpeg scale fragment that caps the longest side to ``max_dimension``.

    Never upscales; keeps aspect; forces even dimensions. Returns a string with
    a trailing comma (or empty when the cap is disabled) for easy insertion.
    """
    d = settings.max_dimension
    if not d:
        return ""
    return (
        f"scale='if(gte(iw,ih),min({d},iw),-2)':"
        f"'if(gte(iw,ih),-2,min({d},ih))',"
    )


def _render_watermark_png(text: str, dest: Path, target_width: int | None = None) -> None:
    """Render watermark text to a transparent PNG using Pillow.

    Semi-transparent light-grey text with a faint dark outline (readable on any
    background). Avoids ffmpeg's ``drawtext`` (absent from the bundled build).
    If ``target_width`` is given, the image is resized to exactly that width
    (keeping aspect) so ffmpeg can overlay it without ``scale2ref``.
    """
    try:
        font = ImageFont.truetype(settings.watermark_font, 140)
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
        fill=(200, 200, 200, 105),
        stroke_width=stroke,
        stroke_fill=(0, 0, 0, 70),
    )

    if target_width and img.width:
        ratio = target_width / img.width
        img = img.resize(
            (target_width, max(1, round(img.height * ratio))), Image.LANCZOS
        )

    img.save(dest, "PNG")


async def _probe_dimensions(source: Path) -> tuple[int, int]:
    """Return (width, height) of the video, or (0, 0) if it can't be read."""
    exe = ffmpeg_path()
    if not exe:
        return 0, 0
    proc = await asyncio.create_subprocess_exec(
        exe, "-hide_banner", "-i", str(source),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode("utf-8", errors="replace")
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0


class VideoProcessor:
    """ffmpeg-based video transformations."""

    async def uniquify(self, source: Path) -> Path:
        """Produce a perceptually-similar but distinct copy of the video."""
        out = _output_path(source, "unique")

        # Randomised transforms so platforms (TikTok etc.) are less likely to
        # flag the result as a duplicate/repost. No mirror/flip (it visibly
        # reverses the content); instead a mix of light/colour correction, a
        # hue shift, a gentle sharpen, a zoom and a speed change. Every run
        # differs, and together they change every pixel + the colour/audio
        # fingerprints while looking natural.
        brightness = round(random.uniform(-0.07, 0.07), 3)
        contrast = round(random.uniform(0.90, 1.10), 3)
        saturation = round(random.uniform(0.88, 1.14), 3)
        gamma = round(random.uniform(0.92, 1.08), 3)
        hue_deg = round(random.uniform(-12, 12), 1)        # colour-tone shift
        hue_sat = round(random.uniform(0.94, 1.08), 3)
        sharpen = round(random.uniform(0.3, 0.9), 2)        # subtle detail change
        # Noticeable zoom (crop then scale back) changes framing & every pixel.
        crop_px = random.choice([8, 12, 16, 20])
        # Speed change shifts both the video and the audio fingerprint.
        tempo = round(random.uniform(0.93, 1.07), 3)
        # Frame-rate change alters the temporal fingerprint.
        fps = random.choice([24, 25, 30])
        # Subtle colour-balance shift (warmer/cooler) in shadows & midtones.
        cb = lambda: round(random.uniform(-0.06, 0.06), 3)  # noqa: E731
        rs, gs, bs, rm, gm, bm = cb(), cb(), cb(), cb(), cb(), cb()
        # Pitch shift (changes the audio fingerprint more than tempo alone).
        pitch = round(random.uniform(0.95, 1.05), 3)
        new_sr = int(48000 * pitch)
        fresh_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        # Crop (zoom) first, then downscale EARLY so the per-pixel filters
        # (eq/hue/colorbalance/unsharp) run at the reduced resolution — much
        # faster. ``_cap_scale`` also serves as the post-crop rescale; when the
        # cap is disabled we just keep the (slightly smaller) cropped frame.
        vf = (
            f"crop=iw-{crop_px}:ih-{crop_px},"
            f"{_cap_scale()}"
            f"eq=brightness={brightness}:contrast={contrast}:"
            f"saturation={saturation}:gamma={gamma},"
            f"hue=h={hue_deg}:s={hue_sat},"
            f"colorbalance=rs={rs}:gs={gs}:bs={bs}:rm={rm}:gm={gm}:bm={bm},"
            f"unsharp=5:5:{sharpen}:5:5:0.0,"
            f"fps={fps},"
            f"setpts={round(1 / tempo, 4)}*PTS,"
            "format=yuv420p"
        )
        # Shift pitch by `pitch` and set the overall tempo to `tempo`:
        # asetrate raises pitch+tempo, then atempo corrects the tempo back.
        af = (
            f"aresample=48000,asetrate={new_sr},aresample=48000,"
            f"atempo={round(tempo / pitch, 4)}"
        )

        args = [
            "-i", str(source),
            "-vf", vf,
            "-af", af,
            "-map_metadata", "-1",
            "-metadata", f"creation_time={fresh_ts}",
            "-threads", "0",
            "-c:v", "libx264",
            "-preset", settings.ffmpeg_preset,
            "-crf", "24",
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
        """Overlay a semi-transparent grey text watermark, centred, lower third.

        The text is rendered to a PNG with Pillow already sized to ~55% of the
        video width (so no ffmpeg ``scale2ref`` is needed — it's unreliable on
        the bundled ffmpeg 7.0), then composited with a plain ``overlay``.
        """
        out = _output_path(source, "wm")
        wm_png = source.with_name(f"{source.stem}_wm_{uuid.uuid4().hex[:8]}.png")

        # Work out the final (optionally capped) dimensions, then size the
        # watermark to ~55% of the final width.
        vid_w, vid_h = await _probe_dimensions(source)
        cap = settings.max_dimension
        if vid_w and vid_h and cap and max(vid_w, vid_h) > cap:
            factor = cap / max(vid_w, vid_h)
            out_w = (round(vid_w * factor) // 2) * 2
            out_h = (round(vid_h * factor) // 2) * 2
        else:
            out_w, out_h = vid_w, vid_h
        target_w = int(out_w * 0.55) if out_w else 600

        # Pillow is blocking — render (and resize) off the event loop.
        await asyncio.to_thread(_render_watermark_png, text, wm_png, target_w)

        # Scale the base video to the final size (if capped), then overlay the
        # PNG centred in the lower third. "-loop 1" + "shortest=1" make the
        # single PNG last for the whole video; [out] is mapped explicitly (a
        # complex filtergraph isn't auto-mapped); "0:a?" keeps audio if present.
        scale = f"scale={out_w}:{out_h}," if (out_w and (out_w, out_h) != (vid_w, vid_h)) else ""
        filter_complex = (
            f"[0:v]{scale}format=yuv420p[base];"
            "[base][1:v]overlay=(W-w)/2:(H-h)*0.72:shortest=1[out]"
        )
        args = [
            "-i", str(source),
            "-loop", "1", "-i", str(wm_png),
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-threads", "0",
            "-c:v", "libx264",
            "-preset", settings.ffmpeg_preset,
            "-crf", "24",
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

    async def extract_audio(self, source: Path) -> Path:
        """Extract the audio track from a video as an MP3 file."""
        token = uuid.uuid4().hex[:8]
        out = source.with_name(f"{source.stem}_audio_{token}.mp3")
        args = [
            "-i", str(source),
            "-vn",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            str(out),
        ]
        log.info("audio.start", source=str(source))
        await _run_ffmpeg(args)
        log.info("audio.done", out=str(out))
        return out
