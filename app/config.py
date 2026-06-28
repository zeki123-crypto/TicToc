"""Application configuration.

All settings are loaded from environment variables (or a local ``.env`` file)
and validated by pydantic. Import the singleton ``settings`` from anywhere.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: str = Field(..., alias="BOT_TOKEN")
    admin_ids: list[int] = Field(default_factory=list, alias="ADMIN_IDS")

    # --- Storage ---
    storage_type: str = Field("memory", alias="STORAGE_TYPE")
    redis_dsn: str = Field("redis://localhost:6379/0", alias="REDIS_DSN")

    # --- Downloads ---
    download_dir: Path = Field(Path("downloads"), alias="DOWNLOAD_DIR")
    max_file_size_mb: int = Field(50, alias="MAX_FILE_SIZE_MB")
    max_duration_seconds: int = Field(1800, alias="MAX_DURATION_SECONDS")

    # --- Rate limiting & processing ---
    throttle_rate: float = Field(2.0, alias="THROTTLE_RATE")
    max_concurrent_jobs: int = Field(2, alias="MAX_CONCURRENT_JOBS")
    watermark_font: str = Field(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        alias="WATERMARK_FONT",
    )

    # --- Logging ---
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> list[int]:
        """Accept a comma-separated string or a list of ids."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [int(part.strip()) for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple)):
            return [int(v) for v in value]
        raise ValueError("ADMIN_IDS must be a comma-separated string of ids")

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def use_redis(self) -> bool:
        return self.storage_type.lower() == "redis"

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
