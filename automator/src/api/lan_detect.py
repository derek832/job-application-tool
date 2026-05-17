"""
LAN IP detection and validation module.

Provides pure functions for IPv4 validation and LAN IP detection logic.
The detection strategy resolves the host machine's LAN-routable IP address
from within a Docker container, using either an explicit LAN_IP environment
variable or DNS resolution of host.docker.internal.

Validates: Requirements 1.2, 1.3, 4.1, 4.2, 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import asyncio
import os
import re
import socket

import structlog

logger = structlog.get_logger(__name__)

# Regex matching exactly four dot-separated octets (0-255)
_IPV4_PATTERN = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)


class LanDetectionError(Exception):
    """Raised when LAN IP detection fails (DNS timeout or resolution error)."""


def is_ipv4(value: str) -> bool:
    """Check if a string matches IPv4 dotted-decimal format.

    Validates that the string consists of exactly four dot-separated octets,
    each in the range 0-255.

    Args:
        value: The string to check.

    Returns:
        True if the string is a valid IPv4 address, False otherwise.
    """
    return _IPV4_PATTERN.match(value) is not None


def is_private_ip(address: str) -> bool:
    """Check if an IPv4 address is in a private network range.

    Private ranges (RFC 1918):
    - 10.0.0.0/8     (10.0.0.0 – 10.255.255.255)
    - 172.16.0.0/12  (172.16.0.0 – 172.31.255.255)
    - 192.168.0.0/16 (192.168.0.0 – 192.168.255.255)

    Args:
        address: A valid IPv4 address string.

    Returns:
        True if the address is in a private range, False otherwise.
    """
    parts = address.split(".")
    if len(parts) != 4:
        return False

    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return False

    # 10.0.0.0/8
    if octets[0] == 10:
        return True

    # 172.16.0.0/12 (172.16.x.x – 172.31.x.x)
    if octets[0] == 172 and 16 <= octets[1] <= 31:
        return True

    # 192.168.0.0/16
    if octets[0] == 192 and octets[1] == 168:
        return True

    return False


def is_loopback(address: str) -> bool:
    """Check if an IPv4 address is in the loopback range (127.0.0.0/8).

    Args:
        address: A valid IPv4 address string.

    Returns:
        True if the address is a loopback address, False otherwise.
    """
    parts = address.split(".")
    if len(parts) != 4:
        return False

    try:
        first_octet = int(parts[0])
    except ValueError:
        return False

    return first_octet == 127


def is_link_local(address: str) -> bool:
    """Check if an IPv4 address is in the link-local range (169.254.0.0/16).

    Args:
        address: A valid IPv4 address string.

    Returns:
        True if the address is a link-local address, False otherwise.
    """
    parts = address.split(".")
    if len(parts) != 4:
        return False

    try:
        octets = [int(p) for p in parts]
    except ValueError:
        return False

    return octets[0] == 169 and octets[1] == 254


def validate_lan_ip(address: str) -> str | None:
    """Validate an IPv4 address for LAN routability.

    Orchestrates validation checks to ensure the address is suitable for
    LAN communication. Returns None if valid, or an error message if invalid.

    Checks performed:
    1. Must not be a loopback address (127.0.0.0/8)
    2. Must not be a link-local address (169.254.0.0/16)
    3. Must be in a private network range (10/8, 172.16/12, 192.168/16)

    Args:
        address: A valid IPv4 address string.

    Returns:
        None if the address is valid for LAN use, or an error message string
        describing why the address is invalid.
    """
    if is_loopback(address) or is_link_local(address):
        return (
            f"Detected address {address} is not routable on the LAN "
            "(loopback or link-local address)."
        )

    if not is_private_ip(address):
        return (
            f"Detected address {address} does not appear to be a LAN IP. "
            "Expected a private network address "
            "(10.x.x.x, 172.16-31.x.x, or 192.168.x.x)."
        )

    return None


def format_base_url(host: str, port: int = 7432) -> str:
    """Format a host into a full base URL.

    Args:
        host: The IP address or hostname.
        port: The port number. Defaults to 7432.

    Returns:
        A URL string in the format ``http://<host>:<port>``.
    """
    return f"http://{host}:{port}"


async def detect_lan_ip() -> str:
    """Resolve the host machine's LAN IP address.

    Detection priority:
    1. LAN_IP environment variable (if set and non-whitespace)
    2. DNS resolution of host.docker.internal (5-second timeout)

    Returns:
        The raw IP address or hostname string.

    Raises:
        LanDetectionError: If DNS resolution fails or times out and no
            valid LAN_IP environment variable is set.
    """
    # Priority 1: LAN_IP environment variable
    lan_ip_env = os.environ.get("LAN_IP", "")
    if lan_ip_env.strip():
        logger.info("lan_detect_env_override", lan_ip=lan_ip_env.strip())
        return lan_ip_env.strip()

    # Priority 2: DNS resolution of host.docker.internal
    logger.info("lan_detect_dns_resolution", hostname="host.docker.internal")
    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.getaddrinfo("host.docker.internal", None, family=socket.AF_INET),
            timeout=5.0,
        )
        if not result:
            raise LanDetectionError(
                "Auto-detection failed: DNS resolution error for "
                "host.docker.internal. Set LAN_IP in your .env file "
                "as a fallback."
            )
        # getaddrinfo returns list of (family, type, proto, canonname, sockaddr)
        # sockaddr for AF_INET is (address, port)
        address = result[0][4][0]
        logger.info("lan_detect_resolved", address=address)
        return address

    except TimeoutError:
        raise LanDetectionError(
            "Auto-detection failed: could not resolve "
            "host.docker.internal within 5 seconds. Set LAN_IP in "
            "your .env file as a fallback."
        )
    except OSError as exc:
        raise LanDetectionError(
            "Auto-detection failed: DNS resolution error for "
            "host.docker.internal. Set LAN_IP in your .env file "
            "as a fallback."
        ) from exc
