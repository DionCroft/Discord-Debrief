"""Discord delivery for the London daily debrief."""

from __future__ import annotations

import copy
import json
import logging
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from config import PROJECT_ROOT, Config, load_config


logger = logging.getLogger(__name__)
DISCORD_API_BASE_URL = "https://discord.com/api/v10"
DISCORD_MESSAGE_LIMIT = 1900
DISCORD_EMBEDS_PER_MESSAGE = 10
DISCORD_ERROR_BODY_LIMIT = 1200
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_FIELD_LIMIT = 25
DISCORD_EMBED_FIELD_VALUE_LIMIT = 1024
DISCORD_EMBED_TITLE_LIMIT = 256
DISCORD_TOTAL_EMBED_TEXT_LIMIT = 6000
DISCORD_SAFE_TOTAL_EMBED_TEXT_LIMIT = 5800
DISCORD_UPLOAD_LIMIT_BYTES = 8 * 1024 * 1024
DISCORD_DELIVERY_ATTEMPTS = 3


@dataclass(frozen=True)
class DiscordDeliveryResult:
    success: bool
    method: str
    status_code: int | None = None
    error: str | None = None
    response_body: str | None = None

    def summary(self) -> str:
        parts = [f"method={self.method}", f"success={self.success}"]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.error:
            parts.append(f"error={self.error}")
        if self.response_body:
            parts.append(f"response={self.response_body}")
        return "; ".join(parts)


