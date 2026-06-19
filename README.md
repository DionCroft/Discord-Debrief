# London Daily Debrief

Builds a London daily brief with weather, TfL status, air quality, pollen, BBC news, and commuter insight.

## Install

```bash
cd daily-debrief
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

`--send-discord` forces Discord delivery for that run if credentials are configured. Discord receives a styled embed briefing with overview, weather, travel, air quality, pollen, and news sections. You can also set `ENABLE_DISCORD=true` for scheduled use, and pass `--no-discord` to skip sending for a single run. Bot tokens should only live in `.env` or another secret store.

Optional pixel-art images can be added with public image or GIF URLs:

```env
PIXEL_BANNER_URL=
WEATHER_THUMBNAIL_URL=
ENVIRONMENT_THUMBNAIL_URL=
TRAVEL_THUMBNAIL_URL=
NEWS_THUMBNAIL_URL=
```

Travel keeps the full disruption details and will split into continuation embeds if there are too many issues for one Discord card.

## Cron Example

```cron
0 */4 * * * /home/cadmus/Projects/Debrief/daily-debrief/run_discord_debrief.sh
```

This runs every 4 hours and appends output to `logs/london_daily_debrief.log`.
