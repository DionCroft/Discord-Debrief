"""Configuration for the London daily debrief."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_HISTORY_PATH = PROJECT_ROOT / "data" / "brief_history.json"
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "london_daily_debrief.log"
DEFAULT_HEALTH_PATH = PROJECT_ROOT / "data" / "last_run_status.json"
DEFAULT_PIXEL_ASSET_DIR = PROJECT_ROOT / "assets" / "pixel-gifs"


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


def _env_list(name: str, defaults: Sequence[str] = ()) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(defaults)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _asset(name: str) -> str:
    return str(DEFAULT_PIXEL_ASSET_DIR / name)


@dataclass(frozen=True)
class Config:
    """Runtime configuration loaded from defaults and environment variables."""

    enable_discord: bool = False
    history_path: Path = DEFAULT_HISTORY_PATH
    log_path: Path = DEFAULT_LOG_PATH
    health_path: Path = DEFAULT_HEALTH_PATH
    alert_feed_urls: list[str] | None = None
    discord_webhook_url: str | None = None
    discord_bot_token: str | None = None
    discord_channel_id: str | None = None
    pixel_banner_url: str | None = None
    weather_thumbnail_url: str | None = None
    weather_clear_thumbnail_url: str | None = None
    weather_cloud_thumbnail_url: str | None = None
    weather_rain_thumbnail_url: str | None = None
    weather_storm_thumbnail_url: str | None = None
    weather_fog_thumbnail_url: str | None = None
    environment_thumbnail_url: str | None = None
    air_good_thumbnail_url: str | None = None
    air_moderate_thumbnail_url: str | None = None
    air_poor_thumbnail_url: str | None = None
    pollen_low_thumbnail_url: str | None = None
    pollen_moderate_thumbnail_url: str | None = None
    pollen_high_thumbnail_url: str | None = None
    travel_thumbnail_url: str | None = None
    travel_good_thumbnail_url: str | None = None
    travel_delay_thumbnail_url: str | None = None
    news_thumbnail_url: str | None = None


def load_config() -> Config:
    """Load configuration from daily-debrief/.env and the process environment."""

    _load_dotenv(PROJECT_ROOT / ".env")

    return Config(
        enable_discord=_env_bool("ENABLE_DISCORD", False),
        history_path=Path(os.getenv("HISTORY_PATH") or str(DEFAULT_HISTORY_PATH)),
        log_path=Path(os.getenv("LOG_PATH") or str(DEFAULT_LOG_PATH)),
        health_path=Path(os.getenv("HEALTH_PATH") or str(DEFAULT_HEALTH_PATH)),
        alert_feed_urls=_env_list("ALERT_FEED_URLS"),
        discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL") or None,
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN") or None,
        discord_channel_id=os.getenv("DISCORD_CHANNEL_ID") or None,
        pixel_banner_url=os.getenv("PIXEL_BANNER_URL") or _asset("banner.gif"),
        weather_thumbnail_url=os.getenv("WEATHER_THUMBNAIL_URL") or _asset("weather-cloud.gif"),
        weather_clear_thumbnail_url=os.getenv("WEATHER_CLEAR_THUMBNAIL_URL") or _asset("weather-clear.gif"),
        weather_cloud_thumbnail_url=os.getenv("WEATHER_CLOUD_THUMBNAIL_URL") or _asset("weather-cloud.gif"),
        weather_rain_thumbnail_url=os.getenv("WEATHER_RAIN_THUMBNAIL_URL") or _asset("weather-rain.gif"),
        weather_storm_thumbnail_url=os.getenv("WEATHER_STORM_THUMBNAIL_URL") or _asset("weather-storm.gif"),
        weather_fog_thumbnail_url=os.getenv("WEATHER_FOG_THUMBNAIL_URL") or _asset("weather-fog.gif"),
        environment_thumbnail_url=os.getenv("ENVIRONMENT_THUMBNAIL_URL") or _asset("air-good.gif"),
        air_good_thumbnail_url=os.getenv("AIR_GOOD_THUMBNAIL_URL") or _asset("air-good.gif"),
        air_moderate_thumbnail_url=os.getenv("AIR_MODERATE_THUMBNAIL_URL") or _asset("air-moderate.gif"),
        air_poor_thumbnail_url=os.getenv("AIR_POOR_THUMBNAIL_URL") or _asset("air-poor.gif"),
        pollen_low_thumbnail_url=os.getenv("POLLEN_LOW_THUMBNAIL_URL") or _asset("pollen-low.gif"),
        pollen_moderate_thumbnail_url=os.getenv("POLLEN_MODERATE_THUMBNAIL_URL") or _asset("pollen-moderate.gif"),
        pollen_high_thumbnail_url=os.getenv("POLLEN_HIGH_THUMBNAIL_URL") or _asset("pollen-high.gif"),
        travel_thumbnail_url=os.getenv("TRAVEL_THUMBNAIL_URL") or _asset("travel-good.gif"),
        travel_good_thumbnail_url=os.getenv("TRAVEL_GOOD_THUMBNAIL_URL") or _asset("travel-good.gif"),
        travel_delay_thumbnail_url=os.getenv("TRAVEL_DELAY_THUMBNAIL_URL") or _asset("travel-delay.gif"),
        news_thumbnail_url=os.getenv("NEWS_THUMBNAIL_URL") or _asset("news.gif"),
    )
