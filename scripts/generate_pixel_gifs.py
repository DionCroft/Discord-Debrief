"""Generate bundled pixel-art GIFs for the London daily debrief."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "pixel-gifs"
SEASONAL_DIR = OUT_DIR / "seasonal"
SCALE = 3
SIZE = 48
FRAME_COUNT = 8
DURATION_MS = 130

INK = "#151625"
OUTLINE = "#ffffff"
SHADOW = "#272a46"
BLUE = "#56a7ff"
CYAN = "#8ee7ff"
YELLOW = "#ffd166"
ORANGE = "#ff9f43"
RED = "#ff5c5c"
GREEN = "#7bd88f"
LIME = "#c5f56f"
PINK = "#ff7abd"
LAVENDER = "#b9b5ff"
GREY = "#a5adba"

SEASONS = ("spring", "summer", "autumn", "winter")
DAY_PARTS = ("day", "night")
CATEGORIES = ("banner", "weather", "travel", "environment", "news")
SEASON_PALETTES = {
    "spring": {
        "sky_day": "#8bd9ff",
        "sky_night": "#202c59",
        "ground": "#6fd36f",
        "accent": "#ff9ac8",
        "crop": "#b6f56b",
        "tree": "#7bd88f",
    },
    "summer": {
        "sky_day": "#56b8ff",
        "sky_night": "#17234d",
        "ground": "#45b85c",
        "accent": "#ffd166",
        "crop": "#ffdd57",
        "tree": "#2fb36d",
    },
    "autumn": {
        "sky_day": "#f0a35e",
        "sky_night": "#291f3f",
        "ground": "#9b6a3d",
        "accent": "#ff7a3d",
        "crop": "#d96d2b",
        "tree": "#c86b2e",
    },
    "winter": {
        "sky_day": "#b7d7ff",
        "sky_night": "#18213d",
        "ground": "#dbeafe",
        "accent": "#9de7ff",
        "crop": "#f8fafc",
        "tree": "#a7c7d9",
    },
}


def canvas(width: int = SIZE, height: int = SIZE) -> Image.Image:
    return Image.new("RGB", (width, height), INK)


def save_gif_path(path: Path, frames: list[Image.Image], duration: int = DURATION_MS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    scaled = [
        frame.resize((frame.width * SCALE, frame.height * SCALE), Image.Resampling.NEAREST)
        for frame in frames
    ]
    scaled[0].save(
        path,
        save_all=True,
        append_images=scaled[1:],
        duration=duration,
        loop=0,
        optimize=False,
    )


def save_gif(name: str, frames: list[Image.Image], duration: int = DURATION_MS) -> None:
    save_gif_path(OUT_DIR / name, frames, duration)


def sparkle(draw: ImageDraw.ImageDraw, x: int, y: int, color: str = OUTLINE) -> None:
    draw.point((x, y - 1), fill=color)
    draw.point((x - 1, y), fill=color)
    draw.point((x, y), fill=color)
    draw.point((x + 1, y), fill=color)
    draw.point((x, y + 1), fill=color)


def cloud(draw: ImageDraw.ImageDraw, x: int, y: int, color: str = OUTLINE) -> None:
    draw.rectangle((x + 5, y + 10, x + 31, y + 18), fill=color)
    draw.rectangle((x + 10, y + 6, x + 22, y + 20), fill=color)
    draw.rectangle((x + 20, y + 8, x + 34, y + 20), fill=color)
    draw.rectangle((x + 7, y + 13, x + 36, y + 21), fill=color)
    draw.rectangle((x + 9, y + 15, x + 34, y + 23), fill=color)


def make_weather_clear() -> list[Image.Image]:
    frames = []
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        d.rectangle((0, 35, 47, 47), fill="#252a3f")
        d.rectangle((17, 17, 31, 31), fill=YELLOW)
        d.rectangle((20, 14, 28, 34), fill=YELLOW)
        d.rectangle((14, 20, 34, 28), fill=YELLOW)
        d.rectangle((19, 19, 29, 29), fill="#fff1a8")
        for x, y in [(7, 9), (39, 12), (11, 31), (38, 35)]:
            if (i + x) % 3 == 0:
                sparkle(d, x, y, CYAN)
        frames.append(img)
    return frames


def make_weather_cloud() -> list[Image.Image]:
    frames = []
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        d.rectangle((0, 35, 47, 47), fill="#252a3f")
        cloud(d, 4 + (i % 3), 14, OUTLINE)
        cloud(d, 14 - (i % 2), 22, GREY)
        d.rectangle((0, 40, 47, 47), fill="#303650")
        frames.append(img)
    return frames


def make_weather_rain() -> list[Image.Image]:
    frames = []
    drops = [(12, 30), (22, 28), (32, 31), (17, 36), (29, 38)]
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        cloud(d, 7, 8, OUTLINE)
        for x, y in drops:
            offset = (i * 3) % 10
            yy = y + offset
            if yy > 45:
                yy -= 18
            d.line((x, yy, x - 3, yy + 5), fill=BLUE, width=1)
        frames.append(img)
    return frames


def make_weather_storm() -> list[Image.Image]:
    frames = []
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        cloud(d, 7, 7, GREY)
        bolt = YELLOW if i % 2 == 0 else ORANGE
        d.polygon([(24, 27), (18, 37), (24, 36), (20, 47), (34, 31), (27, 32)], fill=bolt)
        if i % 2 == 0:
            d.rectangle((0, 0, 47, 47), outline="#4b5280")
        frames.append(img)
    return frames


def make_weather_fog() -> list[Image.Image]:
    frames = []
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        cloud(d, 7, 8, GREY)
        for row, y in enumerate([29, 35, 41]):
            shift = (i + row * 3) % 8
            d.rectangle((2 + shift, y, 36 + shift, y + 2), fill="#d9e2ec")
            d.rectangle((-14 + shift, y, -2 + shift, y + 2), fill="#d9e2ec")
        frames.append(img)
    return frames


def make_travel(good: bool) -> list[Image.Image]:
    frames = []
    signal = GREEN if good else RED
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        train_x = 4 + (i % 2)
        d.rectangle((train_x, 13, train_x + 39, 32), fill=OUTLINE)
        d.rectangle((train_x + 3, 17, train_x + 11, 23), fill=BLUE)
        d.rectangle((train_x + 15, 17, train_x + 23, 23), fill=BLUE)
        d.rectangle((train_x + 27, 17, train_x + 35, 23), fill=BLUE)
        d.rectangle((train_x + 7, 34, train_x + 32, 36), fill=GREY)
        d.rectangle((8, 40, 40, 42), fill=SHADOW)
        d.rectangle((38, 5, 43, 10), fill=signal if good or i % 2 == 0 else ORANGE)
        if not good:
            d.rectangle((18, 6, 30, 9), fill=ORANGE)
        frames.append(img)
    return frames


def make_air(level: str) -> list[Image.Image]:
    colors = {"good": GREEN, "moderate": YELLOW, "poor": RED}
    color = colors[level]
    frames = []
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        d.rectangle((9, 28, 17, 39), fill=OUTLINE)
        d.rectangle((20, 20, 28, 39), fill=OUTLINE)
        d.rectangle((31, 12, 39, 39), fill=OUTLINE)
        d.rectangle((7, 40, 41, 42), fill=GREY)
        for row, y in enumerate([10, 17, 24]):
            shift = (i * 2 + row * 4) % 18
            d.rectangle((2 + shift, y, 17 + shift, y + 1), fill=color)
            d.rectangle((24 + shift, y, 33 + shift, y + 1), fill=color)
        frames.append(img)
    return frames


def make_pollen(level: str) -> list[Image.Image]:
    colors = {"low": LIME, "moderate": YELLOW, "high": PINK}
    color = colors[level]
    frames = []
    grains = [(10, 12), (22, 9), (35, 15), (15, 28), (31, 31), (39, 24)]
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        d.rectangle((22, 20, 25, 39), fill=GREEN)
        d.rectangle((14, 28, 22, 33), fill=GREEN)
        d.rectangle((25, 25, 35, 30), fill=GREEN)
        d.rectangle((18, 11, 30, 23), fill=color)
        d.rectangle((15, 14, 33, 20), fill=color)
        d.rectangle((21, 8, 27, 26), fill=color)
        d.rectangle((22, 14, 26, 20), fill="#fff6bd")
        for x, y in grains:
            yy = y + ((i + x) % 5)
            d.rectangle((x, yy, x + 1, yy + 1), fill=color)
        frames.append(img)
    return frames


def make_news() -> list[Image.Image]:
    frames = []
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        d.rectangle((8, 9, 40, 39), fill=OUTLINE)
        d.rectangle((12, 13, 25, 22), fill=BLUE)
        if i % 2 == 0:
            d.rectangle((14, 15, 23, 20), fill=CYAN)
        for row, y in enumerate([14, 19, 26, 31, 36]):
            width = 13 + ((i + row) % 4) * 3
            d.rectangle((28 if row < 2 else 12, y, 28 + width if row < 2 else 12 + width + 16, y + 1), fill=INK)
        sparkle(d, 36, 12 + (i % 3), YELLOW)
        frames.append(img)
    return frames


def make_banner() -> list[Image.Image]:
    frames = []
    width, height = 128, 40
    for i in range(FRAME_COUNT):
        img = canvas(width, height)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, width - 1, height - 1), fill="#202236", outline=OUTLINE)
        d.rectangle((8, 24, 120, 31), fill="#343957")
        d.rectangle((18, 14, 34, 24), fill=OUTLINE)
        d.rectangle((21, 17, 31, 21), fill=BLUE)
        d.rectangle((40, 10, 52, 31), fill=OUTLINE)
        d.rectangle((56, 16, 76, 31), fill=OUTLINE)
        d.rectangle((82, 12, 100, 31), fill=OUTLINE)
        d.rectangle((104, 18, 116, 31), fill=OUTLINE)
        d.rectangle((42, 13, 49, 19), fill="#202236")
        d.rectangle((60, 19, 72, 23), fill="#202236")
        d.rectangle((86, 15, 96, 20), fill="#202236")
        for x in range(10 + i * 3, width, 24):
            sparkle(d, x, 7, CYAN)
        frames.append(img)
    return frames


def seasonal_sky(draw: ImageDraw.ImageDraw, season: str, period: str, width: int, height: int, frame: int) -> None:
    palette = SEASON_PALETTES[season]
    sky = palette["sky_day"] if period == "day" else palette["sky_night"]
    ground = palette["ground"]
    draw.rectangle((0, 0, width - 1, height - 1), fill=sky)
    draw.rectangle((0, height - 13, width - 1, height - 1), fill=ground)

    if period == "day":
        draw.rectangle((width - 18, 6, width - 10, 14), fill=YELLOW)
        draw.rectangle((width - 20, 8, width - 8, 12), fill=YELLOW)
    else:
        draw.rectangle((width - 18, 6, width - 11, 13), fill="#e9edff")
        for x, y in [(8, 7), (23, 11), (39, 5), (width - 33, 16)]:
            if (frame + x) % 3 == 0:
                sparkle(draw, x, y, "#eef6ff")

    if season == "winter":
        for x in range((frame * 2) % 8, width, 12):
            draw.point((x, 18 + ((x + frame) % 13)), fill=OUTLINE)
    elif season == "autumn":
        for x in range((frame * 2) % 11, width, 15):
            draw.rectangle((x, 24 + ((x + frame) % 10), x + 1, 25 + ((x + frame) % 10)), fill=ORANGE)
    elif season == "spring":
        for x in range(4, width, 16):
            draw.point((x + (frame % 3), height - 16, ), fill=PINK)
    else:
        for x in range(5 + frame % 5, width, 20):
            sparkle(draw, x, height - 18, YELLOW)


def draw_crop_rows(draw: ImageDraw.ImageDraw, season: str, width: int, height: int, frame: int) -> None:
    palette = SEASON_PALETTES[season]
    for y in range(height - 10, height - 2, 4):
        draw.rectangle((4, y, width - 5, y + 1), fill="#3a3f53")
    for x in range(8, width - 5, 9):
        bob = (frame + x) % 2
        draw.rectangle((x, height - 11 - bob, x + 2, height - 8 - bob), fill=palette["crop"])


def draw_cottage(draw: ImageDraw.ImageDraw, x: int, y: int, season: str, period: str, variant: int) -> None:
    palette = SEASON_PALETTES[season]
    roof = "#9c4f2f" if season != "winter" else "#8aa4bf"
    wall = "#f4d39b" if period == "day" else "#d6b078"
    draw.rectangle((x + 3, y + 10, x + 22, y + 25), fill=wall, outline=INK)
    draw.polygon([(x, y + 11), (x + 13, y), (x + 26, y + 11)], fill=roof)
    draw.rectangle((x + 11, y + 16, x + 15, y + 25), fill="#5c3b2e")
    window = palette["accent"] if period == "night" else "#78c8ff"
    draw.rectangle((x + 5, y + 14, x + 9, y + 18), fill=window)
    if variant == 2:
        draw.rectangle((x + 18, y + 14, x + 21, y + 18), fill=window)


def draw_tree(draw: ImageDraw.ImageDraw, x: int, y: int, season: str, frame: int) -> None:
    palette = SEASON_PALETTES[season]
    draw.rectangle((x + 5, y + 13, x + 8, y + 26), fill="#6b4f32")
    leaf = palette["tree"]
    if season == "winter":
        leaf = "#eef6ff"
    draw.rectangle((x, y + 7 + frame % 2, x + 14, y + 17 + frame % 2), fill=leaf)
    draw.rectangle((x + 3, y + 2, x + 11, y + 19), fill=leaf)


def draw_category_icon(
    draw: ImageDraw.ImageDraw,
    category: str,
    season: str,
    period: str,
    variant: int,
    frame: int,
    x: int = 16,
    y: int = 13,
) -> None:
    palette = SEASON_PALETTES[season]
    if category == "weather":
        if variant == 1:
            if period == "day":
                draw.rectangle((x + 7, y, x + 17, y + 10), fill=YELLOW)
                draw.rectangle((x + 9, y - 2, x + 15, y + 12), fill=YELLOW)
                draw.rectangle((x + 5, y + 2, x + 19, y + 8), fill=YELLOW)
            cloud(draw, x - 4 + frame % 2, y + 7, OUTLINE)
        else:
            cloud(draw, x - 2, y + 1, OUTLINE)
            for drop_x in [x + 2, x + 10, x + 18]:
                yy = y + 22 + (frame * 2 + drop_x) % 7
                draw.line((drop_x, yy, drop_x - 2, yy + 4), fill=BLUE)
    elif category == "travel":
        offset = frame % 2
        draw.rectangle((x - 6 + offset, y + 5, x + 25 + offset, y + 20), fill=OUTLINE)
        for win in [x - 3, x + 7, x + 17]:
            draw.rectangle((win + offset, y + 9, win + 6 + offset, y + 13), fill=BLUE)
        draw.rectangle((x - 3, y + 23, x + 24, y + 24), fill=INK)
        draw.rectangle((x + 26, y + 1, x + 30, y + 5), fill=GREEN if variant == 1 else ORANGE)
    elif category == "environment":
        draw.rectangle((x + 8, y + 10, x + 11, y + 25), fill=GREEN)
        draw.rectangle((x + 2, y + 16, x + 8, y + 20), fill=GREEN)
        draw.rectangle((x + 11, y + 14, x + 19, y + 18), fill=GREEN)
        draw.rectangle((x + 5, y + 1, x + 17, y + 13), fill=palette["accent"])
        draw.rectangle((x + 2, y + 5, x + 20, y + 10), fill=palette["accent"])
        for grain_x in [x - 2, x + 24, x + 28]:
            grain_y = y + 3 + ((frame + grain_x) % 10)
            draw.rectangle((grain_x, grain_y, grain_x + 1, grain_y + 1), fill=palette["accent"])
    elif category == "news":
        draw.rectangle((x - 5, y, x + 24, y + 25), fill=OUTLINE)
        draw.rectangle((x - 1, y + 4, x + 12, y + 11), fill=palette["accent"])
        if frame % 2 == 0:
            draw.rectangle((x + 1, y + 5, x + 10, y + 9), fill=CYAN)
        for idx, yy in enumerate([y + 5, y + 10, y + 16, y + 21]):
            draw.rectangle((x + 15 if idx < 2 else x - 1, yy, x + 21, yy + 1), fill=INK)
    else:
        draw_cottage(draw, x - 8, y - 2, season, period, variant)
        draw_tree(draw, x + 21, y - 2, season, frame)


def make_seasonal_card(category: str, season: str, period: str, variant: int) -> list[Image.Image]:
    frames = []
    for i in range(FRAME_COUNT):
        img = canvas()
        d = ImageDraw.Draw(img)
        seasonal_sky(d, season, period, SIZE, SIZE, i)
        draw_crop_rows(d, season, SIZE, SIZE, i + variant)
        draw_category_icon(d, category, season, period, variant, i)
        frames.append(img)
    return frames


def make_seasonal_banner(season: str, period: str, variant: int) -> list[Image.Image]:
    frames = []
    width, height = 128, 40
    for i in range(FRAME_COUNT):
        img = canvas(width, height)
        d = ImageDraw.Draw(img)
        seasonal_sky(d, season, period, width, height, i)
        draw_crop_rows(d, season, width, height, i + variant)
        draw_cottage(d, 14, 8, season, period, variant)
        draw_tree(d, 46, 8, season, i)
        draw_category_icon(d, "weather", season, period, variant, i, x=76, y=9)
        draw_category_icon(d, "travel", season, period, variant, i, x=97, y=8)
        frames.append(img)
    return frames


ASSETS: dict[str, Callable[[], list[Image.Image]]] = {
    "banner.gif": make_banner,
    "weather-clear.gif": make_weather_clear,
    "weather-cloud.gif": make_weather_cloud,
    "weather-rain.gif": make_weather_rain,
    "weather-storm.gif": make_weather_storm,
    "weather-fog.gif": make_weather_fog,
    "travel-good.gif": lambda: make_travel(good=True),
    "travel-delay.gif": lambda: make_travel(good=False),
    "air-good.gif": lambda: make_air("good"),
    "air-moderate.gif": lambda: make_air("moderate"),
    "air-poor.gif": lambda: make_air("poor"),
    "pollen-low.gif": lambda: make_pollen("low"),
    "pollen-moderate.gif": lambda: make_pollen("moderate"),
    "pollen-high.gif": lambda: make_pollen("high"),
    "news.gif": make_news,
}


def main() -> None:
    for name, maker in ASSETS.items():
        save_gif(name, maker())
        print(f"Generated {OUT_DIR / name}")

    for category in CATEGORIES:
        for season in SEASONS:
            for period in DAY_PARTS:
                for variant in (1, 2):
                    name = f"{category}-{season}-{period}-{variant}.gif"
                    if category == "banner":
                        frames = make_seasonal_banner(season, period, variant)
                    else:
                        frames = make_seasonal_card(category, season, period, variant)
                    path = SEASONAL_DIR / name
                    save_gif_path(path, frames)
                    print(f"Generated {path}")


if __name__ == "__main__":
    main()
