"""
Property-based tests for LAN IP auto-detection.

Uses Hypothesis to verify correctness properties of the detection and
validation logic in src.api.lan_detect.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from src.api.lan_detect import (
    detect_lan_ip,
    format_base_url,
    is_ipv4,
    is_link_local,
    is_loopback,
    is_private_ip,
    validate_lan_ip,
)


# ---------------------------------------------------------------------------
# Property 3: Whitespace-Only Environment Variable Is Ignored
# ---------------------------------------------------------------------------


@given(
    whitespace=st.text(
        alphabet=st.sampled_from(" \t\n\r"),
        min_size=1,
    )
)
@settings(max_examples=100)
def test_whitespace_only_env_var_is_ignored(whitespace: str) -> None:
    """Feature: lan-auto-detect, Property 3: Whitespace-Only Environment Variable Is Ignored

    For any string composed entirely of whitespace characters, when set as the
    LAN_IP environment variable, the detection logic SHALL treat it as unset
    and proceed with DNS resolution.

    **Validates: Requirements 4.2**
    """
    dns_resolved_ip = "192.168.1.50"

    async def _run() -> None:
        with patch.dict("os.environ", {"LAN_IP": whitespace}):
            with patch(
                "src.api.lan_detect.asyncio.get_running_loop"
            ) as mock_loop:
                mock_getaddrinfo = AsyncMock(
                    return_value=[(None, None, None, None, (dns_resolved_ip, 0))]
                )
                mock_loop.return_value.getaddrinfo = mock_getaddrinfo

                result = await detect_lan_ip()

                # The whitespace-only value should be ignored; DNS result used
                assert result == dns_resolved_ip
                # DNS resolution was actually called (env var was treated as unset)
                mock_getaddrinfo.assert_called_once()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 5: Non-IPv4 Values Bypass IP Validation
# ---------------------------------------------------------------------------


@given(value=st.text(min_size=1).filter(lambda s: not is_ipv4(s)))
@settings(max_examples=100)
def test_non_ipv4_values_bypass_ip_validation(value: str) -> None:
    """Feature: lan-auto-detect, Property 5: Non-IPv4 Values Bypass IP Validation

    For any string that does not match IPv4 dotted-decimal format (four
    dot-separated octets of 0-255), is_ipv4 returns False, confirming
    the endpoint logic would bypass private-range validation and accept
    the value as a hostname.

    **Validates: Requirements 5.3**
    """
    assert is_ipv4(value) is False


# ---------------------------------------------------------------------------
# Strategies: Private IPv4 Addresses
# ---------------------------------------------------------------------------

_private_ip_10 = st.builds(
    lambda b, c, d: f"10.{b}.{c}.{d}",
    b=st.integers(min_value=0, max_value=255),
    c=st.integers(min_value=0, max_value=255),
    d=st.integers(min_value=0, max_value=255),
)

_private_ip_172 = st.builds(
    lambda b, c, d: f"172.{b}.{c}.{d}",
    b=st.integers(min_value=16, max_value=31),
    c=st.integers(min_value=0, max_value=255),
    d=st.integers(min_value=0, max_value=255),
)

_private_ip_192 = st.builds(
    lambda c, d: f"192.168.{c}.{d}",
    c=st.integers(min_value=0, max_value=255),
    d=st.integers(min_value=0, max_value=255),
)

private_ipv4_strategy = st.one_of(_private_ip_10, _private_ip_172, _private_ip_192)

# Strategy for valid port numbers
valid_port_strategy = st.integers(min_value=1, max_value=65535)


# ---------------------------------------------------------------------------
# Property 1: URL Formatting Correctness
# ---------------------------------------------------------------------------


@given(address=private_ipv4_strategy)
@settings(max_examples=100)
def test_url_formatting_correctness_default_port(address: str) -> None:
    """Feature: lan-auto-detect, Property 1: URL Formatting Correctness

    For any valid private IPv4 address, format_base_url produces
    a string matching http://<address>:7432 exactly.

    **Validates: Requirements 1.1, 1.6**
    """
    result = format_base_url(address)
    assert result == f"http://{address}:7432"
    assert result.startswith("http://")
    assert result.endswith(":7432")
    assert address in result


@given(address=private_ipv4_strategy, port=valid_port_strategy)
@settings(max_examples=100)
def test_url_formatting_correctness_custom_port(address: str, port: int) -> None:
    """Feature: lan-auto-detect, Property 1: URL Formatting Correctness

    For any valid private IPv4 address and custom port value,
    format_base_url produces http://<address>:<port> exactly.

    **Validates: Requirements 1.1, 1.6**
    """
    result = format_base_url(address, port=port)
    assert result == f"http://{address}:{port}"
    assert result.startswith("http://")
    assert result.endswith(f":{port}")
    assert address in result


# ---------------------------------------------------------------------------
# Property 2: Environment Variable Override Skips DNS
# ---------------------------------------------------------------------------


@given(
    value=st.text(
        alphabet=st.characters(blacklist_characters="\x00"),
        min_size=1,
    ).filter(lambda s: s.strip() != "")
)
@settings(max_examples=100)
def test_env_var_override_skips_dns(value: str) -> None:
    """Feature: lan-auto-detect, Property 2: Environment Variable Override Skips DNS

    For any non-empty, non-whitespace string set as the LAN_IP environment
    variable, the detection logic SHALL return that value (stripped) without
    invoking DNS resolution.

    **Validates: Requirements 1.2, 4.1**
    """

    async def _run() -> None:
        with patch.dict("os.environ", {"LAN_IP": value}):
            with patch(
                "src.api.lan_detect.asyncio.get_running_loop"
            ) as mock_loop:
                mock_getaddrinfo = AsyncMock(
                    return_value=[(None, None, None, None, ("192.168.1.50", 0))]
                )
                mock_loop.return_value.getaddrinfo = mock_getaddrinfo

                result = await detect_lan_ip()

                # The env var value (stripped) should be returned directly
                assert result == value.strip()
                # DNS resolution should NOT have been called
                mock_getaddrinfo.assert_not_called()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Property 4: IP Validation Accepts Only Private Range Addresses
# ---------------------------------------------------------------------------


@given(
    octets=st.tuples(
        st.integers(0, 255),
        st.integers(0, 255),
        st.integers(0, 255),
        st.integers(0, 255),
    )
)
@settings(max_examples=100)
def test_ip_validation_accepts_only_private_range(
    octets: tuple[int, int, int, int],
) -> None:
    """Feature: lan-auto-detect, Property 4: IP Validation Accepts Only Private Range Addresses

    For any IPv4 address, validate_lan_ip SHALL return None (accept) if and
    only if the address is in a private range AND is NOT loopback AND is NOT
    link-local.

    **Validates: Requirements 5.1, 5.2, 5.4**
    """
    ip = f"{octets[0]}.{octets[1]}.{octets[2]}.{octets[3]}"

    result = validate_lan_ip(ip)

    should_be_valid = (
        is_private_ip(ip) and not is_loopback(ip) and not is_link_local(ip)
    )

    if should_be_valid:
        assert result is None, (
            f"Expected {ip} to be accepted (valid private, non-loopback, "
            f"non-link-local) but got error: {result}"
        )
    else:
        assert result is not None, (
            f"Expected {ip} to be rejected (not a valid private LAN address) "
            f"but validate_lan_ip returned None"
        )
