"""Handles incoming links: downloads the video and offers the action menu."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app import keyboards, texts
from app.config import settings
from app.logging_config import get_logger
from app.services.downloader import (
    DownloadError,
    DurationLimitError,
    VideoDownloader,
)
from app.services.session_store import ActiveVideo, SessionStore
from app.utils.helpers import extract_url, format_duration

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

    status = await message.answer(texts.DOWNLOADING)

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
        ),
    )

    await status.edit_text(
        texts.DOWNLOAD_DONE.format(
            title=result.title[:80],
            duration=format_duration(result.duration),
        ),
        reply_markup=keyboards.action_menu(),
    )


@router.message(F.text & ~F.text.startswith("/"))
async def handle_non_link(message: Message) -> None:
    """Any plain text that is not a command and not a link."""
    await message.answer(texts.NOT_A_LINK)