def embeds_without_images(embeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped = copy.deepcopy(embeds)
    for embed in stripped:
        embed.pop("image", None)
        embed.pop("thumbnail", None)
    return stripped


def send_discord_report(
    body: str,
    config: Config | None = None,
    embeds: list[dict[str, Any]] | None = None,
) -> bool:
    """Post the debrief to Discord when Discord delivery is enabled."""

    return send_discord_report_detailed(body, config=config, embeds=embeds).success


def send_discord_report_detailed(
    body: str,
    config: Config | None = None,
    embeds: list[dict[str, Any]] | None = None,
) -> DiscordDeliveryResult:
    """Post the debrief and return details that are useful for scheduled-run alerts."""

    config = config or load_config()
    if not config.enable_discord:
        logger.info("Discord disabled; skipping London debrief.")
        return DiscordDeliveryResult(success=False, method="disabled", error="Discord disabled")

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
    return DiscordDeliveryResult(
        success=False,
        method="unconfigured",
        error="Discord enabled but no delivery method is configured",
    )


def _send_via_webhook(
    body: str,
    webhook_url: str,
    embeds: list[dict[str, Any]] | None = None,
) -> DiscordDeliveryResult:
    last_response: requests.Response | None = None
    try:
        for payload in _payloads(body, embeds):
            _log_payload_preflight(payload)
            response = _post_discord_payload_with_retries(webhook_url, payload)
            last_response = response
            response.raise_for_status()
        logger.info("London debrief sent to Discord via webhook.")
        return DiscordDeliveryResult(success=True, method="webhook")
    except requests.RequestException as exc:
        logger.exception("Discord webhook delivery failed.")
        return _delivery_error_result("webhook", exc, last_response)


def _send_via_bot(
    body: str,
    bot_token: str,
    channel_id: str,
    embeds: list[dict[str, Any]] | None = None,
) -> DiscordDeliveryResult:
    last_response: requests.Response | None = None
    try:
        for payload in _payloads(body, embeds):
            _log_payload_preflight(payload)
            response = _post_discord_payload_with_retries(
                f"{DISCORD_API_BASE_URL}/channels/{channel_id}/messages",
                headers={
                    "Authorization": f"Bot {bot_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "LondonDailyDebrief/0.1",
                },
                payload=payload,
            )
            last_response = response
            response.raise_for_status()
        logger.info("London debrief sent to Discord via bot.")
        return DiscordDeliveryResult(success=True, method="bot")
    except requests.RequestException as exc:
        logger.exception("Discord bot delivery failed.")
        return _delivery_error_result("bot", exc, last_response)


def _payloads(body: str, embeds: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if embeds:
        payloads = []
        current: list[dict[str, Any]] = []
        current_text_length = 0

        for embed in embeds:
            embed_length = _embed_text_length(embed)
            if (
                current
                and (
                    len(current) >= DISCORD_EMBEDS_PER_MESSAGE
                    or current_text_length + embed_length > DISCORD_SAFE_TOTAL_EMBED_TEXT_LIMIT
                )
            ):
                payloads.append(
                    {
                        "content": body if not payloads else "",
                        "embeds": current,
                    }
                )
                current = []
                current_text_length = 0

            current.append(embed)
            current_text_length += embed_length

        if current:
            payloads.append(
                {
                    "content": body if not payloads else "",
                    "embeds": current,
                }
            )
        return payloads

    return [_message_payload(chunk) for chunk in _message_chunks(body)]


def _embed_text_length(embed: dict[str, Any]) -> int:
    total = len(embed.get("title", "")) + len(embed.get("description", ""))
    for field in embed.get("fields", []):
        total += len(field.get("name", "")) + len(field.get("value", ""))
    footer = embed.get("footer", {})
    if isinstance(footer, dict):
        total += len(footer.get("text", ""))
    author = embed.get("author", {})
    if isinstance(author, dict):
        total += len(author.get("name", ""))
    return total


def _post_discord_payload(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> requests.Response:
    payload, files = _with_local_asset_attachments(payload)
    if not files:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        _log_bad_response(response, payload, file_count=0)
        return response

    multipart_headers = dict(headers or {})
    multipart_headers.pop("Content-Type", None)
    try:
        response = requests.post(
            url,
            headers=multipart_headers or None,
            data={"payload_json": json.dumps(payload)},
            files=files,
            timeout=20,
        )
        _log_bad_response(response, payload, file_count=len(files))
        return response
    finally:
        for file_tuple in files.values():
            file_tuple[1].close()


def _post_discord_payload_with_retries(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    attempts: int = DISCORD_DELIVERY_ATTEMPTS,
) -> requests.Response:
    last_response: requests.Response | None = None
    last_error: requests.RequestException | None = None

    for attempt in range(1, attempts + 1):
        try:
            response = _post_discord_payload(url, payload, headers=headers)
            last_response = response
            if not _should_retry_response(response) or attempt == attempts:
                return response

            delay = _retry_delay(response, attempt)
            logger.warning(
                "Discord delivery attempt %s/%s returned retryable status %s; retrying in %.1fs.",
                attempt,
                attempts,
                response.status_code,
                delay,
            )
            time.sleep(delay)
        except requests.RequestException as exc:
            last_error = exc
            if attempt == attempts:
                raise
            delay = min(2 ** (attempt - 1), 8)
            logger.warning(
                "Discord delivery attempt %s/%s failed with %s; retrying in %.1fs.",
                attempt,
                attempts,
                exc,
                delay,
            )
            time.sleep(delay)

    if last_response is not None:
        return last_response
    if last_error is not None:
        raise last_error
    raise requests.RequestException("Discord delivery failed before making a request")


def _should_retry_response(response: requests.Response) -> bool:
    return response.status_code == 429 or 500 <= response.status_code < 600


def _retry_delay(response: requests.Response, attempt: int) -> float:
    try:
        data = response.json()
    except ValueError:
        data = {}
    retry_after = data.get("retry_after") or response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(float(retry_after), 30)
        except (TypeError, ValueError):
            pass
    return min(2 ** (attempt - 1), 8)


def _delivery_error_result(
    method: str,
    exc: requests.RequestException,
    response: requests.Response | None,
) -> DiscordDeliveryResult:
    if response is None:
        response = exc.response
    return DiscordDeliveryResult(
        success=False,
        method=method,
        status_code=response.status_code if response is not None else None,
        error=str(exc),
        response_body=_response_text(response) if response is not None else None,
    )


def _log_bad_response(
    response: requests.Response,
    payload: dict[str, Any],
    file_count: int,
) -> None:
    if response.status_code < 400:
        return

    logger.error(
        "Discord API rejected payload: status=%s body=%s summary=%s",
        response.status_code,
        _response_text(response),
        _payload_summary(payload, file_count),
    )


def _response_text(response: requests.Response | None) -> str | None:
    if response is None:
        return None
    text = response.text.strip()
    if len(text) > DISCORD_ERROR_BODY_LIMIT:
        text = text[:DISCORD_ERROR_BODY_LIMIT].rstrip() + "..."
    return text or None


def _payload_summary(payload: dict[str, Any], file_count: int) -> dict[str, Any]:
    embeds = payload.get("embeds", [])
    return {
        "content_length": len(payload.get("content", "")),
        "embed_count": len(embeds),
        "file_count": file_count,
        "embed_titles": [embed.get("title") for embed in embeds],
        "embed_description_lengths": [
            len(embed.get("description", "")) for embed in embeds
        ],
        "field_counts": [len(embed.get("fields", [])) for embed in embeds],
    }


def _log_payload_preflight(payload: dict[str, Any]) -> None:
    issues = _payload_preflight_issues(payload)
    if issues:
        logger.warning("Discord payload preflight warnings: %s", issues)


def _payload_preflight_issues(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    content = payload.get("content", "")
    if len(content) > DISCORD_MESSAGE_LIMIT:
        issues.append(f"content length {len(content)} exceeds {DISCORD_MESSAGE_LIMIT}")

    embeds = payload.get("embeds", [])
    total_text = 0
    for idx, embed in enumerate(embeds, start=1):
        title = embed.get("title", "")
        description = embed.get("description", "")
        fields = embed.get("fields", [])
        total_text += len(title) + len(description)
        if len(title) > DISCORD_EMBED_TITLE_LIMIT:
            issues.append(f"embed {idx} title length {len(title)} exceeds {DISCORD_EMBED_TITLE_LIMIT}")
        if len(description) > DISCORD_EMBED_DESCRIPTION_LIMIT:
            issues.append(
                f"embed {idx} description length {len(description)} exceeds {DISCORD_EMBED_DESCRIPTION_LIMIT}"
            )
        if len(fields) > DISCORD_EMBED_FIELD_LIMIT:
            issues.append(f"embed {idx} field count {len(fields)} exceeds {DISCORD_EMBED_FIELD_LIMIT}")
        for field_idx, field in enumerate(fields, start=1):
            total_text += len(field.get("name", "")) + len(field.get("value", ""))
            if len(field.get("value", "")) > DISCORD_EMBED_FIELD_VALUE_LIMIT:
                issues.append(
                    f"embed {idx} field {field_idx} value length {len(field.get('value', ''))} "
                    f"exceeds {DISCORD_EMBED_FIELD_VALUE_LIMIT}"
                )

    if total_text > DISCORD_TOTAL_EMBED_TEXT_LIMIT:
        issues.append(f"total embed text length {total_text} exceeds {DISCORD_TOTAL_EMBED_TEXT_LIMIT}")

    _, files = _with_local_asset_attachments(payload)
    try:
        for file_name, file_tuple in files.items():
            file_path = Path(file_tuple[1].name)
            file_size = file_path.stat().st_size
            if file_size > DISCORD_UPLOAD_LIMIT_BYTES:
                issues.append(
                    f"{file_name} size {file_size} exceeds {DISCORD_UPLOAD_LIMIT_BYTES} bytes"
                )
    finally:
        for file_tuple in files.values():
            file_tuple[1].close()

    return issues


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
