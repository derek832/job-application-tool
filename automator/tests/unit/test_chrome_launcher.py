"""Unit tests for the Chrome CDP launcher and status checker.

Tests cover:
- get_chrome_status() returns connected=True with version info when Chrome responds
- get_chrome_status() returns connected=False on timeout/connection error
- get_chrome_status() returns connected=False on non-200 response
- launch_chrome() returns already_running=True when Chrome is already reachable
- launch_chrome() returns failure when Chrome binary is not found
- launch_chrome() spawns Chrome with correct flags and polls for readiness
- launch_chrome() returns failure on launch timeout
- _find_chrome_binary() returns None when no binary exists
- _build_chrome_command() produces correct arguments
- launch_chrome() never uses the user's default Chrome profile directory
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

from src.integrations.chrome_launcher import (
    ChromeStatus,
    _build_chrome_command,
    _find_chrome_binary,
    get_chrome_status,
    launch_chrome,
)

CDP_URL = "http://localhost:9222"
VERSION_URL = f"{CDP_URL}/json/version"

MOCK_VERSION_RESPONSE = {
    "Browser": "Chrome/122.0.6261.94",
    "Protocol-Version": "1.3",
    "User-Agent": "Mozilla/5.0",
    "V8-Version": "12.2.281.19",
    "WebKit-Version": "537.36",
    "webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/abc123",
}


class TestGetChromeStatus:
    """Tests for get_chrome_status()."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_connected_when_chrome_responds(self) -> None:
        respx.get(VERSION_URL).mock(return_value=httpx.Response(200, json=MOCK_VERSION_RESPONSE))

        result = await get_chrome_status(CDP_URL)

        assert result.connected is True
        assert result.browser_version == "Chrome/122.0.6261.94"
        assert result.debugger_url == "ws://localhost:9222/devtools/browser/abc123"

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_disconnected_on_timeout(self) -> None:
        respx.get(VERSION_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))

        result = await get_chrome_status(CDP_URL)

        assert result.connected is False
        assert result.browser_version is None
        assert result.debugger_url is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_disconnected_on_connection_error(self) -> None:
        respx.get(VERSION_URL).mock(side_effect=httpx.ConnectError("refused"))

        result = await get_chrome_status(CDP_URL)

        assert result.connected is False
        assert result.browser_version is None

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_disconnected_on_non_200(self) -> None:
        respx.get(VERSION_URL).mock(return_value=httpx.Response(500, text="error"))

        result = await get_chrome_status(CDP_URL)

        assert result.connected is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_strips_trailing_slash_from_url(self) -> None:
        respx.get(VERSION_URL).mock(return_value=httpx.Response(200, json=MOCK_VERSION_RESPONSE))

        result = await get_chrome_status("http://localhost:9222/")

        assert result.connected is True


