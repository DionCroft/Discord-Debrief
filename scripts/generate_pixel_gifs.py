"""Generate bundled pixel-art GIFs for the London daily debrief."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "assets" / "pixel-gifs"
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


def canvas(width: int = SIZE, height: int = SIZE) -> Image.Image:
    return Image.new("RGB", (width, height), INK)


def save_gif(name: str, frames: list[Image.Image], duration: int = DURATION_MS) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scaled = [
        frame.resize((frame.width * SCALE, frame.height * SCALE), Image.Resampling.NEAREST)
        for frame in frames
    ]
    scaled[0].save(
        OUT_DIR / name,
        save_all=True,
        append_images=scaled[1:],
        duration=duration,
        loop=0,
        optimize=False,
    )


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


if __name__ == "__main__":
    main()
