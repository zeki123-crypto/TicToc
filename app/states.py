"""Finite-state-machine states used across the bot."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class WatermarkFlow(StatesGroup):
    """States for collecting watermark configuration from the user."""

    waiting_for_text = State()
