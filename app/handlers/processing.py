"""Handles the post-download action menu: send / uniquify / watermark."""
from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app import keyboards, texts
from app.config import settings
from app.logging_config import get_logger
from app.services.processor import ProcessingError, VideoProcessor
from app.services.session_store import ActiveVideo, SessionStore
from app.states import WatermarkFlow
from app.utils.helpers import human_size, safe_unlink

log = get_logger(__name__)
router = Router(name="processing")


async def _send_video(
    message: Message,
    path: Path,
    caption: str,
    *,
    cleanup: bool = True,
) -> bool:
    """Send a video file, enforcing the Telegram size limit.

    Returns True on success. When ``cleanup`` is set the file is removed
    afterwards (used for transient processed outputs).
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
            caption=caption,
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


def _get_active(store: SessionStore, chat_id: int) -> ActiveVideo | None:
    return store.get(chat_id)


# --------------------------------------------------------------------------- #
#  Callback: send original
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == keyboards.CB_SEND_ORIGINAL)
async def on_send_original(query: CallbackQuery, store: SessionStore) -> None:
    await query.answer()
    video = _get_active(store, query.message.chat.id)
    if not video:
        await query.message.answer(texts.SESSION_EXPIRED)
        return

    # Don't delete the source here — keep it so the user can still process it.
    await _send_video(
        query.message, video.path, texts.ORIGINAL_CAPTION, cleanup=False
    )


# --------------------------------------------------------------------------- #
#  Callback: uniquify
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == keyboards.CB_UNIQUIFY)
async def on_uniquify(
    query: CallbackQuery, store: SessionStore, processor: VideoProcessor
) -> None:
    await query.answer()
    video = _get_active(store, query.message.chat.id)
    if not video:
        await query.message.answer(texts.SESSION_EXPIRED)
        return

    status = await query.message.answer(texts.PROCESSING)
    try:
        out = await processor.uniquify(video.path)
    except ProcessingError as exc:
        await status.edit_text(texts.PROCESSING_FAILED.format(error=str(exc)[:200]))
        return

    await status.delete()
    await _send_video(query.message, out, texts.UNIQUIFIED_CAPTION, cleanup=True)


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
    try:
        out = await processor.watermark(video.path, text)
    except ProcessingError as exc:
        await status.edit_text(texts.PROCESSING_FAILED.format(error=str(exc)[:200]))
        return

    await status.delete()
    await _send_video(message, out, texts.WATERMARKED_CAPTION, cleanup=True)


# --------------------------------------------------------------------------- #
#  Callback: cancel
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
