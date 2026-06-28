"""Command handlers: /start, /help, /cancel."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.markdown import html_decoration as hd

from app import texts
from app.services.session_store import SessionStore

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = hd.quote(message.from_user.first_name or "друг")
    await message.answer(texts.START.format(name=name))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message, state: FSMContext, store: SessionStore
) -> None:
    current = await state.get_state()
    store.clear(message.chat.id)
    if current is None:
        await message.answer(texts.NOTHING_TO_CANCEL)
        return
    await state.clear()
    await message.answer(texts.CANCELLED)
