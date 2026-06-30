"""Application configuration.

All settings are loaded from environment variables (or a local ``.env`` file)
and validated by pydantic. Import the singleton ``settings`` from anywhere.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_REDIS = "redis://localhost:6379/0"
# Font shipped with the package so watermarks work in any environment.
_BUNDLED_FONT = Path(__file__).resolve().parent / "assets" / "DejaVuSans-Bold.ttf"


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
    # Some managed Redis add-ons expose ``REDIS_URL``, so we accept either
    # ``REDIS_DSN`` or ``REDIS_URL``.
    storage_type: str = Field("memory", alias="STORAGE_TYPE")
    redis_dsn: str = Field(
        _DEFAULT_REDIS,
        validation_alias=AliasChoices("REDIS_DSN", "REDIS_URL"),
    )

    # --- Downloads ---
    download_dir: Path = Field(Path("downloads"), alias="DOWNLOAD_DIR")
    max_file_size_mb: int = Field(50, alias="MAX_FILE_SIZE_MB")
    max_duration_seconds: int = Field(1800, alias="MAX_DURATION_SECONDS")

    # --- Rate limiting & processing ---
    throttle_rate: float = Field(2.0, alias="THROTTLE_RATE")
    max_concurrent_jobs: int = Field(2, alias="MAX_CONCURRENT_JOBS")
    # x264 speed preset (ultrafast..medium). "ultrafast" = fastest encode.
    ffmpeg_preset: str = Field("ultrafast", alias="FFMPEG_PRESET")
    # Cap the longest side of processed video (px) to speed up encode/upload.
    # 0 disables the cap. 1280 ≈ 720p-class, a good speed/quality balance.
    max_dimension: int = Field(1280, alias="MAX_DIMENSION")
    # Delete temp files older than this many minutes (background cleanup).
    temp_file_ttl_minutes: int = Field(20, alias="TEMP_FILE_TTL_MINUTES")
    watermark_font: str = Field(
        str(_BUNDLED_FONT),
        alias="WATERMARK_FONT",
    )

    # --- Logging ---
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("bot_token", mode="before")
    @classmethod
    def _clean_token(cls, value: object) -> object:
        """Strip whitespace/newlines and surrounding quotes from the token.

        Copy-paste from a hosting panel often adds a trailing newline or wraps
        the value in quotes, which aiogram rejects as an invalid token.
        """
        if isinstance(value, str):
            return value.strip().strip('"').strip("'").strip()
        return value

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

    @model_validator(mode="after")
    def _auto_enable_redis(self) -> "Settings":
        """If a real Redis URL is supplied but STORAGE_TYPE was left at the
        default, switch to Redis automatically."""
        if self.storage_type.lower() == "memory" and self.redis_dsn != _DEFAULT_REDIS:
            self.storage_type = "redis"
        return self

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
