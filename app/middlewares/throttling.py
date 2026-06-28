"""Simple per-user throttling middleware.

Uses an in-memory TTL cache to drop bursts of heavy requests from the same
user. For multi-instance deployments this can be swapped for a Redis-backed
implementation, but per-instance throttling is usually sufficient.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app import texts


class ThrottlingMiddleware(BaseMiddleware):
    """Rate-limit users to at most one heavy action every ``rate`` seconds."""

    def __init__(self, rate: float = 2.0) -> None:
        self.rate = rate
        self._last_seen: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        now = time.monotonic()
        last = self._last_seen.get(user.id, 0.0)

        if now - last < self.rate:
            # Notify the user without invoking the handler.
            if isinstance(event, CallbackQuery):
                await event.answer(texts.THROTTLED, show_alert=False)
            elif isinstance(event, Message):
                await event.answer(texts.THROTTLED)
            return None

        self._last_seen[user.id] = now
        return await handler(event, data)
