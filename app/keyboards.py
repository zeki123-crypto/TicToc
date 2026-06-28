"""Inline keyboards and callback-data definitions."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- callback-data constants ---
CB_SEND_ORIGINAL = "act:original"
CB_UNIQUIFY = "act:uniquify"
CB_WATERMARK = "act:watermark"
CB_CANCEL = "act:cancel"


def action_menu() -> InlineKeyboardMarkup:
    """Keyboard shown right after a successful download."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📤 Получить как есть", callback_data=CB_SEND_ORIGINAL)
    )
    builder.row(
        InlineKeyboardButton(text="🎲 Уникализировать", callback_data=CB_UNIQUIFY)
    )
    builder.row(
        InlineKeyboardButton(text="💧 Водяной знак", callback_data=CB_WATERMARK)
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data=CB_CANCEL)
    )
    return builder.as_markup()
