#!/usr/bin/env python3
"""
London Morning Brief

Builds a detailed morning briefing for:
- London weather (current + intelligent transitions)
- TfL status
- BBC news

Modes:
- --compact : shorter WhatsApp-friendly output
- --full    : richer detailed output

Designed for use with OpenClaw / cron / WhatsApp / Discord delivery.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import traceback
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

import feedparser
import requests

from config import DEFAULT_PIXEL_ASSET_DIR, Config, load_config
from discord_notifier import (
    embeds_without_images,
    send_discord_report,
    send_discord_report_detailed,
)


# =========================
# CONFIG
# =========================

LONDON_LAT = 51.5072
LONDON_LON = -0.1276

BBC_NEWS_RSS = "https://feeds.bbci.co.uk/news/rss.xml"
TFL_STATUS_URL = "https://api.tfl.gov.uk/Line/Mode/tube,dlr,overground,elizabeth-line/Status"
TFL_DISRUPTION_URL = "https://api.tfl.gov.uk/Line/Mode/tube,dlr,overground,elizabeth-line/Disruption"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

REQUEST_TIMEOUT = 20
DISCORD_DESCRIPTION_LIMIT = 3900
DISCORD_FIELD_LIMIT = 1000
HISTORY_MAX_RUNS = 30
EXPECTED_SEASONAL_GIF_COUNT = 80

logger = logging.getLogger(__name__)
SEASONAL_ASSET_DIR = DEFAULT_PIXEL_ASSET_DIR / "seasonal"

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


# =========================
# HELPERS
# =========================

def clean_html_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten_text(text: str, max_len: int = 220) -> str:
    text = clean_html_text(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def safe_get_json(url: str) -> Any:
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def safe_parse_feed(url: str) -> feedparser.FeedParserDict:
    return feedparser.parse(url)


def fetch_source(name: str, fetcher: Any, fallback: Any) -> Any:
    try:
        value = fetcher()
        logger.info("%s source fetched successfully.", name)
        return value
    except Exception:
        logger.exception("%s source failed.", name)
        return fallback


def setup_logging(config: Config) -> None:
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        config.log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)



def hhmm_to_hour(value: str) -> int:
    return int(value.split(":")[0])


def time_label(hour_str: str) -> str:
    return hour_str[:5]


def format_range(start: str, end: str) -> str:
    start_h = time_label(start)
    end_h = time_label(end)
    if start_h == end_h:
        return start_h
    end_hour = hhmm_to_hour(end_h)
    end_display = f"{end_hour + 1:02d}:00" if end_hour < 23 else "24:00"
    return f"{start_h}–{end_display}"


def classify_sky(desc: str) -> str:
    desc = desc.lower()
    if "thunderstorm" in desc:
        return "stormy"
    if "snow" in desc:
        return "snowy"
    if "rain" in desc or "drizzle" in desc or "showers" in desc:
        return "wet"
    if "fog" in desc:
        return "foggy"
    if "clear" in desc or "mainly clear" in desc:
        return "clear"
    if "partly cloudy" in desc:
        return "partly cloudy"
    if "overcast" in desc:
        return "cloudy"
    return "mixed"


def sky_phrase(category: str) -> str:
    return {
        "stormy": "stormy conditions",
        "snowy": "snow possible",
        "wet": "wet conditions",
        "foggy": "foggy conditions",
        "clear": "mostly clear skies",
        "partly cloudy": "partly cloudy skies",
        "cloudy": "mostly cloudy skies",
        "mixed": "mixed conditions",
    }.get(category, "mixed conditions")


def dominant_category(rows: List[Dict[str, Any]]) -> str:
    counter = Counter(classify_sky(r["desc"]) for r in rows)
    return counter.most_common(1)[0][0]


def group_consecutive_hours(hours: List[str]) -> List[tuple[str, str]]:
    if not hours:
        return []

    values = sorted(hours, key=hhmm_to_hour)
    groups: List[List[str]] = [[values[0]]]

    for h in values[1:]:
        prev = groups[-1][-1]
        if hhmm_to_hour(h) == hhmm_to_hour(prev) + 1:
            groups[-1].append(h)
        else:
            groups.append([h])

    return [(g[0], g[-1]) for g in groups]


def detect_rain_windows(hourly: List[Dict[str, Any]], threshold: int = 45) -> List[Dict[str, Any]]:
    rainy_hours = [row["hour"] for row in hourly if row["rain_prob"] >= threshold]
    grouped = group_consecutive_hours(rainy_hours)

    windows: List[Dict[str, Any]] = []
    for start, end in grouped:
        rows = [
            r for r in hourly
            if hhmm_to_hour(start) <= hhmm_to_hour(r["hour"]) <= hhmm_to_hour(end)
        ]
        if not rows:
            continue
        windows.append(
            {
                "start": start,
                "end": end,
                "peak_rain": max(r["rain_prob"] for r in rows),
                "desc": dominant_category(rows),
            }
        )
    return windows


def split_day_periods(hourly: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    periods = [
        ("00:00", "06:00"),
        ("06:00", "12:00"),
        ("12:00", "18:00"),
        ("18:00", "24:00"),
    ]

    chunks: List[Dict[str, Any]] = []
    for start, end in periods:
        start_h = hhmm_to_hour(start)
        end_h = 24 if end == "24:00" else hhmm_to_hour(end)

        rows = [r for r in hourly if start_h <= hhmm_to_hour(r["hour"]) < end_h]
        if not rows:
            continue

        chunks.append(
            {
                "start": start,
                "end": end,
                "category": dominant_category(rows),
                "peak_rain": max(r["rain_prob"] for r in rows),
                "avg_wind": round(sum(r["wind"] for r in rows) / len(rows), 1),
            }
        )
    return chunks


def merge_similar_periods(periods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not periods:
        return []

    merged = [periods[0].copy()]
    for p in periods[1:]:
        last = merged[-1]
        same_weather = p["category"] == last["category"]
        similar_rain = abs(p["peak_rain"] - last["peak_rain"]) <= 15

        if same_weather and similar_rain:
            last["end"] = p["end"]
            last["peak_rain"] = max(last["peak_rain"], p["peak_rain"])
            last["avg_wind"] = round((last["avg_wind"] + p["avg_wind"]) / 2, 1)
        else:
            merged.append(p.copy())

    return merged


def describe_period(period: Dict[str, Any], compact: bool = False) -> str:
    label = f"{period['start']}–{period['end']}"
    sky = sky_phrase(period["category"])
    rain = period["peak_rain"]
    wind = period["avg_wind"]

    if rain >= 70:
        rain_text = f"rain likely ({rain}%)"
    elif rain >= 40:
        rain_text = f"moderate rain chance ({rain}%)"
    elif rain >= 20:
        rain_text = f"small shower risk ({rain}%)"
    else:
        rain_text = "mostly dry"

    if compact:
        return f"• {label} — {rain_text}, {sky}, wind ~{wind} km/h."
    return f"• {label} — {rain_text}, with {sky} and winds around {wind} km/h."


# =========================
# DATA SOURCES
# =========================

def get_weather() -> Dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LONDON_LAT}&longitude={LONDON_LON}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
        "precipitation,rain,showers,snowfall,weather_code,wind_speed_10m"
        "&hourly=temperature_2m,precipitation_probability,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
        "weather_code,wind_speed_10m_max"
        "&timezone=Europe%2FLondon"
        "&forecast_days=1"
    )

    data = safe_get_json(url)

    current = data["current"]
    hourly = data["hourly"]
    daily = data["daily"]

    hourly_rows: List[Dict[str, Any]] = []
    for i in range(len(hourly["time"])):
        code = hourly["weather_code"][i]
        hourly_rows.append(
            {
                "hour": hourly["time"][i].split("T")[1],
                "temp": hourly["temperature_2m"][i],
                "rain_prob": hourly["precipitation_probability"][i],
                "desc": WEATHER_CODES.get(code, "Unknown"),
                "wind": hourly["wind_speed_10m"][i],
            }
        )

    return {
        "current_desc": WEATHER_CODES.get(current["weather_code"], "Unknown"),
        "current_temp": current["temperature_2m"],
        "feels_like": current["apparent_temperature"],
        "humidity": current["relative_humidity_2m"],
        "wind": current["wind_speed_10m"],
        "max": daily["temperature_2m_max"][0],
        "min": daily["temperature_2m_min"][0],
        "rain_chance_max": daily["precipitation_probability_max"][0],
        "daily_desc": WEATHER_CODES.get(daily["weather_code"][0], "Unknown"),
        "max_wind": daily["wind_speed_10m_max"][0],
        "hourly": hourly_rows,
    }


def get_tfl() -> Dict[str, Any]:
    lines = safe_get_json(TFL_STATUS_URL)

    good_lines: List[str] = []
    issues: List[Dict[str, str]] = []

    for line in lines:
        name = line.get("name", "Unknown line")
        statuses = line.get("lineStatuses", [])
        if not statuses:
            continue

        status = statuses[0].get("statusSeverityDescription", "Unknown")
        reason = clean_html_text(statuses[0].get("reason", ""))

        if status == "Good Service":
            good_lines.append(name)
        else:
            issues.append(
                {
                    "line": name,
                    "status": status,
                    "reason": shorten_text(reason, 260) if reason else "",
                }
            )

    return {"good_lines": good_lines, "issues": issues}


def get_tfl_disruption_alerts(limit: int = 8) -> List[Dict[str, str]]:
    disruptions = safe_get_json(TFL_DISRUPTION_URL)
    alerts: List[Dict[str, str]] = []

    for item in disruptions[:limit]:
        line_name = item.get("line", {}).get("name") or item.get("lineName") or "TfL"
        category = item.get("categoryDescription") or item.get("type") or "Disruption"
        description = clean_html_text(item.get("description", ""))
        additional = clean_html_text(item.get("additionalInfo", ""))
        summary = shorten_text(" ".join(part for part in [description, additional] if part), 320)
        alerts.append(
            {
                "title": f"{line_name} - {category}",
                "summary": summary or "TfL reports disruption on this service.",
                "source": "TfL disruptions",
            }
        )

    return alerts


def get_air_quality() -> Dict[str, Any]:
    url = (
        f"{AIR_QUALITY_URL}?latitude={LONDON_LAT}&longitude={LONDON_LON}"
        "&current=european_aqi,pm2_5,pm10,grass_pollen,birch_pollen,"
        "alder_pollen,mugwort_pollen,olive_pollen,ragweed_pollen"
        "&timezone=Europe%2FLondon"
        "&forecast_days=1"
    )
    data = safe_get_json(url)
    current = data["current"]

    pollen_values = {
        "Grass": current.get("grass_pollen"),
        "Birch": current.get("birch_pollen"),
        "Alder": current.get("alder_pollen"),
        "Mugwort": current.get("mugwort_pollen"),
        "Olive": current.get("olive_pollen"),
        "Ragweed": current.get("ragweed_pollen"),
    }
    available_pollen = {
        name: value for name, value in pollen_values.items()
        if isinstance(value, (int, float))
    }
    top_pollen = max(available_pollen.items(), key=lambda item: item[1]) if available_pollen else None

    return {
        "european_aqi": current.get("european_aqi"),
        "pm2_5": current.get("pm2_5"),
        "pm10": current.get("pm10"),
        "pollen": available_pollen,
        "top_pollen": top_pollen,
    }


def get_news(limit: int = 5) -> List[Dict[str, str]]:
    feed = safe_parse_feed(BBC_NEWS_RSS)
    items: List[Dict[str, str]] = []

    for entry in feed.entries[:limit]:
        items.append(
            {
                "title": clean_html_text(entry.get("title", "Untitled")),
                "summary": shorten_text(entry.get("summary", ""), 220),
                "link": entry.get("link", ""),
            }
        )

    return items


def get_alert_feed_items(feed_urls: List[str], limit: int = 5) -> List[Dict[str, str]]:
    alerts: List[Dict[str, str]] = []
    for feed_url in feed_urls:
        try:
            feed = safe_parse_feed(feed_url)
            for entry in feed.entries[:limit]:
                alerts.append(
                    {
                        "title": clean_html_text(entry.get("title", "Untitled alert")),
                        "summary": shorten_text(entry.get("summary", ""), 260),
                        "link": entry.get("link", ""),
                        "source": clean_html_text(feed.feed.get("title", "Alert feed")),
                    }
                )
        except Exception:
            logger.exception("Alert feed failed: %s", feed_url)
    return alerts[:limit]


def build_alerts(
    weather: Optional[Dict[str, Any]],
    tfl: Optional[Dict[str, Any]],
    tfl_disruption_alerts: List[Dict[str, str]],
    feed_alerts: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    alerts: List[Dict[str, str]] = []

    if weather:
        if weather["rain_chance_max"] >= 70:
            alerts.append(
                {
                    "title": "High rain risk",
                    "summary": f"Rain risk peaks at {weather['rain_chance_max']}% today.",
                    "source": "Weather",
                    "severity": "warning",
                }
            )
        if weather["max_wind"] >= 30:
            alerts.append(
                {
                    "title": "Breezy conditions",
                    "summary": f"Winds may peak around {weather['max_wind']} km/h.",
                    "source": "Weather",
                    "severity": "notice",
                }
            )

    if tfl:
        for issue in tfl["issues"]:
            status = issue["status"].lower()
            if any(word in status for word in ("closure", "suspended", "severe", "planned")):
                alerts.append(
                    {
                        "title": f"{issue['line']} - {issue['status']}",
                        "summary": issue["reason"] or "TfL reports disruption on this line.",
                        "source": "TfL",
                        "severity": "warning" if "severe" in status or "suspended" in status else "notice",
                    }
                )

    alerts.extend({**item, "severity": "notice"} for item in tfl_disruption_alerts)
    alerts.extend({**item, "severity": "notice"} for item in feed_alerts)
    return dedupe_alerts(alerts)[:8]


def dedupe_alerts(alerts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen: set[str] = set()
    deduped: List[Dict[str, str]] = []
    for alert in alerts:
        key = f"{alert.get('source', '')}|{alert.get('title', '')}|{alert.get('summary', '')[:80]}".lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(alert)
    return deduped


# =========================
# SUMMARY BUILDERS
# =========================

def build_weather_overview(weather: Dict[str, Any]) -> str:
    desc = weather["daily_desc"].lower()
    rain = weather["rain_chance_max"]
    max_wind = weather["max_wind"]

    if rain >= 70 and max_wind >= 28:
        return "A cool, unsettled, and breezy day, with the wettest conditions arriving later."
    if rain >= 70:
        return "A damp and unsettled day, with rain likely at points."
    if rain >= 40:
        return "A mixed day, with brighter spells but showers possible."
    if "clear" in desc or "cloud" in desc or "overcast" in desc:
        return f"A fairly settled day overall, with {desc} conditions."
    return "A mixed London day with variable conditions."


def build_weather_changes(hourly: List[Dict[str, Any]], compact: bool = False) -> List[str]:
    rain_windows = detect_rain_windows(hourly, threshold=45)
    periods = merge_similar_periods(split_day_periods(hourly))

    lines: List[str] = []

    if rain_windows:
        for window in rain_windows[:2]:
            time_range = format_range(window["start"], window["end"])
            if window["peak_rain"] >= 70:
                lines.append(f"• Rain is most likely from {time_range}, peaking around {window['peak_rain']}%.")
            else:
                lines.append(f"• Showers are possible from {time_range}, with rain risk up to {window['peak_rain']}%.")
    else:
        lines.append("• No significant rain window stands out today.")

    if compact:
        return lines

    lines.append("• Key shifts through the day:")
    for p in periods[:4]:
        lines.append(describe_period(p, compact=False))

    return lines


def build_commuter_insight(weather: Dict[str, Any], tfl: Dict[str, Any]) -> str:
    notes: List[str] = []

    if weather["rain_chance_max"] >= 70:
        notes.append("A wet commute is likely, so allow extra travel time and carry an umbrella.")
    elif weather["rain_chance_max"] >= 40:
        notes.append("Rain is possible later, so it may be worth keeping an umbrella handy.")

    if weather["max_wind"] >= 30:
        notes.append("Breezy conditions may make walking and cycling less comfortable than usual.")

    if tfl["issues"]:
        first = tfl["issues"][0]
        notes.append(
            f"The most significant TfL issue currently appears to be on the {first['line']} with {first['status'].lower()}."
        )

    if not notes:
        notes.append("Conditions look fairly stable for a normal London commute today.")

    return " ".join(notes)


def aqi_level(value: Optional[float]) -> str:
    if value is None:
        return "Unavailable"
    if value <= 20:
        return "Good"
    if value <= 40:
        return "Fair"
    if value <= 60:
        return "Moderate"
    if value <= 80:
        return "Poor"
    if value <= 100:
        return "Very poor"
    return "Extremely poor"


def pollen_level(value: Optional[float]) -> str:
    if value is None:
        return "Unavailable"
    if value < 10:
        return "Low"
    if value < 50:
        return "Moderate"
    return "High"


def load_history(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"runs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not read history file: %s", path)
        return {"runs": []}


def save_history(path: Path, history: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        history["runs"] = history.get("runs", [])[-HISTORY_MAX_RUNS:]
        path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Could not write history file: %s", path)


def build_history_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    weather = data.get("weather")
    tfl = data.get("tfl")
    air_quality = data.get("air_quality")
    pollen = air_quality.get("top_pollen") if air_quality else None

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rain_chance": weather.get("rain_chance_max") if weather else None,
        "max_wind": weather.get("max_wind") if weather else None,
        "current_temp": weather.get("current_temp") if weather else None,
        "tfl_issue_count": len(tfl["issues"]) if tfl else None,
        "aqi": air_quality.get("european_aqi") if air_quality else None,
        "pollen_name": pollen[0] if pollen else None,
        "pollen_value": pollen[1] if pollen else None,
    }


def previous_snapshot(history: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    runs = history.get("runs", [])
    if not runs:
        return None
    return runs[-1]


def update_history(path: Path, data: Dict[str, Any]) -> None:
    history = data.get("history") or load_history(path)
    history.setdefault("runs", []).append(build_history_snapshot(data))
    save_history(path, history)


def compare_metric(
    label: str,
    current: Optional[float],
    previous: Optional[float],
    unit: str = "",
    lower_is_better: bool = True,
    threshold: float = 1,
) -> Optional[str]:
    if current is None or previous is None:
        return None

    delta = current - previous
    if abs(delta) < threshold:
        return f"{label} is about the same as last run ({current:g}{unit})."

    direction = "higher" if delta > 0 else "lower"
    better = (delta < 0 and lower_is_better) or (delta > 0 and not lower_is_better)
    judgement = "better" if better else "worse"
    return f"{label} is {judgement}: {current:g}{unit}, {direction} than {previous:g}{unit}."


def build_trend_summary(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> List[str]:
    if not previous:
        return ["No previous run stored yet, so trends will appear after the next briefing."]

    lines = [
        compare_metric("Rain risk", current.get("rain_chance"), previous.get("rain_chance"), "%"),
        compare_metric("Wind", current.get("max_wind"), previous.get("max_wind"), " km/h"),
        compare_metric("TfL disruption", current.get("tfl_issue_count"), previous.get("tfl_issue_count"), " issue(s)"),
        compare_metric("Air quality", current.get("aqi"), previous.get("aqi")),
        compare_metric("Pollen", current.get("pollen_value"), previous.get("pollen_value"), " grains/m³"),
    ]
    return [line for line in lines if line][:4] or ["No comparable trend data available yet."]


def build_action_items(
    weather: Optional[Dict[str, Any]],
    tfl: Optional[Dict[str, Any]],
    air_quality: Optional[Dict[str, Any]],
) -> List[str]:
    actions: List[str] = []

    if weather:
        if weather["rain_chance_max"] >= 70:
            actions.append("Carry an umbrella and allow a little extra journey time.")
        elif weather["rain_chance_max"] >= 40:
            actions.append("Keep a rain layer handy for the higher-risk windows.")

        if weather["max_wind"] >= 30:
            actions.append("Expect breezy walking or cycling conditions.")

    if tfl and tfl["issues"]:
        first = tfl["issues"][0]
        actions.append(f"Check the {first['line']} before travelling; it currently has {first['status'].lower()}.")

    if air_quality:
        if aqi_level(air_quality.get("european_aqi")) in {"Poor", "Very poor", "Extremely poor"}:
            actions.append("Air quality is poor, so consider easier outdoor activity if sensitive.")
        if air_quality.get("top_pollen") and pollen_level(air_quality["top_pollen"][1]) == "High":
            actions.append(f"{air_quality['top_pollen'][0]} pollen is high today.")

    if not actions:
        actions.append("No obvious commute action needed from the current data.")

    return actions[:3]


# =========================
# OUTPUT BUILDERS
# =========================

def add_section(lines: List[str], title: str) -> None:
    lines.append("━━━━━━━━━━")
    lines.append(title)
    lines.append("━━━━━━━━━━")


def collect_brief_data(config: Config, compact: bool = False) -> Dict[str, Any]:
    now = datetime.now().strftime("%A, %d %B %Y")
    current_time = datetime.now().strftime("%H:%M")
    history = load_history(config.history_path)
    previous = previous_snapshot(history)

    weather = fetch_source("Weather", get_weather, None)
    tfl = fetch_source("TfL", get_tfl, None)
    tfl_disruption_alerts = fetch_source("TfL disruptions", get_tfl_disruption_alerts, [])
    air_quality = fetch_source("Air quality", get_air_quality, None)
    news = fetch_source("BBC news", lambda: get_news(limit=3 if compact else 5), [])
    feed_alerts = fetch_source(
        "Alert feeds",
        lambda: get_alert_feed_items(config.alert_feed_urls or []),
        [],
    )
    alerts = build_alerts(weather, tfl, tfl_disruption_alerts, feed_alerts)

    trend_snapshot = {
        "rain_chance": weather.get("rain_chance_max") if weather else None,
        "max_wind": weather.get("max_wind") if weather else None,
        "tfl_issue_count": len(tfl["issues"]) if tfl else None,
        "aqi": air_quality.get("european_aqi") if air_quality else None,
        "pollen_value": air_quality["top_pollen"][1] if air_quality and air_quality.get("top_pollen") else None,
    }

    return {
        "now": now,
        "current_time": current_time,
        "weather": weather,
        "tfl": tfl,
        "air_quality": air_quality,
        "news": news,
        "alerts": alerts,
        "history": history,
        "previous_snapshot": previous,
        "trend_snapshot": trend_snapshot,
        "trend_summary": build_trend_summary(trend_snapshot, previous),
        "compact": compact,
    }


def build_brief_from_data(data: Dict[str, Any]) -> str:
    now = data["now"]
    current_time = data["current_time"]
    weather = data["weather"]
    tfl = data["tfl"]
    air_quality = data["air_quality"]
    news = data["news"]
    alerts = data["alerts"]
    trend_summary = data["trend_summary"]
    compact = data["compact"]

    lines: List[str] = []
    lines.append(f"🌅 *London Morning Brief* — {now}")
    lines.append("")

    # Weather
    add_section(lines, "🌤 *Weather*")
    if weather is None:
        lines.append("• Unavailable at the moment.")
    else:
        lines.append(
            f"• Right now ({current_time}): {weather['current_desc']}, "
            f"{weather['current_temp']}°C (feels like {weather['feels_like']}°C)."
        )
        lines.append(f"• Today overall: {build_weather_overview(weather)}")
        lines.append(f"• Temperature range: {weather['min']}°C → {weather['max']}°C.")
        lines.append(f"• Humidity: {weather['humidity']}%. Wind may peak at {weather['max_wind']} km/h.")
        lines.append("")
        lines.append("*How conditions change:*")
        lines.extend(build_weather_changes(weather["hourly"], compact=compact))

    lines.append("")

    # TfL
    add_section(lines, "🚇 *TfL Status*")
    if tfl is None:
        lines.append("• Unavailable at the moment.")
    elif not tfl["issues"]:
        lines.append("• Most major TfL services are running normally.")
    else:
        for issue in tfl["issues"]:
            lines.append(f"• *{issue['line']}* — {issue['status']}")
            if not compact and issue["reason"]:
                lines.append(f"  {issue['reason']}")
            lines.append("")
        if lines[-1] == "":
            lines.pop()

    lines.append("")

    # Environment
    add_section(lines, "🌿 *Air Quality & Pollen*")
    if air_quality is None:
        lines.append("• Unavailable at the moment.")
    else:
        aqi = air_quality.get("european_aqi")
        lines.append(f"• Air quality: {aqi_level(aqi)}" + (f" (European AQI {aqi})." if aqi is not None else "."))
        lines.append(
            f"• PM2.5: {air_quality.get('pm2_5', 'n/a')} µg/m³. "
            f"PM10: {air_quality.get('pm10', 'n/a')} µg/m³."
        )
        if air_quality.get("top_pollen"):
            name, value = air_quality["top_pollen"]
            lines.append(f"• Pollen: {pollen_level(value)}. Highest current reading is {name} ({value} grains/m³).")
        else:
            lines.append("• Pollen: unavailable or out of season.")

    lines.append("")

    # Alerts
    add_section(lines, "⚠️ *Alerts*")
    if not alerts:
        lines.append("• No major local alerts detected from the configured sources.")
    else:
        for alert in alerts:
            lines.append(f"• *{alert['title']}* ({alert.get('source', 'Alert')})")
            if alert.get("summary") and not compact:
                lines.append(f"  {alert['summary']}")
            if alert.get("link") and not compact:
                lines.append(f"  Link: {alert['link']}")

    lines.append("")

    # Trends
    add_section(lines, "📊 *Since Last Run*")
    for line in trend_summary:
        lines.append(f"• {line}")

    lines.append("")

    # News
    add_section(lines, "📰 *Top News*")
    if not news:
        lines.append("• Unavailable at the moment.")
    else:
        for idx, item in enumerate(news, start=1):
            lines.append(f"{idx}. *{item['title']}*")
            if item["summary"]:
                lines.append(f"   {item['summary']}")
            if item["link"]:
                lines.append(f"   Link: {item['link']}")
            lines.append("")
        if lines[-1] == "":
            lines.pop()

    lines.append("")

    # Insight
    add_section(lines, "💡 *Commuter Insight*")
    if weather is None or tfl is None:
        lines.append("• Unavailable at the moment.")
    else:
        lines.append(f"• {build_commuter_insight(weather, tfl)}")

    return "\n".join(lines)


def build_brief(compact: bool = False) -> str:
    config = load_config()
    setup_logging(config)
    return build_brief_from_data(collect_brief_data(config, compact=compact))


def build_discord_embeds(data: Dict[str, Any], config: Optional[Config] = None) -> List[Dict[str, Any]]:
    weather = data["weather"]
    tfl = data["tfl"]
    air_quality = data["air_quality"]
    news = data["news"]
    alerts = data["alerts"]
    trend_summary = data["trend_summary"]
    compact = data["compact"]
    now = data["now"]
    current_time = data["current_time"]

    color = discord_status_color(weather, tfl)
    embeds: List[Dict[str, Any]] = [
        with_optional_image(
            {
            "title": "▣ LONDON DAILY BRIEF ▣",
            "description": pixel_panel(build_discord_overview(data)),
            "color": color,
            "footer": {"text": now},
            },
            image_url=seasonal_pixel_url("banner", config.pixel_banner_url) if config else None,
        )
    ]

    embeds.append(
        with_optional_image(
            {
            "title": "▣ WEATHER",
            "description": pixel_panel(weather_status_line(weather, current_time)),
            "fields": build_discord_weather_fields(weather, compact),
            "color": color,
            },
            thumbnail_url=weather_thumbnail_url(weather, config),
        )
    )

    embeds.extend(
        build_discord_travel_embeds(
            tfl,
            compact,
            thumbnail_url=travel_thumbnail_url(tfl, config),
        )
    )

    embeds.append(
        with_optional_image(
            {
            "title": "▣ AIR QUALITY + POLLEN",
            "description": build_discord_environment(air_quality),
            "color": environment_status_color(air_quality),
            },
            thumbnail_url=environment_thumbnail_url(air_quality, config),
        )
    )

    embeds.append(
        {
            "title": "▣ ALERTS",
            "description": build_discord_alerts(alerts),
            "color": 0xE74C3C if alerts else 0x2ECC71,
        }
    )

    embeds.append(
        with_optional_image(
            {
            "title": "▣ SINCE LAST RUN",
            "description": "\n".join(f"• {line}" for line in trend_summary),
            "color": 0x95A5A6,
            },
            thumbnail_url=seasonal_pixel_url("banner", config.pixel_banner_url) if config else None,
        )
    )

    embeds.append(
        with_optional_image(
            {
            "title": "▣ NEWS",
            "description": build_discord_news(news, limit=5),
            "color": 0x3498DB,
            },
            thumbnail_url=seasonal_pixel_url("news", config.news_thumbnail_url) if config else None,
        )
    )

    return embeds


def discord_status_color(weather: Optional[Dict[str, Any]], tfl: Optional[Dict[str, Any]]) -> int:
    if tfl and len(tfl["issues"]) >= 3:
        return 0xE74C3C
    if weather and (weather["rain_chance_max"] >= 70 or weather["max_wind"] >= 30):
        return 0xF0B232
    if tfl and tfl["issues"]:
        return 0xF0B232
    return 0x2ECC71


def environment_status_color(air_quality: Optional[Dict[str, Any]]) -> int:
    if not air_quality:
        return 0x95A5A6

    air_level = aqi_level(air_quality.get("european_aqi"))
    pollen = air_quality.get("top_pollen")
    pollen_status = pollen_level(pollen[1]) if pollen else "Unavailable"

    if air_level in {"Poor", "Very poor", "Extremely poor"} or pollen_status == "High":
        return 0xF0B232
    if air_level == "Moderate" or pollen_status == "Moderate":
        return 0xF1C40F
    return 0x2ECC71


def build_discord_overview(data: Dict[str, Any]) -> List[str]:
    weather = data["weather"]
    tfl = data["tfl"]
    air_quality = data["air_quality"]
    news = data["news"]

    lines: List[str] = []
    if weather:
        lines.append(f"Weather: {build_weather_overview(weather)}")
    else:
        lines.append("Weather: unavailable at the moment.")

    if tfl is None:
        lines.append("TfL: unavailable at the moment.")
    elif tfl["issues"]:
        lines.append(f"TfL: {len(tfl['issues'])} notable issue(s) currently reported.")
    else:
        lines.append("TfL: major services look normal.")

    if air_quality:
        pollen = air_quality.get("top_pollen")
        pollen_summary = (
            f"{pollen_level(pollen[1])} {pollen[0]} pollen"
            if pollen else "pollen unavailable"
        )
        lines.append(f"Air: {aqi_level(air_quality.get('european_aqi'))}; {pollen_summary}.")
    else:
        lines.append("Air: unavailable at the moment.")

    lines.append(f"News scan: {len(news)} top item(s).")
    lines.append("")
    lines.append("Actions:")
    lines.extend(f"• {item}" for item in build_action_items(weather, tfl, air_quality))
    return lines


def weather_status_line(
    weather: Optional[Dict[str, Any]],
    current_time: str,
) -> str:
    if weather is None:
        return "Unavailable at the moment."

    return (
        f"NOW {current_time}: **{weather['current_desc']}**, "
        f"{weather['current_temp']}°C, feels like {weather['feels_like']}°C."
    )


def build_discord_weather_fields(
    weather: Optional[Dict[str, Any]],
    compact: bool,
) -> List[Dict[str, Any]]:
    if weather is None:
        return []

    lines = [
        f"**Temp:** {weather['min']}°C to {weather['max']}°C",
        f"**Wind:** peak {weather['max_wind']} km/h",
        f"**Rain:** {weather['rain_chance_max']}%",
    ]
    changes = "\n".join(strip_bullets(line) for line in build_weather_changes(weather["hourly"], compact=compact))
    return [
        {"name": "[ STATUS ]", "value": "\n".join(lines), "inline": True},
        {"name": "[ DAY MAP ]", "value": truncate(changes, DISCORD_FIELD_LIMIT), "inline": False},
    ]


def build_discord_travel_embeds(
    tfl: Optional[Dict[str, Any]],
    compact: bool,
    thumbnail_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    color = 0x5865F2 if not tfl or not tfl["issues"] else 0xF0B232

    if tfl is None:
        return [
            with_optional_image(
                {
                    "title": "▣ TRAVEL",
                    "description": pixel_panel("Unavailable at the moment."),
                    "color": color,
                },
                thumbnail_url=thumbnail_url,
            )
        ]
    if not tfl["issues"]:
        return [
            with_optional_image(
                {
                    "title": "▣ TRAVEL",
                    "description": pixel_panel("STATUS: Most major TfL services are running normally."),
                    "color": color,
                },
                thumbnail_url=thumbnail_url,
            )
        ]

    chunks: List[List[str]] = [[]]
    current_length = 0

    for issue in tfl["issues"]:
        line = f"**{issue['line']}** - {issue['status']}"
        if not compact and issue["reason"]:
            line = f"{line}\n{issue['reason']}"

        entry_length = len(line) + 2
        if chunks[-1] and current_length + entry_length > DISCORD_DESCRIPTION_LIMIT:
            chunks.append([])
            current_length = 0

        chunks[-1].append(line)
        current_length += entry_length

    embeds: List[Dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        title = "▣ TRAVEL" if idx == 1 else f"▣ TRAVEL CONT. {idx}"
        embeds.append(
            with_optional_image(
                {
                    "title": title,
                    "description": pixel_panel("\n\n".join(chunk)),
                    "color": color,
                },
                thumbnail_url=thumbnail_url if idx == 1 else None,
            )
        )
    return embeds


def build_discord_environment(air_quality: Optional[Dict[str, Any]]) -> str:
    if air_quality is None:
        return "Unavailable at the moment."

    aqi = air_quality.get("european_aqi")
    pm2_5 = air_quality.get("pm2_5")
    pm10 = air_quality.get("pm10")
    pollen = air_quality.get("top_pollen")

    lines = [
        f"**Air quality:** {aqi_level(aqi)}" + (f" · European AQI {aqi}" if aqi is not None else ""),
        f"**PM2.5:** {pm2_5 if pm2_5 is not None else 'n/a'} µg/m³",
        f"**PM10:** {pm10 if pm10 is not None else 'n/a'} µg/m³",
    ]

    if pollen:
        pollen_name, pollen_value = pollen
        lines.append(
            f"**Pollen:** {pollen_level(pollen_value)} · highest is {pollen_name} "
            f"({pollen_value} grains/m³)"
        )
    else:
        lines.append("**Pollen:** unavailable or out of season")

    return "\n".join(lines)


def build_discord_alerts(alerts: List[Dict[str, str]]) -> str:
    if not alerts:
        return "No major local alerts detected from the configured sources."

    lines: List[str] = []
    for alert in alerts[:8]:
        title = alert["title"]
        source = alert.get("source", "Alert")
        summary = alert.get("summary", "")
        if alert.get("link"):
            heading = f"**[{escape_link_text(title)}]({alert['link']})** · {source}"
        else:
            heading = f"**{title}** · {source}"
        lines.append(f"{heading}\n{summary}".strip())
    return truncate("\n\n".join(lines), 4000)


def build_discord_news(items: List[Dict[str, str]], limit: int) -> str:
    if not items:
        return "Unavailable at the moment."

    lines: List[str] = []
    for idx, item in enumerate(items[:limit], start=1):
        if item.get("link"):
            title = f"**[{idx}. {escape_link_text(item['title'])}]({item['link']})**"
        else:
            title = f"**{idx}. {item['title']}**"
        lines.append(f"{title}\n{item.get('summary', '')}")
    return truncate("\n\n".join(lines), 4000)


def pixel_panel(value: str | List[str]) -> str:
    return "\n".join(value) if isinstance(value, list) else value


def with_optional_image(
    embed: Dict[str, Any],
    image_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
) -> Dict[str, Any]:
    if image_url:
        embed["image"] = {"url": image_url}
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}
    return embed


def season_for_month(month: int) -> str:
    if month in {3, 4, 5}:
        return "spring"
    if month in {6, 7, 8}:
        return "summer"
    if month in {9, 10, 11}:
        return "autumn"
    return "winter"


def day_part_for_hour(hour: int) -> str:
    return "day" if 6 <= hour < 18 else "night"


def seasonal_variant(category: str, value: datetime) -> int:
    seed = value.toordinal() + sum(ord(char) for char in category)
    return 1 + (seed % 2)


def is_default_pixel_asset(value: Optional[str]) -> bool:
    if not value:
        return False
    if value.startswith(("http://", "https://", "attachment://")):
        return False
    try:
        Path(value).resolve().relative_to(DEFAULT_PIXEL_ASSET_DIR)
    except ValueError:
        return False
    return True


def seasonal_pixel_url(
    category: str,
    fallback_url: Optional[str],
    value: Optional[datetime] = None,
) -> Optional[str]:
    if fallback_url and not is_default_pixel_asset(fallback_url):
        return fallback_url

    value = value or datetime.now()
    season = season_for_month(value.month)
    day_part = day_part_for_hour(value.hour)
    variant = seasonal_variant(category, value)
    path = SEASONAL_ASSET_DIR / f"{category}-{season}-{day_part}-{variant}.gif"
    if path.exists():
        return str(path)
    return fallback_url


def weather_thumbnail_url(weather: Optional[Dict[str, Any]], config: Optional[Config]) -> Optional[str]:
    if not config:
        return None
    seasonal = seasonal_pixel_url("weather", config.weather_thumbnail_url)
    if seasonal:
        return seasonal
    if not weather:
        return config.weather_thumbnail_url

    category = classify_sky(weather.get("current_desc", ""))
    if category == "stormy":
        return config.weather_storm_thumbnail_url or config.weather_rain_thumbnail_url or config.weather_thumbnail_url
    if category == "wet" or weather.get("rain_chance_max", 0) >= 45:
        return config.weather_rain_thumbnail_url or config.weather_thumbnail_url
    if category == "foggy":
        return config.weather_fog_thumbnail_url or config.weather_thumbnail_url
    if category in {"cloudy", "partly cloudy"}:
        return config.weather_cloud_thumbnail_url or config.weather_thumbnail_url
    return config.weather_clear_thumbnail_url or config.weather_thumbnail_url


def travel_thumbnail_url(tfl: Optional[Dict[str, Any]], config: Optional[Config]) -> Optional[str]:
    if not config:
        return None
    fallback = config.travel_delay_thumbnail_url if tfl and tfl.get("issues") else config.travel_good_thumbnail_url
    seasonal = seasonal_pixel_url("travel", fallback or config.travel_thumbnail_url)
    if seasonal:
        return seasonal
    if tfl and not tfl["issues"]:
        return config.travel_good_thumbnail_url or config.travel_thumbnail_url
    if tfl and tfl["issues"]:
        return config.travel_delay_thumbnail_url or config.travel_thumbnail_url
    return config.travel_thumbnail_url


def environment_thumbnail_url(air_quality: Optional[Dict[str, Any]], config: Optional[Config]) -> Optional[str]:
    if not config:
        return None
    seasonal = seasonal_pixel_url("environment", config.environment_thumbnail_url)
    if seasonal:
        return seasonal
    if not air_quality:
        return config.environment_thumbnail_url

    pollen = air_quality.get("top_pollen")
    pollen_status = pollen_level(pollen[1]) if pollen else "Unavailable"
    air_status = aqi_level(air_quality.get("european_aqi"))

    if pollen_status == "High":
        return config.pollen_high_thumbnail_url or config.environment_thumbnail_url
    if pollen_status == "Moderate":
        return config.pollen_moderate_thumbnail_url or config.environment_thumbnail_url
    if air_status in {"Poor", "Very poor", "Extremely poor"}:
        return config.air_poor_thumbnail_url or config.environment_thumbnail_url
    if air_status == "Moderate":
        return config.air_moderate_thumbnail_url or config.environment_thumbnail_url
    return (
        config.air_good_thumbnail_url
        or config.pollen_low_thumbnail_url
        or config.environment_thumbnail_url
    )


def strip_bullets(text: str) -> str:
    return text.removeprefix("• ").strip()


def escape_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def send_failure_alert(config: Config, title: str, detail: str) -> bool:
    if not config.enable_discord:
        return False

    message = (
        f"⚠️ **London Daily Debrief failed**\n"
        f"**{title}**\n"
        f"```text\n{truncate(detail, 1500)}\n```"
    )
    try:
        sent = send_discord_report(message, config=config, embeds=None)
        if sent:
            logger.info("Discord failure alert sent.")
        else:
            logger.error("Discord failure alert could not be sent.")
        return sent
    except Exception:
        logger.exception("Discord failure alert raised an unexpected error.")
        return False


def write_health_status(config: Config, status: Dict[str, Any]) -> None:
    try:
        config.health_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **status,
        }
        config.health_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Could not write health status file: %s", config.health_path)


def repair_local_runtime(config: Config) -> List[str]:
    repairs: List[str] = []
    for path in {config.history_path.parent, config.log_path.parent, config.health_path.parent}:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            repairs.append(f"Created missing directory: {path}")

    default_gifs = list(DEFAULT_PIXEL_ASSET_DIR.glob("*.gif"))
    seasonal_gifs = list(SEASONAL_ASSET_DIR.glob("*.gif"))
    if len(default_gifs) < 15 or len(seasonal_gifs) < EXPECTED_SEASONAL_GIF_COUNT:
        try:
            from scripts.generate_pixel_gifs import main as generate_pixel_gifs

            generate_pixel_gifs()
            repairs.append("Regenerated bundled pixel GIF assets.")
        except Exception:
            logger.exception("Could not regenerate bundled pixel GIF assets.")
            repairs.append("Could not regenerate bundled pixel GIF assets; check Pillow is installed.")

    return repairs


def deliver_discord_with_self_heal(
    config: Config,
    data: Dict[str, Any],
    brief: str,
) -> Dict[str, Any]:
    embeds = build_discord_embeds(data, config=config)
    attempts: List[Dict[str, Any]] = []

    rich = send_discord_report_detailed(
        "London Morning Brief",
        config=config,
        embeds=embeds,
    )
    attempts.append({"mode": "rich", "result": rich.summary()})
    if rich.success:
        return {"success": True, "mode": "rich", "attempts": attempts}

    no_images = send_discord_report_detailed(
        "London Morning Brief",
        config=config,
        embeds=embeds_without_images(embeds),
    )
    attempts.append({"mode": "embeds_without_images", "result": no_images.summary()})
    if no_images.success:
        send_failure_alert(
            config,
            "Self-healed Discord delivery",
            f"Rich embed delivery failed, but the briefing was sent without GIF attachments.\n{rich.summary()}",
        )
        return {"success": True, "mode": "embeds_without_images", "attempts": attempts}

    text = send_discord_report_detailed(
        truncate(brief, 5500),
        config=config,
        embeds=None,
    )
    attempts.append({"mode": "text_only", "result": text.summary()})
    if text.success:
        send_failure_alert(
            config,
            "Self-healed Discord delivery",
            "Rich embed delivery and image-free embed delivery failed, but the briefing was sent as text.\n"
            f"Rich: {rich.summary()}\nNo images: {no_images.summary()}",
        )
        return {"success": True, "mode": "text_only", "attempts": attempts}

    detail = "\n".join(f"{attempt['mode']}: {attempt['result']}" for attempt in attempts)
    send_failure_alert(config, "Discord delivery failed after self-heal attempts", detail)
    return {"success": False, "mode": "failed", "attempts": attempts}


# =========================
# MAIN
# =========================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Shorter WhatsApp-friendly output",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full detailed output (default)",
    )
    parser.add_argument(
        "--send-discord",
        action="store_true",
        help="Force Discord sending for this run if Discord credentials are configured",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Print only; do not send to Discord",
    )
    args = parser.parse_args()

    compact = args.compact and not args.full
    config = load_config()
    setup_logging(config)
    logger.info("London debrief run started.")

    if args.send_discord:
        config = replace(config, enable_discord=True)
    if args.no_discord:
        config = replace(config, enable_discord=False)

    try:
        repairs = repair_local_runtime(config)
        if repairs:
            logger.info("Self-repair actions completed: %s", repairs)

        data = collect_brief_data(config, compact=compact)
        brief = build_brief_from_data(data)
        print(brief)

        delivery_status: Dict[str, Any] = {"enabled": config.enable_discord}
        if config.enable_discord:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
            delivery_status = deliver_discord_with_self_heal(config, data, brief)
            if not delivery_status["success"]:
                logger.error("London debrief Discord delivery failed after self-heal attempts.")
                write_health_status(
                    config,
                    {
                        "status": "failed",
                        "stage": "discord_delivery",
                        "repairs": repairs,
                        "discord": delivery_status,
                    },
                )
                raise SystemExit(1)

        update_history(config.history_path, data)
        write_health_status(
            config,
            {
                "status": "ok",
                "repairs": repairs,
                "discord": delivery_status,
                "sources": {
                    "weather": data["weather"] is not None,
                    "tfl": data["tfl"] is not None,
                    "air_quality": data["air_quality"] is not None,
                    "news": bool(data["news"]),
                    "alerts": len(data["alerts"]),
                },
            },
        )
        logger.info("London debrief run finished.")
    except SystemExit:
        raise
    except Exception as exc:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logger.exception("London debrief run failed.")
        write_health_status(
            config,
            {
                "status": "failed",
                "stage": "run",
                "error": str(exc),
                "traceback": detail,
            },
        )
        send_failure_alert(config, "Scheduled run failed", detail)
        raise


if __name__ == "__main__":
    main()
