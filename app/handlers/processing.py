"""Handles the post-download actions: uniquify / watermark / extract audio."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app import keyboards, texts
from app.config import settings
from app.handlers.sending import send_video
from app.logging_config import get_logger
from app.services.downloader import VideoDownloader
from app.services.processor import ProcessingError, VideoProcessor
from app.services.session_store import ActiveVideo, SessionStore
from app.states import WatermarkFlow
from app.utils.helpers import human_size, safe_unlink

log = get_logger(__name__)
router = Router(name="processing")


def _get_active(store: SessionStore, chat_id: int) -> ActiveVideo | None:
    return store.get(chat_id)


async def _redownload(video: ActiveVideo, downloader: VideoDownloader) -> bool:
    """Re-fetch the source file from its URL into ``video.path``."""
    if not video.url:
        return False
    try:
        result = await downloader.download(video.url)
    except Exception as exc:  # noqa: BLE001
        log.warning("recover.redownload_failed", url=video.url, error=str(exc))
        return False
    video.path = result.path
    return True


async def _safe_process(
    video: ActiveVideo,
    downloader: VideoDownloader,
    op: Callable[[Path], Awaitable[Path]],
) -> Path | None:
    """Run ``op(video.path)``, recovering from a missing source file.

    The downloaded file lives on ephemeral disk and can disappear (cleanup
    race, restart). If it's gone — or ffmpeg fails because it vanished — we
    re-download from the source URL and retry once.
    """
    if not video.path.exists():
        if not await _redownload(video, downloader):
            return None
    try:
        return await op(video.path)
    except ProcessingError:
        if await _redownload(video, downloader):
            try:
                return await op(video.path)
            except ProcessingError as exc:
                log.warning("process.failed_after_recover", error=str(exc))
        return None


# --------------------------------------------------------------------------- #
#  Callback: uniquify
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == keyboards.CB_UNIQUIFY)
async def on_uniquify(
    query: CallbackQuery,
    store: SessionStore,
    processor: VideoProcessor,
    downloader: VideoDownloader,
) -> None:
    await query.answer()
    video = _get_active(store, query.message.chat.id)
    if not video:
        await query.message.answer(texts.SESSION_EXPIRED)
        return

    status = await query.message.answer(texts.PROCESSING)
    out = await _safe_process(video, downloader, processor.uniquify)
    if out is None:
        await status.edit_text(texts.PROCESSING_FAILED.format(error="—"))
        return

    # Make the uniquified file the active video so a follow-up watermark is
    # applied to it (keep the original URL as a recovery fallback).
    store.set(
        query.message.chat.id,
        ActiveVideo(
            path=out, title=video.title, duration=video.duration, url=video.url
        ),
    )

    await status.delete()
    await send_video(
        query.message,
        out,
        texts.UNIQUIFIED_CAPTION,
        reply_markup=keyboards.after_uniquify_menu(),
        cleanup=False,
    )


# --------------------------------------------------------------------------- #
#  Callback: extract audio
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == keyboards.CB_AUDIO)
async def on_extract_audio(
    query: CallbackQuery,
    store: SessionStore,
    processor: VideoProcessor,
    downloader: VideoDownloader,
) -> None:
    await query.answer()
    video = _get_active(store, query.message.chat.id)
    if not video:
        await query.message.answer(texts.SESSION_EXPIRED)
        return

    status = await query.message.answer(texts.EXTRACTING_AUDIO)
    out = await _safe_process(video, downloader, processor.extract_audio)
    if out is None:
        await status.edit_text(texts.PROCESSING_FAILED.format(error="—"))
        return

    await status.delete()
    try:
        size = out.stat().st_size if out.exists() else 0
        if size == 0 or size > settings.max_file_size_bytes:
            await query.message.answer(
                texts.FILE_TOO_LARGE.format(
                    size=human_size(size), limit=settings.max_file_size_mb
                )
                if size
                else texts.SESSION_EXPIRED
            )
            return
        await query.message.answer_audio(
            FSInputFile(out),
            caption=texts.AUDIO_CAPTION,
            title=video.title[:60],
        )
    except Exception as exc:  # noqa: BLE001
        log.error("audio.send_failed", error=str(exc))
        await query.message.answer(texts.GENERIC_ERROR)
    finally:
        safe_unlink(out)


# --------------------------------------------------------------------------- #
#  Callback: watermark (asks for text via FSM)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == keyboards.CB_WATERMARK)
async def on_watermark_request(
    query: CallbackQuery, store: SessionStore, state: FSMContext
) -> None:
    await query.answer()
    video = _get_active(store, query.message.chat.id)
    if not video:
        await query.message.answer(texts.SESSION_EXPIRED)
        return

    await state.set_state(WatermarkFlow.waiting_for_text)
    await query.message.answer(texts.ASK_WATERMARK_TEXT)


@router.message(WatermarkFlow.waiting_for_text, F.text)
async def on_watermark_text(
    message: Message,
    state: FSMContext,
    store: SessionStore,
    processor: VideoProcessor,
    downloader: VideoDownloader,
) -> None:
    text = (message.text or "").strip()
    if len(text) > 50:
        await message.answer(texts.WATERMARK_TOO_LONG)
        return

    video = _get_active(store, message.chat.id)
    if not video:
        await state.clear()
        await message.answer(texts.SESSION_EXPIRED)
        return

    await state.clear()
    status = await message.answer(texts.PROCESSING)
    out = await _safe_process(
        video, downloader, lambda p: processor.watermark(p, text)
    )
    if out is None:
        await status.edit_text(texts.PROCESSING_FAILED.format(error="—"))
        return

    await status.delete()
    await send_video(message, out, texts.WATERMARKED_CAPTION, cleanup=True)


# --------------------------------------------------------------------------- #
#  Callback: cancel (kept for older messages still showing a cancel button)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == keyboards.CB_CANCEL)
async def on_cancel(
    query: CallbackQuery, store: SessionStore, state: FSMContext
) -> None:
    await query.answer()
    await state.clear()
    store.clear(query.message.chat.id)
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - message may be too old to edit
        pass
    await query.message.answer(texts.CANCELLED)
