"""Configuration for the London daily debrief."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE pairs from a local .env file if present."""

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from defaults and environment variables."""

    enable_discord: bool = False
    discord_webhook_url: str | None = None
    discord_bot_token: str | None = None
    discord_channel_id: str | None = None
    pixel_banner_url: str | None = None
    weather_thumbnail_url: str | None = None
    environment_thumbnail_url: str | None = None
    travel_thumbnail_url: str | None = None
    news_thumbnail_url: str | None = None


def load_config() -> Config:
    """Load configuration from daily-debrief/.env and the process environment."""

    _load_dotenv(PROJECT_ROOT / ".env")

    return Config(
        enable_discord=_env_bool("ENABLE_DISCORD", False),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN") or None,
        discord_channel_id=os.getenv("DISCORD_CHANNEL_ID") or None,
        pixel_banner_url=os.getenv("PIXEL_BANNER_URL") or None,
        weather_thumbnail_url=os.getenv("WEATHER_THUMBNAIL_URL") or None,
        environment_thumbnail_url=os.getenv("ENVIRONMENT_THUMBNAIL_URL") or None,
        travel_thumbnail_url=os.getenv("TRAVEL_THUMBNAIL_URL") or None,
        news_thumbnail_url=os.getenv("NEWS_THUMBNAIL_URL") or None,
    )
