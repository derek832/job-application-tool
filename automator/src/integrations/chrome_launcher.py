"""Chrome CDP launcher and status checker.

Detects whether Chrome is running with remote debugging enabled and
launches it as a detached subprocess if not. Always uses a dedicated
user-data-dir to avoid touching the user's default Chrome profile.

Validates: Requirements 5.1, 5.3, 5.4, 5.7, 5.8, 5.9
"""

from __future__ import annotations

import asyncio
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger(__name__)

AUTOMATION_USER_DATA_DIR = "data/chrome-automation-profile"
CDP_TIMEOUT: float = 3.0
LAUNCH_POLL_INTERVAL: float = 0.5
LAUNCH_POLL_MAX_WAIT: float = 10.0


@dataclass
class ChromeStatus:
    """Result of checking Chrome CDP reachability.

    Attributes:
        connected: True if Chrome responded on the CDP port.
        browser_version: Chrome version string, or None if not connected.
        debugger_url: WebSocket debugger URL, or None if not connected.
    """

    connected: bool
    browser_version: str | None = None
    debugger_url: str | None = None


@dataclass
class LaunchResult:
    """Result of attempting to launch Chrome.

    Attributes:
        success: True if Chrome is now reachable on the CDP port.
        message: Human-readable description of what happened.
        already_running: True if Chrome was already reachable (no launch needed).
    """

    success: bool
    message: str
    already_running: bool = False


def _find_chrome_binary() -> str | None:
    """Detect the Chrome binary path based on the current OS.

    Checks common installation locations for Windows, macOS, and Linux.
    Returns the first path that exists, or None if Chrome is not found.
    """
    system = platform.system()

    if system == "Windows":
        candidates = [
            Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        ]
    elif system == "Darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home()
            / "Applications"
            / "Google Chrome.app"
            / "Contents"
            / "MacOS"
            / "Google Chrome",
        ]
    else:
        # Linux
        candidates = [
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
            Path("/snap/bin/chromium"),
        ]

    for path in candidates:
        if path.exists():
            return str(path)

    return None


def _build_chrome_command(
    chrome_binary: str,
    cdp_port: int,
    user_data_dir: str,
) -> list[str]:
    """Build the Chrome launch command with remote debugging flags.

    Args:
        chrome_binary: Path to the Chrome executable.
        cdp_port: The remote debugging port (e.g. 9222).
        user_data_dir: Path to the dedicated automation profile directory.

    Returns:
        A list of command arguments for subprocess.Popen.
    """
    return [
        chrome_binary,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
    ]


async def get_chrome_status(cdp_url: str = "http://localhost:9222") -> ChromeStatus:
    """Check if Chrome is reachable on the CDP port.

    Performs an HTTP GET to {cdp_url}/json/version with a 3-second timeout.

    Args:
        cdp_url: The base URL for the Chrome DevTools Protocol endpoint.

    Returns:
        ChromeStatus with connected=True and version info if reachable,
        or connected=False if Chrome is not responding.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{cdp_url.rstrip('/')}/json/version",
                timeout=CDP_TIMEOUT,
            )

        if response.status_code == 200:
            data = response.json()
            return ChromeStatus(
                connected=True,
                browser_version=data.get("Browser"),
                debugger_url=data.get("webSocketDebuggerUrl"),
            )

        logger.warning(
            "chrome_status_unexpected_response",
            status_code=response.status_code,
            cdp_url=cdp_url,
        )
        return ChromeStatus(connected=False)

    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as exc:
        logger.debug(
            "chrome_status_not_reachable",
            cdp_url=cdp_url,
            error=str(exc),
        )
        return ChromeStatus(connected=False)


async def launch_chrome(
    cdp_port: int = 9222,
    user_data_dir: str = AUTOMATION_USER_DATA_DIR,
) -> LaunchResult:
    """Launch Chrome with remote debugging flags.

    If Chrome is already reachable on the specified port, returns success
    without launching a new process. Otherwise, spawns Chrome as a detached
    subprocess with --remote-debugging-port, --user-data-dir, and --no-first-run.

    Args:
        cdp_port: The remote debugging port to use.
        user_data_dir: Path to the dedicated automation profile directory.
            Never uses the user's default Chrome profile.

    Returns:
        LaunchResult indicating success/failure and whether Chrome was
        already running.
    """
    cdp_url = f"http://localhost:{cdp_port}"

    # Check if Chrome is already reachable — don't launch a duplicate
    status = await get_chrome_status(cdp_url)
    if status.connected:
        logger.info(
            "chrome_already_running",
            cdp_port=cdp_port,
            browser_version=status.browser_version,
        )
        return LaunchResult(
            success=True,
            message=f"Chrome already running ({status.browser_version})",
            already_running=True,
        )

    # Find Chrome binary
    chrome_binary = _find_chrome_binary()
    if chrome_binary is None:
        logger.error("chrome_binary_not_found", system=platform.system())
        return LaunchResult(
            success=False,
            message=(
                f"Chrome binary not found on {platform.system()}. "
                "Please install Google Chrome or set the path manually."
            ),
        )

    # Ensure user-data-dir exists
    user_data_path = Path(user_data_dir)
    user_data_path.mkdir(parents=True, exist_ok=True)

    # Build command
    cmd = _build_chrome_command(chrome_binary, cdp_port, str(user_data_path.resolve()))

    logger.info(
        "chrome_launching",
        command=cmd,
        cdp_port=cdp_port,
        user_data_dir=str(user_data_path.resolve()),
    )

    # Spawn Chrome as a detached subprocess
    try:
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=(sys.platform != "win32"),
            creationflags=creation_flags,
        )
    except OSError as exc:
        logger.error("chrome_launch_failed", error=str(exc))
        return LaunchResult(
            success=False,
            message=f"Failed to launch Chrome: {exc}",
        )

    # Poll until Chrome is reachable or timeout
    elapsed = 0.0
    while elapsed < LAUNCH_POLL_MAX_WAIT:
        await asyncio.sleep(LAUNCH_POLL_INTERVAL)
        elapsed += LAUNCH_POLL_INTERVAL

        status = await get_chrome_status(cdp_url)
        if status.connected:
            logger.info(
                "chrome_launch_success",
                cdp_port=cdp_port,
                browser_version=status.browser_version,
                elapsed_seconds=elapsed,
            )
            return LaunchResult(
                success=True,
                message=f"Chrome launched successfully ({status.browser_version})",
            )

    logger.error(
        "chrome_launch_timeout",
        cdp_port=cdp_port,
        timeout_seconds=LAUNCH_POLL_MAX_WAIT,
    )
    return LaunchResult(
        success=False,
        message=(
            f"Chrome process started but not reachable on port {cdp_port} "
            f"after {LAUNCH_POLL_MAX_WAIT} seconds."
        ),
    )
