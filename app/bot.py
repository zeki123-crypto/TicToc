"""Bot & dispatcher factory and application lifecycle."""
from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import settings
from app.handlers import get_main_router
from app.logging_config import get_logger
from app.middlewares.throttling import ThrottlingMiddleware
from app.services.downloader import VideoDownloader
from app.services.processor import VideoProcessor
from app.services.session_store import SessionStore

log = get_logger(__name__)


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


async def _on_shutdown(store: SessionStore) -> None:
    store.cleanup_all()
    log.info("bot.stopped")
