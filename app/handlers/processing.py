"""Handles the post-download actions: uniquify / watermark."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards, texts
from app.handlers.sending import send_video
from app.logging_config import get_logger
from app.services.processor import ProcessingError, VideoProcessor
from app.services.session_store import ActiveVideo, SessionStore
from app.states import WatermarkFlow

log = get_logger(__name__)
router = Router(name="processing")


def _get_active(store: SessionStore, chat_id: int) -> ActiveVideo | None:
    return store.get(chat_id)


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

    # Make the uniquified file the active video so a follow-up watermark is
    # applied to it (this also deletes the previous source file).
    store.set(
        query.message.chat.id,
        ActiveVideo(path=out, title=video.title, duration=video.duration),
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
