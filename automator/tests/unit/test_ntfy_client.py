"""Unit tests for the ntfy push notification client.

Tests cover:
- Successful publish returns NtfyResult(ok=True)
- 4xx errors are not retried
- 5xx errors are retried up to 3 times
- Network/timeout errors are retried
- Retry succeeds on second attempt
- Request body is correctly composed with and without actions
- Title is set to "Job Automator" and tags are included
"""

from __future__ import annotations

import httpx
import pytest
import respx

from src.integrations.ntfy_client import (
    NtfyAction,
    NtfyPayload,
    NtfySettings,
    _build_request_body,
    publish,
)

SERVER_URL = "https://ntfy.sh"
TOPIC = "a1b2c3d4e5f6g7h8"
PUBLISH_URL = SERVER_URL


@pytest.fixture
def settings() -> NtfySettings:
    return NtfySettings(
        server_url=SERVER_URL,
        urgent_topic=TOPIC,
        info_topic="i9j0k1l2m3n4o5p6",
        lan_base_url="http://192.168.1.100:7432",
        api_token="test-token-123",
    )


@pytest.fixture
def payload() -> NtfyPayload:
    return NtfyPayload(
        topic=TOPIC,
        title="Job Automator",
        message="Senior Engineer @ Acme Corp (85%): stretch_role",
        priority=4,
        tags=["briefcase"],
    )