class TestLaunchChrome:
    """Tests for launch_chrome()."""

    @pytest.mark.asyncio
    async def test_returns_already_running_when_chrome_reachable(self) -> None:
        mock_status = ChromeStatus(
            connected=True,
            browser_version="Chrome/122.0.6261.94",
            debugger_url="ws://localhost:9222/devtools/browser/abc123",
        )

        with patch(
            "src.integrations.chrome_launcher.get_chrome_status",
            new_callable=AsyncMock,
            return_value=mock_status,
        ):
            result = await launch_chrome(cdp_port=9222)

        assert result.success is True
        assert result.already_running is True
        assert "already running" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_failure_when_binary_not_found(self) -> None:
        mock_status = ChromeStatus(connected=False)

        with (
            patch(
                "src.integrations.chrome_launcher.get_chrome_status",
                new_callable=AsyncMock,
                return_value=mock_status,
            ),
            patch(
                "src.integrations.chrome_launcher._find_chrome_binary",
                return_value=None,
            ),
        ):
            result = await launch_chrome(cdp_port=9222)

        assert result.success is False
        assert result.already_running is False
        assert "not found" in result.message.lower()

    @pytest.mark.asyncio
    async def test_launches_chrome_and_polls_for_readiness(self) -> None:
        # First call: not connected (triggers launch)
        # Second call (after poll): connected
        status_responses = [
            ChromeStatus(connected=False),
            ChromeStatus(
                connected=True,
                browser_version="Chrome/122.0.6261.94",
                debugger_url="ws://localhost:9222/devtools/browser/abc123",
            ),
        ]
        call_count = 0

        async def mock_get_status(cdp_url: str = "") -> ChromeStatus:
            nonlocal call_count
            result = status_responses[min(call_count, len(status_responses) - 1)]
            call_count += 1
            return result

        mock_popen = MagicMock()

        with (
            patch(
                "src.integrations.chrome_launcher.get_chrome_status",
                side_effect=mock_get_status,
            ),
            patch(
                "src.integrations.chrome_launcher._find_chrome_binary",
                return_value="C:/Program Files/Google/Chrome/Application/chrome.exe",
            ),
            patch("src.integrations.chrome_launcher.subprocess.Popen", mock_popen),
            patch("src.integrations.chrome_launcher.Path.mkdir"),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await launch_chrome(cdp_port=9222)

        assert result.success is True
        assert result.already_running is False
        assert mock_popen.called

    @pytest.mark.asyncio
    async def test_returns_failure_on_launch_timeout(self) -> None:
        mock_status = ChromeStatus(connected=False)
        mock_popen = MagicMock()

        with (
            patch(
                "src.integrations.chrome_launcher.get_chrome_status",
                new_callable=AsyncMock,
                return_value=mock_status,
            ),
            patch(
                "src.integrations.chrome_launcher._find_chrome_binary",
                return_value="C:/Program Files/Google/Chrome/Application/chrome.exe",
            ),
            patch("src.integrations.chrome_launcher.subprocess.Popen", mock_popen),
            patch("src.integrations.chrome_launcher.Path.mkdir"),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await launch_chrome(cdp_port=9222)

        assert result.success is False
        assert "not reachable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_returns_failure_on_os_error(self) -> None:
        mock_status = ChromeStatus(connected=False)

        with (
            patch(
                "src.integrations.chrome_launcher.get_chrome_status",
                new_callable=AsyncMock,
                return_value=mock_status,
            ),
            patch(
                "src.integrations.chrome_launcher._find_chrome_binary",
                return_value="/usr/bin/google-chrome",
            ),
            patch(
                "src.integrations.chrome_launcher.subprocess.Popen",
                side_effect=OSError("Permission denied"),
            ),
            patch("src.integrations.chrome_launcher.Path.mkdir"),
        ):
            result = await launch_chrome(cdp_port=9222)

        assert result.success is False
        assert "permission denied" in result.message.lower()

    @pytest.mark.asyncio
    async def test_never_uses_default_chrome_profile(self) -> None:
        """Verify the user-data-dir is always the automation directory."""
        mock_status_disconnected = ChromeStatus(connected=False)
        mock_status_connected = ChromeStatus(
            connected=True,
            browser_version="Chrome/122.0.6261.94",
            debugger_url="ws://localhost:9222/devtools/browser/abc123",
        )

        call_count = 0

        async def mock_get_status(cdp_url: str = "") -> ChromeStatus:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_status_disconnected
            return mock_status_connected

        mock_popen = MagicMock()

        with (
            patch(
                "src.integrations.chrome_launcher.get_chrome_status",
                side_effect=mock_get_status,
            ),
            patch(
                "src.integrations.chrome_launcher._find_chrome_binary",
                return_value="/usr/bin/google-chrome",
            ),
            patch("src.integrations.chrome_launcher.subprocess.Popen", mock_popen),
            patch("src.integrations.chrome_launcher.Path.mkdir"),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await launch_chrome(cdp_port=9222)

        # Verify the command passed to Popen uses the automation user-data-dir
        popen_args = mock_popen.call_args[0][0]
        user_data_arg = [arg for arg in popen_args if "--user-data-dir=" in arg]
        assert len(user_data_arg) == 1
        assert "chrome-automation-profile" in user_data_arg[0]
        # Must NOT contain default profile paths
        assert ".config/google-chrome" not in user_data_arg[0]
        assert "User Data" not in user_data_arg[0]


class TestFindChromeBinary:
    """Tests for _find_chrome_binary()."""

    def test_returns_none_when_no_binary_exists(self) -> None:
        with patch("src.integrations.chrome_launcher.Path.exists", return_value=False):
            result = _find_chrome_binary()

        assert result is None

    def test_returns_first_existing_path(self) -> None:
        # Mock Path.exists to return True for the second candidate
        call_count = 0

        def mock_exists(self) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count == 2

        with patch("src.integrations.chrome_launcher.Path.exists", mock_exists):
            result = _find_chrome_binary()

        assert result is not None


class TestBuildChromeCommand:
    """Tests for _build_chrome_command()."""

    def test_includes_remote_debugging_port(self) -> None:
        cmd = _build_chrome_command("/usr/bin/chrome", 9222, "/tmp/profile")

        assert "--remote-debugging-port=9222" in cmd

    def test_includes_user_data_dir(self) -> None:
        cmd = _build_chrome_command("/usr/bin/chrome", 9222, "/tmp/profile")

        assert "--user-data-dir=/tmp/profile" in cmd

    def test_includes_no_first_run(self) -> None:
        cmd = _build_chrome_command("/usr/bin/chrome", 9222, "/tmp/profile")

        assert "--no-first-run" in cmd

    def test_first_element_is_binary(self) -> None:
        cmd = _build_chrome_command("/usr/bin/chrome", 9222, "/tmp/profile")

        assert cmd[0] == "/usr/bin/chrome"

    def test_custom_port(self) -> None:
        cmd = _build_chrome_command("/usr/bin/chrome", 9333, "/tmp/profile")

        assert "--remote-debugging-port=9333" in cmd
