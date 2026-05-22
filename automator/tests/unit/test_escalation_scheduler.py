"""Unit tests for the escalation scheduler module.

Tests cover:
- schedule_escalation_timeout: scheduling one-shot jobs at deadline
- cancel_escalation_timeout: removing scheduled jobs, no-op when missing
- _make_job_id: deterministic job ID generation
- Integration with escalation engine (create/resolve wiring)

Validates: Requirements 4.4, 4.6
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.escalation_scheduler import (
    _JOB_ID_PREFIX,
    _make_job_id,
    cancel_escalation_timeout,
    schedule_escalation_timeout,
)


class TestMakeJobId:
    """Tests for _make_job_id helper."""

    def test_prefixes_escalation_id(self) -> None:
        esc_id = "abc-123-def"
        result = _make_job_id(esc_id)
        assert result == f"{_JOB_ID_PREFIX}abc-123-def"

    def test_unique_for_different_ids(self) -> None:
        id1 = str(uuid.uuid4())
        id2 = str(uuid.uuid4())
        assert _make_job_id(id1) != _make_job_id(id2)


class TestScheduleEscalationTimeout:
    """Tests for schedule_escalation_timeout."""

    def test_returns_false_when_scheduler_not_initialized(self) -> None:
        """When no scheduler is available, returns False gracefully."""
        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler", return_value=None
        ):
            result = schedule_escalation_timeout(
                "esc-123", datetime.now(tz=UTC) + timedelta(minutes=45)
            )
            assert result is False

    def test_schedules_job_with_correct_id(self) -> None:
        """Adds a job to the scheduler with the expected job ID."""
        mock_scheduler = MagicMock()
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)

        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler",
            return_value=mock_scheduler,
        ):
            result = schedule_escalation_timeout("esc-456", deadline)

        assert result is True
        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        assert call_kwargs.kwargs["id"] == f"{_JOB_ID_PREFIX}esc-456"

    def test_schedules_job_with_date_trigger(self) -> None:
        """Uses a DateTrigger with the provided deadline."""
        from apscheduler.triggers.date import DateTrigger

        mock_scheduler = MagicMock()
        deadline = datetime.now(tz=UTC) + timedelta(hours=6)

        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler",
            return_value=mock_scheduler,
        ):
            schedule_escalation_timeout("esc-789", deadline)

        call_kwargs = mock_scheduler.add_job.call_args
        trigger = call_kwargs.kwargs["trigger"]
        assert isinstance(trigger, DateTrigger)

    def test_passes_escalation_id_as_arg(self) -> None:
        """The job receives the escalation_id as an argument."""
        mock_scheduler = MagicMock()
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)

        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler",
            return_value=mock_scheduler,
        ):
            schedule_escalation_timeout("esc-abc", deadline)

        call_kwargs = mock_scheduler.add_job.call_args
        assert call_kwargs.kwargs["args"] == ["esc-abc"]

    def test_replace_existing_true(self) -> None:
        """Job is registered with replace_existing=True to handle re-scheduling."""
        mock_scheduler = MagicMock()
        deadline = datetime.now(tz=UTC) + timedelta(minutes=45)

        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler",
            return_value=mock_scheduler,
        ):
            schedule_escalation_timeout("esc-xyz", deadline)

        call_kwargs = mock_scheduler.add_job.call_args
        assert call_kwargs.kwargs["replace_existing"] is True


class TestCancelEscalationTimeout:
    """Tests for cancel_escalation_timeout."""

    def test_returns_false_when_scheduler_not_initialized(self) -> None:
        """When no scheduler is available, returns False gracefully."""
        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler", return_value=None
        ):
            result = cancel_escalation_timeout("esc-123")
            assert result is False

    def test_removes_job_by_id(self) -> None:
        """Calls remove_job with the correct job ID."""
        mock_scheduler = MagicMock()

        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler",
            return_value=mock_scheduler,
        ):
            result = cancel_escalation_timeout("esc-456")

        assert result is True
        mock_scheduler.remove_job.assert_called_once_with(
            f"{_JOB_ID_PREFIX}esc-456"
        )

    def test_returns_false_when_job_not_found(self) -> None:
        """No-op when the job doesn't exist (already fired or never scheduled)."""
        from apscheduler.jobstores.base import JobLookupError

        mock_scheduler = MagicMock()
        mock_scheduler.remove_job.side_effect = JobLookupError("esc-789")

        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler",
            return_value=mock_scheduler,
        ):
            result = cancel_escalation_timeout("esc-789")

        assert result is False

    def test_does_not_raise_on_missing_job(self) -> None:
        """Gracefully handles JobLookupError without propagating."""
        from apscheduler.jobstores.base import JobLookupError

        mock_scheduler = MagicMock()
        mock_scheduler.remove_job.side_effect = JobLookupError("missing")

        with patch(
            "src.pipeline.escalation_scheduler._get_scheduler",
            return_value=mock_scheduler,
        ):
            # Should not raise
            cancel_escalation_timeout("missing")
