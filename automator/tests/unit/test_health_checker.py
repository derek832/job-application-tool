"""Unit tests for the session health checker module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from src.pipeline.health_checker import (
    HealthCheckResult,
    _check_chrome_reachable,
    _check_linkedin_session,
    check_session_health,
)


class TestHealthCheckResult:
    """Tests for the HealthCheckResult dataclass."""

    def test_healthy_result(self):
        result = HealthCheckResult(
            chrome_reachable=True,
            linkedin_authenticated=True,
            error_message=None,
            checked_at="2024-03-15T09:00:00+00:00",
        )
        assert result.chrome_reachable is True
        assert result.linkedin_authenticated is True
        assert result.error_message is None
        assert result.checked_at == "2024-03-15T09:00:00+00:00"

    def test_chrome_unreachable_result(self):
        result = HealthCheckResult(
            chrome_reachable=False,
            linkedin_authenticated=False,
            error_message="Chrome CDP is not reachable",
            checked_at="2024-03-15T09:00:00+00:00",
        )
        assert result.chrome_reachable is False
        assert result.linkedin_authenticated is False
        assert result.error_message == "Chrome CDP is not reachable"

    def test_linkedin_expired_result(self):
        result = HealthCheckResult(
            chrome_reachable=True,
            linkedin_authenticated=False,
            error_message="LinkedIn session expired — please log in to Chrome",
            checked_at="2024-03-15T09:00:00+00:00",
        )
        assert result.chrome_reachable is True
        assert result.linkedin_authenticated is False
        assert "LinkedIn session expired" in result.error_message


class TestCheckChromeReachable:
    """Tests for the _check_chrome_reachable helper."""

    @pytest.mark.asyncio
    async def test_chrome_reachable_success(self):
        """Chrome responds with 200 — should return True."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "Browser": "Chrome/122.0",
                        "webSocketDebuggerUrl": "ws://localhost:9222/...",
                    },
                )
            )
            result = await _check_chrome_reachable("http://localhost:9222")
        assert result is True

    @pytest.mark.asyncio
    async def test_chrome_reachable_non_200(self):
        """Chrome responds with non-200 — should return False."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                return_value=httpx.Response(500)
            )
            result = await _check_chrome_reachable("http://localhost:9222")
        assert result is False

    @pytest.mark.asyncio
    async def test_chrome_unreachable_connection_error(self):
        """Chrome is not running — connection error should return False."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            result = await _check_chrome_reachable("http://localhost:9222")
        assert result is False

    @pytest.mark.asyncio
    async def test_chrome_unreachable_timeout(self):
        """Chrome request times out — should return False."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                side_effect=httpx.TimeoutException("Timed out")
            )
            result = await _check_chrome_reachable("http://localhost:9222")
        assert result is False


class TestCheckSessionHealth:
    """Tests for the top-level check_session_health function."""

    @pytest.mark.asyncio
    async def test_chrome_unreachable_returns_failure(self):
        """When Chrome is unreachable, both checks fail."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            result = await check_session_health("http://localhost:9222")
        assert result.chrome_reachable is False
        assert result.linkedin_authenticated is False
        assert result.error_message == "Chrome CDP is not reachable"
        assert result.checked_at is not None

    @pytest.mark.asyncio
    async def test_chrome_reachable_linkedin_authenticated(self):
        """When Chrome is reachable and LinkedIn doesn't redirect, both pass."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "Browser": "Chrome/122.0",
                        "webSocketDebuggerUrl": "ws://localhost:9222/...",
                    },
                )
            )

            # Mock Playwright CDP connection and navigation
            mock_page = AsyncMock()
            mock_page.url = "https://www.linkedin.com/feed/"
            mock_page.goto = AsyncMock()
            mock_page.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)

            mock_browser = MagicMock()
            mock_browser.contexts = [mock_context]
            mock_browser.close = AsyncMock()

            mock_chromium = MagicMock()
            mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium

            with patch(
                "src.pipeline.health_checker.async_playwright"
            ) as mock_async_pw:
                mock_async_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
                mock_async_pw.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await check_session_health("http://localhost:9222")

        assert result.chrome_reachable is True
        assert result.linkedin_authenticated is True
        assert result.error_message is None

    @pytest.mark.asyncio
    async def test_chrome_reachable_linkedin_expired(self):
        """When Chrome is reachable but LinkedIn redirects to login, session is expired."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "Browser": "Chrome/122.0",
                        "webSocketDebuggerUrl": "ws://localhost:9222/...",
                    },
                )
            )

            # Mock Playwright — page redirects to login
            mock_page = AsyncMock()
            mock_page.url = "https://www.linkedin.com/login"
            mock_page.goto = AsyncMock()
            mock_page.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)

            mock_browser = MagicMock()
            mock_browser.contexts = [mock_context]
            mock_browser.close = AsyncMock()

            mock_chromium = MagicMock()
            mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium

            with patch(
                "src.pipeline.health_checker.async_playwright"
            ) as mock_async_pw:
                mock_async_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
                mock_async_pw.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await check_session_health("http://localhost:9222")

        assert result.chrome_reachable is True
        assert result.linkedin_authenticated is False
        assert "LinkedIn session expired" in result.error_message

    @pytest.mark.asyncio
    async def test_chrome_reachable_linkedin_authwall(self):
        """When LinkedIn redirects to authwall, session is expired."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "Browser": "Chrome/122.0",
                        "webSocketDebuggerUrl": "ws://localhost:9222/...",
                    },
                )
            )

            mock_page = AsyncMock()
            mock_page.url = "https://www.linkedin.com/authwall?trk=gf&trkInfo=..."
            mock_page.goto = AsyncMock()
            mock_page.close = AsyncMock()

            mock_context = MagicMock()
            mock_context.new_page = AsyncMock(return_value=mock_page)

            mock_browser = MagicMock()
            mock_browser.contexts = [mock_context]
            mock_browser.close = AsyncMock()

            mock_chromium = MagicMock()
            mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium

            with patch(
                "src.pipeline.health_checker.async_playwright"
            ) as mock_async_pw:
                mock_async_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
                mock_async_pw.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await check_session_health("http://localhost:9222")

        assert result.chrome_reachable is True
        assert result.linkedin_authenticated is False
        assert "LinkedIn session expired" in result.error_message

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        """When the entire check exceeds the timeout, returns timeout error."""
        import asyncio

        async def slow_response(*args, **kwargs):
            await asyncio.sleep(20)
            return httpx.Response(200)

        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                side_effect=slow_response
            )

            # Patch the timeout to be very short for testing
            with patch("src.pipeline.health_checker.HEALTH_CHECK_TIMEOUT_SECONDS", 0.1):
                result = await check_session_health("http://localhost:9222")

        assert result.chrome_reachable is False
        assert result.linkedin_authenticated is False
        assert "timed out" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_checked_at_is_iso_format(self):
        """The checked_at field should be a valid ISO 8601 timestamp."""
        from datetime import datetime

        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            result = await check_session_health("http://localhost:9222")

        # Should parse without error
        parsed = datetime.fromisoformat(result.checked_at)
        assert parsed is not None

    @pytest.mark.asyncio
    async def test_playwright_connection_error(self):
        """When Playwright fails to connect, returns linkedin check failure."""
        with respx.mock:
            respx.get("http://localhost:9222/json/version").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "Browser": "Chrome/122.0",
                        "webSocketDebuggerUrl": "ws://localhost:9222/...",
                    },
                )
            )

            with patch(
                "src.pipeline.health_checker.async_playwright"
            ) as mock_async_pw:
                mock_pw = MagicMock()
                mock_pw.chromium.connect_over_cdp = AsyncMock(
                    side_effect=Exception("WebSocket connection failed")
                )
                mock_async_pw.return_value.__aenter__ = AsyncMock(return_value=mock_pw)
                mock_async_pw.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await check_session_health("http://localhost:9222")

        assert result.chrome_reachable is True
        assert result.linkedin_authenticated is False
        assert "LinkedIn session check failed" in result.error_message
