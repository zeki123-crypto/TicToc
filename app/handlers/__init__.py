"""Aggregates all routers into a single one for easy registration."""
from __future__ import annotations

from aiogram import Router

from app.handlers import common, download, processing


def get_main_router() -> Router:
    """Build and return the root router with all sub-routers attached.

    Order matters: ``common`` (commands) is registered first so /cancel etc.
    take precedence over the generic link handler.
    """
    router = Router(name="main")
    router.include_router(common.router)
    router.include_router(processing.router)
    router.include_router(download.router)
    return router
