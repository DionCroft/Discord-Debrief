"""Discord delivery for the London daily debrief."""

from __future__ import annotations

import copy
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

import requests

from config import PROJECT_ROOT, Config, load_config


logger = logging.getLogger(__name__)
DISCORD_API_BASE_URL = "https://discord.com/api/v10"
DISCORD_MESSAGE_LIMIT = 1900
DISCORD_EMBEDS_PER_MESSAGE = 10


def send_discord_report(
    body: str,
    config: Config | None = None,
    embeds: list[dict[str, Any]] | None = None,
) -> bool:
    """Post the debrief to Discord when Discord delivery is enabled."""

    config = config or load_config()
    if not config.enable_discord:
        logger.info("Discord disabled; skipping London debrief.")
        return False

    if config.discord_webhook_url:
        return _send_via_webhook(body, config.discord_webhook_url, embeds=embeds)

    if config.discord_bot_token and config.discord_channel_id:
        return _send_via_bot(
            body,
            config.discord_bot_token,
            config.discord_channel_id,
            embeds=embeds,
        )

    logger.warning(
        "Discord enabled but no delivery method is configured. "
        "Set DISCORD_WEBHOOK_URL or both DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID."
    )
    return False


def _send_via_webhook(
    body: str,
    webhook_url: str,
    embeds: list[dict[str, Any]] | None = None,
) -> bool:
    try:
        for payload in _payloads(body, embeds):
            response = _post_discord_payload(webhook_url, payload)
            response.raise_for_status()
        logger.info("London debrief sent to Discord via webhook.")
        return True
    except requests.RequestException:
        logger.exception("Discord webhook delivery failed.")
        return False


def _send_via_bot(
    body: str,
    bot_token: str,
    channel_id: str,
    embeds: list[dict[str, Any]] | None = None,
) -> bool:
    try:
        for payload in _payloads(body, embeds):
            response = _post_discord_payload(
                f"{DISCORD_API_BASE_URL}/channels/{channel_id}/messages",
                headers={
                    "Authorization": f"Bot {bot_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "LondonDailyDebrief/0.1",
                },
                payload=payload,
            )
            response.raise_for_status()
        logger.info("London debrief sent to Discord via bot.")
        return True
    except requests.RequestException:
        logger.exception("Discord bot delivery failed.")
        return False


def _payloads(body: str, embeds: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if embeds:
        payloads = []
        for start in range(0, len(embeds), DISCORD_EMBEDS_PER_MESSAGE):
            payloads.append(
                {
                    "content": body if start == 0 else "",
                    "embeds": embeds[start : start + DISCORD_EMBEDS_PER_MESSAGE],
                }
            )
        return payloads

    return [_message_payload(chunk) for chunk in _message_chunks(body)]


def _post_discord_payload(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> requests.Response:
    payload, files = _with_local_asset_attachments(payload)
    if not files:
        return requests.post(url, headers=headers, json=payload, timeout=20)

    multipart_headers = dict(headers or {})
    multipart_headers.pop("Content-Type", None)
    try:
        return requests.post(
            url,
            headers=multipart_headers or None,
            data={"payload_json": json.dumps(payload)},
            files=files,
            timeout=20,
        )
    finally:
        for file_tuple in files.values():
            file_tuple[1].close()


def _with_local_asset_attachments(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, tuple[str, Any, str]]]:
    payload = copy.deepcopy(payload)
    files: dict[str, tuple[str, Any, str]] = {}
    attached_paths: dict[Path, str] = {}

    for embed in payload.get("embeds", []):
        for key in ("image", "thumbnail"):
            image = embed.get(key)
            if not image:
                continue
            path = _local_asset_path(image.get("url", ""))
            if path is None:
                continue
            filename = attached_paths.get(path)
            if filename is None:
                filename = _attachment_filename(path, len(files))
                attached_paths[path] = filename
                files[f"files[{len(files)}]"] = (
                    filename,
                    path.open("rb"),
                    mimetypes.guess_type(filename)[0] or "application/octet-stream",
                )
            image["url"] = f"attachment://{filename}"

    return payload, files


def _local_asset_path(value: str) -> Path | None:
    if not value or value.startswith(("http://", "https://", "attachment://")):
        return None

    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()

    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError:
        return None

    if path.is_file():
        return path
    logger.warning("Configured Discord image asset does not exist: %s", path)
    return None


def _attachment_filename(path: Path, index: int) -> str:
    safe_stem = "".join(char if char.isalnum() else "-" for char in path.stem).strip("-")
    safe_stem = safe_stem or f"asset-{index + 1}"
    return f"{index + 1}-{safe_stem}{path.suffix.lower()}"


def _message_payload(body: str) -> dict[str, Any]:
    return {"content": body}


def _message_chunks(body: str) -> list[str]:
    """Split a Discord message without breaking lines where possible."""

    if len(body) <= DISCORD_MESSAGE_LIMIT:
        return [body]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in body.splitlines():
        line_length = len(line) + 1
        if current and current_length + line_length > DISCORD_MESSAGE_LIMIT:
            chunks.append("\n".join(current).rstrip())
            current = []
            current_length = 0

        if line_length > DISCORD_MESSAGE_LIMIT:
            for start in range(0, len(line), DISCORD_MESSAGE_LIMIT):
                chunks.append(line[start : start + DISCORD_MESSAGE_LIMIT])
            continue

        current.append(line)
        current_length += line_length

    if current:
        chunks.append("\n".join(current).rstrip())

    return chunks
