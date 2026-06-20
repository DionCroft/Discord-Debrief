# London Daily Debrief

Builds a London daily brief with weather, TfL status, alerts, air quality, pollen, BBC news, commuter insight, and a tiny local trend memory.

## Install

```bash
git clone https://github.com/DionCroft/Discord-Debrief.git
cd Discord-Debrief
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run Locally

```bash
python london_brief_data.py
python london_brief_data.py --compact
```

## Send To Discord

Copy `.env.example` to `.env`, then configure one Discord delivery method.

Webhook:

```env
ENABLE_DISCORD=true
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Bot token:

```env
ENABLE_DISCORD=true
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_CHANNEL_ID=your-channel-id
```

Then run:

```bash
python london_brief_data.py --send-discord
```

`--send-discord` forces Discord delivery for that run if credentials are configured. Discord receives a styled embed briefing with overview, weather, travel, air quality, pollen, alerts, trends, and news sections. You can also set `ENABLE_DISCORD=true` for scheduled use, and pass `--no-discord` to skip sending for a single run. Bot tokens should only live in `.env` or another secret store.

Bundled pixel-art GIFs live in `assets/pixel-gifs/` and are used by default. Discord uploads them with the message as local attachments, so the briefing does not depend on hotlinked image URLs.

The default pack includes 80 cozy seasonal pixel GIFs in `assets/pixel-gifs/seasonal/`:

- categories: banner, weather, travel, environment, news
- seasons: spring, summer, autumn, winter
- time of day: day, night
- variants: 1 and 2

Files follow this pattern:

```text
{category}-{season}-{day|night}-{1|2}.gif
```

For example, `weather-summer-day-1.gif` or `news-winter-night-2.gif`.

You can override any built-in GIF with a public URL or another local file path inside this project:

```env
PIXEL_BANNER_URL=
WEATHER_THUMBNAIL_URL=
WEATHER_CLEAR_THUMBNAIL_URL=
WEATHER_CLOUD_THUMBNAIL_URL=
WEATHER_RAIN_THUMBNAIL_URL=
WEATHER_STORM_THUMBNAIL_URL=
WEATHER_FOG_THUMBNAIL_URL=
ENVIRONMENT_THUMBNAIL_URL=
AIR_GOOD_THUMBNAIL_URL=
AIR_MODERATE_THUMBNAIL_URL=
AIR_POOR_THUMBNAIL_URL=
POLLEN_LOW_THUMBNAIL_URL=
POLLEN_MODERATE_THUMBNAIL_URL=
POLLEN_HIGH_THUMBNAIL_URL=
TRAVEL_THUMBNAIL_URL=
TRAVEL_GOOD_THUMBNAIL_URL=
TRAVEL_DELAY_THUMBNAIL_URL=
NEWS_THUMBNAIL_URL=
```

The script chooses seasonal category GIFs automatically from the current month and hour. The older state-specific GIFs remain as fallback assets.

Regenerate the bundled GIF pack after editing the generator:

```bash
python scripts/generate_pixel_gifs.py
```

Travel keeps the full disruption details and will split into continuation embeds if there are too many issues for one Discord card.

## Alerts And Memory

The briefing includes an Alerts section built from:

- weather thresholds from Open-Meteo
- TfL line status and disruption endpoints
- optional RSS/Atom feeds from `ALERT_FEED_URLS`

Set `ALERT_FEED_URLS` as a comma-separated list if you have trusted Met Office warning or London event feeds:

```env
ALERT_FEED_URLS=https://example.com/warnings.xml,https://example.com/events.xml
```

Each successful run stores a tiny history snapshot in `data/brief_history.json` by default. The next run compares rain risk, wind, TfL disruption count, AQI, and pollen, then adds a "Since Last Run" summary. Override paths with:

```env
HISTORY_PATH=
LOG_PATH=
```

Source-level failures are logged to `logs/london_daily_debrief.log`, so cron runs show which source failed instead of only showing "Unavailable".

## Cron Example

```cron
0 */4 * * * /home/cadmus/Projects/Debrief/daily-debrief/run_discord_debrief.sh
```

This runs every 4 hours and appends output to `logs/london_daily_debrief.log`. Update the path if you cloned the repo somewhere else.

## Systemd Boot Timer

The Pi can run the debrief automatically after reboot and then every 4 hours with the bundled user timer:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/daily-debrief.service ~/.config/systemd/user/
cp systemd/daily-debrief.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now daily-debrief.timer
```

Check the timer:

```bash
systemctl --user list-timers daily-debrief.timer
systemctl --user status daily-debrief.timer
```

Run a debrief immediately:

```bash
systemctl --user start daily-debrief.service
```

Read logs:

```bash
tail -f logs/london_daily_debrief.log
```
