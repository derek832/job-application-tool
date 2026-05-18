"""Ntfy push notification client.

A thin async HTTP client that publishes messages to ntfy.sh topics via
JSON POST. Stateless — all configuration is passed in per call.

Retry policy: 3 attempts with backoff delays of 5s, 15s, 30s.
Uses httpx with a 10-second timeout per request.
Does NOT retry on 4xx client errors.

Validates: Requirements 1.1, 1.3, 1.4, 1.5
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS: int = 3
BACKOFF_SECONDS: list[float] = [5.0, 15.0, 30.0]
REQUEST_TIMEOUT: float = 10.0


@dataclass
class NtfySettings:
    """Configuration for the ntfy client.

    Attributes:
        server_url: The ntfy server base URL (e.g. "https://ntfy.sh").
        urgent_topic: 16-char hex topic for urgent notifications.
        info_topic: 16-char hex topic for informational notifications.
        lan_base_url: LAN base URL for action button callbacks, or None.
        api_token: Bearer token for action button Authorization headers.
    """

    server_url: str
    urgent_topic: str
    info_topic: str
    lan_base_url: str | None
    api_token: str


@dataclass
class NtfyAction:
    """An ntfy notification action button (type: http).

    Attributes:
        action: The action type, always "http".
        label: Button label shown to the user (e.g. "Approve").
        url: The callback URL triggered when the button is tapped.
        method: HTTP method for the callback (e.g. "POST").
        headers: Headers sent with the callback request.
    """

    action: str
    label: str
    url: str
    method: str
    headers: dict[str, str]


@dataclass
class NtfyPayload:
    """The message payload to publish to an ntfy topic.

    Attributes:
        topic: The ntfy topic name to publish to.
        title: Notification title (always "Job Automator").
        message: The notification body text.
        priority: ntfy priority level (3=default, 4=high).
        tags: List of emoji tag names for the notification.
        actions: Optional list of action buttons to include.
    """

    topic: str
    title: str
    message: str
    priority: int
    tags: list[str]
    actions: list[NtfyAction] | None = None


@dataclass
class NtfyResult:
    """Outcome of an ntfy publish operation.

    Attributes:
        ok: True if the message was published successfully.
        error: Description of the failure, or None on success.
        status_code: HTTP status code from the last attempt, or None.
    """

    ok: bool
    error: str | None = None
    status_code: int | None = None


def _build_request_body(payload: NtfyPayload) -> dict:
    """Build the JSON request body for the ntfy publish API.

    Args:
        payload: The notification payload to serialize.

    Returns:
        A dict suitable for JSON serialization.
    """
    body: dict = {
        "topic": payload.topic,
        "title": payload.title,
        "message": payload.message,
        "priority": payload.priority,
        "tags": payload.tags,
    }

    if payload.actions:
        body["actions"] = [
            {
                "action": action.action,
                "label": action.label,
                "url": action.url,
                "method": action.method,
                "headers": action.headers,
            }
            for action in payload.actions
        ]

    return body


async def publish(payload: NtfyPayload, settings: NtfySettings) -> NtfyResult:
    """Publish a message to an ntfy topic with retry logic.

    Posts a JSON payload to the ntfy server root URL with the topic in the
    body. Retries up to 3 times with backoff delays of 5s, 15s, 30s on
    server errors (5xx) and network failures. Does NOT retry on 4xx client
    errors.

    Args:
        payload: The notification payload to publish.
        settings: Ntfy server configuration.

    Returns:
        An NtfyResult indicating success or failure.
    """
    url = settings.server_url.rstrip("/")
    body = _build_request_body(payload)
    last_error: str | None = None
    last_status: int | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.debug(
            "ntfy_publish_attempt",
            attempt=attempt,
            max_attempts=MAX_ATTEMPTS,
            topic=payload.topic,
            url=url,
        )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=body,
                    timeout=REQUEST_TIMEOUT,
                )

            last_status = response.status_code

            # Success
            if response.status_code < 400:
                logger.info(
                    "ntfy_publish_success",
                    attempt=attempt,
                    topic=payload.topic,
                    status_code=response.status_code,
                )
                return NtfyResult(ok=True, status_code=response.status_code)

            # 4xx client error — do not retry
            if 400 <= response.status_code < 500:
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.error(
                    "ntfy_publish_client_error",
                    attempt=attempt,
                    status_code=response.status_code,
                    topic=payload.topic,
                    error=last_error,
                )
                return NtfyResult(
                    ok=False,
                    error=last_error,
                    status_code=response.status_code,
                )

            # 5xx server error — retry with backoff
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            logger.warning(
                "ntfy_publish_server_error",
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                status_code=response.status_code,
                topic=payload.topic,
            )

        except httpx.TimeoutException as exc:
            last_error = f"Timeout: {exc}"
            last_status = None
            logger.warning(
                "ntfy_publish_timeout",
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                topic=payload.topic,
                error=last_error,
            )

        except httpx.HTTPError as exc:
            last_error = f"Network error: {exc}"
            last_status = None
            logger.warning(
                "ntfy_publish_network_error",
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                topic=payload.topic,
                error=last_error,
            )

        # Backoff before next attempt (skip if last attempt)
        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(BACKOFF_SECONDS[attempt - 1])

    logger.error(
        "ntfy_publish_exhausted",
        max_attempts=MAX_ATTEMPTS,
        topic=payload.topic,
        error=last_error,
    )
    return NtfyResult(ok=False, error=last_error, status_code=last_status)
