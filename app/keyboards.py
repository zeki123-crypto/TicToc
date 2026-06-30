"""Inline keyboards and callback-data definitions."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- callback-data constants ---
CB_UNIQUIFY = "act:uniquify"
CB_WATERMARK = "act:watermark"
CB_AUDIO = "act:audio"
CB_CANCEL = "act:cancel"


def action_menu() -> InlineKeyboardMarkup:
    """Buttons shown under the downloaded video."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎲 Уникализировать", callback_data=CB_UNIQUIFY)
    )
    builder.row(
        InlineKeyboardButton(text="💧 Водяной знак", callback_data=CB_WATERMARK)
    )
    builder.row(
        InlineKeyboardButton(text="🎵 Вытащить звук", callback_data=CB_AUDIO)
    )
    return builder.as_markup()


def after_uniquify_menu() -> InlineKeyboardMarkup:
    """Buttons shown under a uniquified video (watermark / extract audio)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💧 Добавить водяной знак", callback_data=CB_WATERMARK
        )
    )
    builder.row(
        InlineKeyboardButton(text="🎵 Вытащить звук", callback_data=CB_AUDIO)
    )
    return builder.as_markup()
