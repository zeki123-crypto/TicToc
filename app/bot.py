"""Bot & dispatcher factory and application lifecycle."""
from __future__ import annotations

import asyncio
import contextlib
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import settings
from app.handlers import get_main_router
from app.logging_config import get_logger
from app.middlewares.throttling import ThrottlingMiddleware
from app.services import tiktok
from app.services.downloader import VideoDownloader
from app.services.processor import VideoProcessor
from app.services.session_store import SessionStore

log = get_logger(__name__)

# Holds the background cleanup task so it can be cancelled on shutdown.
_cleanup_task: asyncio.Task | None = None


async def _cleanup_loop() -> None:
    """Periodically delete stale temp files so disk can't fill under load."""
    ttl = max(60, settings.temp_file_ttl_minutes * 60)
    while True:
        await asyncio.sleep(300)
        now = time.time()
        removed = 0
        try:
            for path in settings.download_dir.glob("*"):
                try:
                    if path.is_file() and now - path.stat().st_mtime > ttl:
                        path.unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    continue
        except Exception as exc:  # noqa: BLE001
            log.warning("cleanup.error", error=str(exc))
        if removed:
            log.info("cleanup.removed", count=removed)


def create_bot() -> Bot:
    """Create the Bot with sane HTML-parse defaults."""
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def _build_storage():
    """Pick the FSM storage backend based on configuration."""
    if settings.use_redis:
        # Imported lazily so the dependency is only needed when configured.
        from aiogram.fsm.storage.redis import RedisStorage

        log.info("storage.redis", dsn=settings.redis_dsn)
        return RedisStorage.from_url(settings.redis_dsn)
    log.info("storage.memory")
    return MemoryStorage()


def create_dispatcher() -> Dispatcher:
    """Create the Dispatcher, wire DI, middleware and routers."""
    dp = Dispatcher(storage=_build_storage())

    # --- Dependency injection (available as handler kwargs by name) ---
    dp["downloader"] = VideoDownloader()
    dp["processor"] = VideoProcessor()
    store = SessionStore()
    dp["store"] = store

    # --- Middleware ---
    throttler = ThrottlingMiddleware(rate=settings.throttle_rate)
    dp.message.middleware(throttler)
    dp.callback_query.middleware(throttler)

    # --- Routers ---
    dp.include_router(get_main_router())

    # --- Lifecycle hooks ---
    dp.startup.register(_on_startup)
    dp.shutdown.register(_on_shutdown)

    return dp


async def _on_startup(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Справка"),
            BotCommand(command="cancel", description="Отменить действие"),
        ]
    )
    me = await bot.get_me()
    log.info("bot.started", username=me.username, id=me.id)

    global _cleanup_task
    _cleanup_task = asyncio.create_task(_cleanup_loop())


async def _on_shutdown(store: SessionStore) -> None:
    global _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _cleanup_task
        _cleanup_task = None
    store.cleanup_all()
    await tiktok.close_session()
    log.info("bot.stopped")
