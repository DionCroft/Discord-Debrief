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
import logging
import re
from collections import Counter
from dataclasses import replace
from datetime import datetime
from typing import Any, Dict, List, Optional

import feedparser
import requests

from config import Config, load_config
from discord_notifier import send_discord_report


# =========================
# CONFIG
# =========================

LONDON_LAT = 51.5072
LONDON_LON = -0.1276

BBC_NEWS_RSS = "https://feeds.bbci.co.uk/news/rss.xml"
TFL_STATUS_URL = "https://api.tfl.gov.uk/Line/Mode/tube,dlr,overground,elizabeth-line/Status"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

REQUEST_TIMEOUT = 20
DISCORD_DESCRIPTION_LIMIT = 3900
DISCORD_FIELD_LIMIT = 1000

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


def collect_brief_data(compact: bool = False) -> Dict[str, Any]:
    now = datetime.now().strftime("%A, %d %B %Y")
    current_time = datetime.now().strftime("%H:%M")

    try:
        weather = get_weather()
    except Exception:
        weather = None

    try:
        tfl = get_tfl()
    except Exception:
        tfl = None

    try:
        air_quality = get_air_quality()
    except Exception:
        air_quality = None

    try:
        news = get_news(limit=3 if compact else 5)
    except Exception:
        news = []

    return {
        "now": now,
        "current_time": current_time,
        "weather": weather,
        "tfl": tfl,
        "air_quality": air_quality,
        "news": news,
        "compact": compact,
    }


def build_brief_from_data(data: Dict[str, Any]) -> str:
    now = data["now"]
    current_time = data["current_time"]
    weather = data["weather"]
    tfl = data["tfl"]
    air_quality = data["air_quality"]
    news = data["news"]
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
    return build_brief_from_data(collect_brief_data(compact=compact))


def build_discord_embeds(data: Dict[str, Any], config: Optional[Config] = None) -> List[Dict[str, Any]]:
    weather = data["weather"]
    tfl = data["tfl"]
    air_quality = data["air_quality"]
    news = data["news"]
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
            image_url=config.pixel_banner_url if config else None,
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
            thumbnail_url=config.weather_thumbnail_url if config else None,
        )
    )

    embeds.extend(
        build_discord_travel_embeds(
            tfl,
            compact,
            thumbnail_url=config.travel_thumbnail_url if config else None,
        )
    )

    embeds.append(
        with_optional_image(
            {
            "title": "▣ AIR QUALITY + POLLEN",
            "description": build_discord_environment(air_quality),
            "color": environment_status_color(air_quality),
            },
            thumbnail_url=config.environment_thumbnail_url if config else None,
        )
    )

    embeds.append(
        with_optional_image(
            {
            "title": "▣ NEWS",
            "description": build_discord_news(news, limit=5),
            "color": 0x3498DB,
            },
            thumbnail_url=config.news_thumbnail_url if config else None,
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


def strip_bullets(text: str) -> str:
    return text.removeprefix("• ").strip()


def escape_link_text(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


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
    data = collect_brief_data(compact=compact)
    brief = build_brief_from_data(data)
    print(brief)

    config = load_config()
    if args.send_discord:
        config = replace(config, enable_discord=True)
    if args.no_discord:
        config = replace(config, enable_discord=False)

    if config.enable_discord:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
        sent = send_discord_report(
            "London Morning Brief",
            config=config,
            embeds=build_discord_embeds(data, config=config),
        )
        if not sent:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
