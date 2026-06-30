"""Shared helper for sending a (possibly size-limited) video back to the user."""
from __future__ import annotations

from pathlib import Path

from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from app import texts
from app.config import settings
from app.logging_config import get_logger
from app.utils.helpers import human_size, safe_unlink

log = get_logger(__name__)


async def signature(message: Message) -> str:
    """A short '📥 Скачано в @bot' credit line (bot username resolved live)."""
    try:
        me = await message.bot.me()  # cached by aiogram after the first call
        if me.username:
            return f"\n\n📥 Скачано в @{me.username}"
    except Exception:  # noqa: BLE001
        pass
    return ""


async def send_video(
    message: Message,
    path: Path,
    caption: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
    cleanup: bool = False,
) -> bool:
    """Send a video file, enforcing the Telegram size limit.

    Returns True on success. When ``cleanup`` is set the file is removed
    afterwards (used for transient processed outputs that aren't kept around).
    """
    size = path.stat().st_size if path.exists() else 0
    if size == 0:
        await message.answer(texts.SESSION_EXPIRED)
        return False

    if size > settings.max_file_size_bytes:
        await message.answer(
            texts.FILE_TOO_LARGE.format(
                size=human_size(size), limit=settings.max_file_size_mb
            )
        )
        if cleanup:
            safe_unlink(path)
        return False

    try:
        await message.answer_video(
            FSInputFile(path),
            caption=f"{caption}{await signature(message)}",
            reply_markup=reply_markup,
            supports_streaming=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("send_video.failed", error=str(exc), path=str(path))
        await message.answer(texts.GENERIC_ERROR)
        return False
    finally:
        if cleanup:
            safe_unlink(path)
