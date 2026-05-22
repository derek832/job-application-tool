"""Unit tests for Docker log filtering utilities."""

from __future__ import annotations

from src.pipeline.log_utils import filter_logs_by_url


class TestFilterLogsByUrl:
    """Tests for filter_logs_by_url."""

    def test_returns_lines_containing_full_url(self) -> None:
        """Lines containing the full target URL are included."""
        lines = [
            "2024-01-15 INFO Starting dry-run",
            "2024-01-15 INFO Processing https://boards.greenhouse.io/acme/jobs/123",
            "2024-01-15 INFO Field filled: name",
        ]
        result = filter_logs_by_url(
            lines, "https://boards.greenhouse.io/acme/jobs/123"
        )
        assert result == [
            "2024-01-15 INFO Processing https://boards.greenhouse.io/acme/jobs/123"
        ]

    def test_returns_lines_containing_domain(self) -> None:
        """Lines containing just the domain component are included."""
        lines = [
            "2024-01-15 INFO Navigating to boards.greenhouse.io",
            "2024-01-15 INFO Unrelated log entry",
            "2024-01-15 INFO Connection to boards.greenhouse.io established",
        ]
        result = filter_logs_by_url(
            lines, "https://boards.greenhouse.io/acme/jobs/123"
        )
        assert result == [
            "2024-01-15 INFO Navigating to boards.greenhouse.io",
            "2024-01-15 INFO Connection to boards.greenhouse.io established",
        ]

    def test_excludes_lines_without_url_or_domain(self) -> None:
        """Lines not containing the URL or domain are excluded."""
        lines = [
            "2024-01-15 INFO Starting pipeline",
            "2024-01-15 INFO Processing jobs.lever.co/other",
            "2024-01-15 INFO Done",
        ]
        result = filter_logs_by_url(
            lines, "https://boards.greenhouse.io/acme/jobs/123"
        )
        assert result == []

    def test_empty_log_lines(self) -> None:
        """Empty input returns empty output."""
        result = filter_logs_by_url([], "https://example.com/job/1")
        assert result == []

    def test_preserves_order(self) -> None:
        """Matching lines are returned in their original order."""
        lines = [
            "line3 boards.greenhouse.io something",
            "line1 unrelated",
            "line2 boards.greenhouse.io other",
        ]
        result = filter_logs_by_url(
            lines, "https://boards.greenhouse.io/acme/jobs/123"
        )
        assert result == [
            "line3 boards.greenhouse.io something",
            "line2 boards.greenhouse.io other",
        ]

    def test_url_with_port(self) -> None:
        """URLs with port numbers have their domain (including port) extracted."""
        lines = [
            "2024-01-15 INFO localhost:7432 responding",
            "2024-01-15 INFO other server",
        ]
        result = filter_logs_by_url(lines, "http://localhost:7432/jobs/1/test-apply")
        assert result == ["2024-01-15 INFO localhost:7432 responding"]

    def test_matches_both_url_and_domain(self) -> None:
        """A line matching both full URL and domain is included once."""
        lines = [
            "Loaded https://boards.greenhouse.io/acme/jobs/123 on boards.greenhouse.io",
        ]
        result = filter_logs_by_url(
            lines, "https://boards.greenhouse.io/acme/jobs/123"
        )
        assert len(result) == 1