@pytest.fixture
def payload_with_actions() -> NtfyPayload:
    return NtfyPayload(
        topic=TOPIC,
        title="Job Automator",
        message="Senior Engineer @ Acme Corp (85%): stretch_role",
        priority=4,
        tags=["briefcase"],
        actions=[
            NtfyAction(
                action="http",
                label="Approve",
                url="http://192.168.1.100:7432/queue/job123/approve",
                method="POST",
                headers={"Authorization": "Bearer test-token-123"},
            ),
            NtfyAction(
                action="http",
                label="Reject",
                url="http://192.168.1.100:7432/queue/job123/reject",
                method="POST",
                headers={"Authorization": "Bearer test-token-123"},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_publish_success(
    settings: NtfySettings, payload: NtfyPayload
) -> None:
    """Successful publish returns ok=True with status code."""
    with respx.mock:
        respx.post(PUBLISH_URL).mock(
            return_value=httpx.Response(200, json={"id": "msg123"})
        )
        result = await publish(payload, settings)

    assert result.ok is True
    assert result.status_code == 200
    assert result.error is None


@pytest.mark.asyncio
async def test_publish_4xx_no_retry(
    settings: NtfySettings,
    payload: NtfyPayload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4xx client errors are not retried."""
    monkeypatch.setattr("src.integrations.ntfy_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(403, text="Forbidden")

    with respx.mock:
        respx.post(PUBLISH_URL).mock(side_effect=side_effect)
        result = await publish(payload, settings)

    assert result.ok is False
    assert result.status_code == 403
    assert "403" in (result.error or "")
    assert call_count == 1  # No retry on 4xx


@pytest.mark.asyncio
async def test_publish_5xx_retries_exhausted(
    settings: NtfySettings,
    payload: NtfyPayload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5xx server errors are retried 3 times then fail."""
    monkeypatch.setattr("src.integrations.ntfy_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="Internal Server Error")

    with respx.mock:
        respx.post(PUBLISH_URL).mock(side_effect=side_effect)
        result = await publish(payload, settings)

    assert result.ok is False
    assert result.status_code == 500
    assert call_count == 3


@pytest.mark.asyncio
async def test_publish_network_error_retries(
    settings: NtfySettings,
    payload: NtfyPayload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network errors are retried 3 times then fail."""
    monkeypatch.setattr("src.integrations.ntfy_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection refused")

    with respx.mock:
        respx.post(PUBLISH_URL).mock(side_effect=side_effect)
        result = await publish(payload, settings)

    assert result.ok is False
    assert result.status_code is None
    assert "Network error" in (result.error or "")
    assert call_count == 3


@pytest.mark.asyncio
async def test_publish_timeout_retries(
    settings: NtfySettings,
    payload: NtfyPayload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timeout errors are retried 3 times then fail."""
    monkeypatch.setattr("src.integrations.ntfy_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("Read timed out")

    with respx.mock:
        respx.post(PUBLISH_URL).mock(side_effect=side_effect)
        result = await publish(payload, settings)

    assert result.ok is False
    assert result.status_code is None
    assert "Timeout" in (result.error or "")
    assert call_count == 3


@pytest.mark.asyncio
async def test_publish_retry_succeeds_on_second_attempt(
    settings: NtfySettings,
    payload: NtfyPayload,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry succeeds on the second attempt after a 5xx."""
    monkeypatch.setattr("src.integrations.ntfy_client.asyncio.sleep", _fake_sleep)

    call_count = 0

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, json={"id": "msg456"})

    with respx.mock:
        respx.post(PUBLISH_URL).mock(side_effect=side_effect)
        result = await publish(payload, settings)

    assert result.ok is True
    assert result.status_code == 200
    assert call_count == 2


@pytest.mark.asyncio
async def test_publish_sends_correct_json_body(
    settings: NtfySettings, payload: NtfyPayload
) -> None:
    """The request body includes topic, title, message, priority, and tags."""
    captured_request = None

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"id": "msg789"})

    with respx.mock:
        respx.post(PUBLISH_URL).mock(side_effect=side_effect)
        await publish(payload, settings)

    assert captured_request is not None
    import json

    body = json.loads(captured_request.content)
    assert body["topic"] == TOPIC
    assert body["title"] == "Job Automator"
    assert body["priority"] == 4
    assert body["tags"] == ["briefcase"]
    assert "Senior Engineer" in body["message"]
    assert "actions" not in body


@pytest.mark.asyncio
async def test_publish_includes_actions_in_body(
    settings: NtfySettings, payload_with_actions: NtfyPayload
) -> None:
    """Action buttons are included in the request body when present."""
    captured_request = None

    def side_effect(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"id": "msg101"})

    with respx.mock:
        respx.post(PUBLISH_URL).mock(side_effect=side_effect)
        await publish(payload_with_actions, settings)

    assert captured_request is not None
    import json

    body = json.loads(captured_request.content)
    assert "actions" in body
    assert len(body["actions"]) == 2
    assert body["actions"][0]["label"] == "Approve"
    assert body["actions"][0]["action"] == "http"
    assert body["actions"][0]["method"] == "POST"
    assert "approve" in body["actions"][0]["url"]
    assert body["actions"][1]["label"] == "Reject"
    assert "reject" in body["actions"][1]["url"]


@pytest.mark.asyncio
async def test_publish_url_construction_trailing_slash(
    payload: NtfyPayload,
) -> None:
    """Server URL with trailing slash is handled correctly."""
    settings = NtfySettings(
        server_url="https://ntfy.sh/",
        urgent_topic=TOPIC,
        info_topic="i9j0k1l2m3n4o5p6",
        lan_base_url=None,
        api_token="token",
    )

    with respx.mock:
        respx.post(PUBLISH_URL).mock(
            return_value=httpx.Response(200, json={"id": "msg"})
        )
        result = await publish(payload, settings)

    assert result.ok is True


def test_build_request_body_without_actions() -> None:
    """_build_request_body produces correct dict without actions."""
    payload = NtfyPayload(
        topic="test_topic",
        title="Job Automator",
        message="Test message",
        priority=3,
        tags=["chart_with_upwards_trend"],
    )
    body = _build_request_body(payload)

    assert body == {
        "topic": "test_topic",
        "title": "Job Automator",
        "message": "Test message",
        "priority": 3,
        "tags": ["chart_with_upwards_trend"],
    }
    assert "actions" not in body


def test_build_request_body_with_actions() -> None:
    """_build_request_body includes actions when present."""
    payload = NtfyPayload(
        topic="test_topic",
        title="Job Automator",
        message="Test message",
        priority=4,
        tags=["briefcase"],
        actions=[
            NtfyAction(
                action="http",
                label="Approve",
                url="http://lan:7432/queue/1/approve",
                method="POST",
                headers={"Authorization": "Bearer tok"},
            ),
        ],
    )
    body = _build_request_body(payload)

    assert "actions" in body
    assert len(body["actions"]) == 1
    assert body["actions"][0]["label"] == "Approve"
    assert body["actions"][0]["headers"] == {"Authorization": "Bearer tok"}


async def _fake_sleep(seconds: float) -> None:
    """No-op replacement for asyncio.sleep in tests."""
