"""Handles incoming links: downloads the video and offers the action menu."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import (
    FSInputFile,
    InputMediaPhoto,
    Message,
)

from app import keyboards, texts
from app.config import settings
from app.logging_config import get_logger
from app.services.downloader import (
    DownloadError,
    DurationLimitError,
    PhotoPostError,
    PhotoResult,
    VideoDownloader,
)
from app.handlers.sending import send_video
from app.services.session_store import ActiveVideo, SessionStore
from app.utils.helpers import (
    detect_platform,
    extract_url,
    format_duration,
    normalize_url,
    safe_unlink,
)

# Telegram allows at most 10 items per media group.
_ALBUM_CHUNK = 10

log = get_logger(__name__)
router = Router(name="download")


@router.message(F.text.regexp(r"https?://"))
async def handle_link(
    message: Message,
    downloader: VideoDownloader,
    store: SessionStore,
) -> None:
    """Download the video referenced by a link in the message."""
    url = extract_url(message.text)
    if not url:
        await message.answer(texts.NOT_A_LINK)
        return
    url = normalize_url(url)

    platform = detect_platform(url)
    status_text = (
        texts.DOWNLOADING_FROM.format(platform=platform)
        if platform
        else texts.DOWNLOADING
    )
    status = await message.answer(status_text)

    try:
        result = await downloader.download(url)
    except DurationLimitError as exc:
        await status.edit_text(
            texts.DURATION_TOO_LONG.format(
                duration=format_duration(exc.duration),
                limit=format_duration(settings.max_duration_seconds),
            )
        )
        return
    except PhotoPostError:
        await _handle_photo_post(message, status, downloader, url)
        return
    except DownloadError as exc:
        await status.edit_text(texts.DOWNLOAD_FAILED.format(error=str(exc)[:200]))
        return

    # Store the active video for this chat so processing handlers can find it.
    store.set(
        message.chat.id,
        ActiveVideo(
            path=result.path,
            title=result.title,
            duration=result.duration,
            url=url,
        ),
    )

    # Send the video itself, with the action buttons attached underneath it.
    await status.delete()
    caption = texts.VIDEO_READY_CAPTION.format(
        title=result.title[:80],
        duration=format_duration(result.duration),
    )
    await send_video(
        message,
        result.path,
        caption=caption,
        reply_markup=keyboards.action_menu(),
        cleanup=False,
    )


async def _handle_photo_post(
    message: Message,
    status: Message,
    downloader: VideoDownloader,
    url: str,
) -> None:
    """Download a TikTok photo slideshow and send the images as album(s)."""
    await status.edit_text(texts.PHOTO_DOWNLOADING)

    try:
        result: PhotoResult = await downloader.download_photos(url)
    except DownloadError as exc:
        await status.edit_text(texts.PHOTO_FAILED.format(error=str(exc)[:200]))
        return

    try:
        await status.edit_text(
            texts.PHOTO_DONE.format(title=result.title[:80], count=len(result.images))
        )
        # Telegram caps a media group at 10 items, so send in chunks.
        for start in range(0, len(result.images), _ALBUM_CHUNK):
            chunk = result.images[start : start + _ALBUM_CHUNK]
            media = [InputMediaPhoto(media=FSInputFile(p)) for p in chunk]
            await message.answer_media_group(media)

        # Send the background track, if TikTok provided one.
        if result.audio and result.audio.exists():
            await message.answer_audio(
                FSInputFile(result.audio), caption=texts.PHOTO_AUDIO_CAPTION
            )
    except Exception as exc:  # noqa: BLE001
        log.error("photo.send_failed", error=str(exc))
        await message.answer(texts.GENERIC_ERROR)
    finally:
        for path in result.all_paths():
            safe_unlink(path)


@router.message(F.text & ~F.text.startswith("/"))
async def handle_non_link(message: Message) -> None:
    """Any plain text that is not a command and not a link."""
    await message.answer(texts.NOT_A_LINK)
