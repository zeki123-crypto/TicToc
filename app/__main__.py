"""Application entry point.

Run with:  python -m app
"""
from __future__ import annotations

import asyncio
import contextlib

import yt_dlp

from app import __version__
from app.bot import create_bot, create_dispatcher
from app.config import settings
from app.logging_config import get_logger, setup_logging


async def main() -> None:
    setup_logging(settings.log_level)
    log = get_logger("app")

    settings.download_dir.mkdir(parents=True, exist_ok=True)

    bot = create_bot()
    dp = create_dispatcher()

    # Build markers — confirm in logs which code/deps are actually deployed.
    log.info(
        "app.starting",
        version=__version__,
        ytdlp=yt_dlp.version.__version__,
        tiktok_api=True,
    )
    try:
        # Drop any updates accumulated while the bot was offline.
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
