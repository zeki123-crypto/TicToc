"""Tracks the most recently downloaded file per user.

Kept deliberately small: the heavy state (current file path + metadata) lives
in the aiogram FSM context, but this store gives handlers a single, typed place
to read/write the "active video" for a chat and to clean up stale files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.utils.helpers import safe_unlink


@dataclass(slots=True)
class ActiveVideo:
    path: Path
    title: str
    duration: int
    # Source URL, kept so the file can be re-downloaded if it's lost from the
    # ephemeral disk (e.g. cleanup race or container restart).
    url: str | None = None


class SessionStore:
    """In-memory mapping of chat_id -> active video."""

    def __init__(self) -> None:
        self._videos: dict[int, ActiveVideo] = {}

    def set(self, chat_id: int, video: ActiveVideo) -> None:
        # Replace and clean up any previously stored file for this chat.
        self.clear(chat_id)
        self._videos[chat_id] = video

    def get(self, chat_id: int) -> ActiveVideo | None:
        video = self._videos.get(chat_id)
        if video and not video.path.exists():
            # File was removed externally; drop the dangling entry.
            self._videos.pop(chat_id, None)
            return None
        return video

    def clear(self, chat_id: int) -> None:
        video = self._videos.pop(chat_id, None)
        if video:
            safe_unlink(video.path)

    def cleanup_all(self) -> None:
        for chat_id in list(self._videos):
            self.clear(chat_id)
