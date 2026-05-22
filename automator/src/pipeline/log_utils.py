"""Docker log filtering utilities.

Provides functions for filtering Docker log output to isolate entries
relevant to a specific validation run, identified by target URL or domain.

Validates: Requirements 3.4
"""

from __future__ import annotations

from urllib.parse import urlparse


def filter_logs_by_url(log_lines: list[str], target_url: str) -> list[str]:
    """Filter Docker log lines to those relevant to a target URL.

    Returns only lines that contain the full target URL or its domain
    component. This allows isolating log entries from a specific dry-run
    when multiple runs may be interleaved in the Docker log output.

    Args:
        log_lines: Raw Docker log lines (e.g., from ``docker compose logs``).
        target_url: The target job posting URL being validated.

    Returns:
        A list containing only lines that reference the target URL or its
        domain. Order is preserved from the input.
    """
    domain = urlparse(target_url).netloc

    return [line for line in log_lines if target_url in line or (domain and domain in line)]
