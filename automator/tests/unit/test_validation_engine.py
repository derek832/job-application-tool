"""Unit tests for the validation engine integration module.

Tests prerequisite checks, platform ordering, dry-run evaluation,
and workflow state transitions.

Validates: Requirements 6.1, 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.agents.visual_form_filler import FillResult
from src.pipeline.fix_cycle_manager import FixCycleManager
from src.pipeline.validation_engine import (
    check_branch_deployed,
    check_cdp_accessible,
    check_docker_healthy,
    evaluate_dry_run,
    get_platform_order,
    run_prerequisite_checks,
)
from src.pipeline.validation_models import (
    PlatformValidationState,
    ValidationSession,
    generate_report,
)


class TestGetPlatformOrder:
    """Tests for get_platform_order()."""

    def test_get_platform_order(self):
        """Assert returns exactly the fixed order: greenhouse, lever, workday, icims, bamboohr."""
        expected = ["greenhouse", "lever", "workday", "icims", "bamboohr"]
        assert get_platform_order() == expected


class TestEvaluateDryRun:
    """Tests for evaluate_dry_run() combining pass criteria, classification, and log filtering."""

    def test_evaluate_dry_run_passing(self):
        """A FillResult with ok=True, fields_filled=5 should pass."""
        fill_result = FillResult(ok=True, fields_filled=5, fields_found=5, reason=None)
        docker_logs = (
            "2024-01-01 INFO boards.greenhouse.io loaded\n"
            "2024-01-01 INFO unrelated log line\n"
            "2024-01-01 INFO visual_fields_identified boards.greenhouse.io\n"
        )
        target_url = "https://boards.greenhouse.io/company/jobs/123"

        result = evaluate_dry_run(fill_result, docker_logs, target_url)

        assert result["passed"] is True
        assert result["fields_filled"] == 5

    def test_evaluate_dry_run_failing_no_fields(self):
        """A FillResult with ok=False, fields_filled=0, fields_found=0 should fail as no_fields_detected."""
        fill_result = FillResult(ok=False, fields_filled=0, fields_found=0)
        docker_logs = "2024-01-01 INFO some log line\n"
        target_url = "https://boards.greenhouse.io/company/jobs/456"

        result = evaluate_dry_run(fill_result, docker_logs, target_url)

        assert result["passed"] is False
        assert result["failure_category"] == "no_fields_detected"

    def test_evaluate_dry_run_failing_low_fill(self):
        """A FillResult with ok=True, fields_filled=1 should fail as low_fill_count."""
        fill_result = FillResult(ok=True, fields_filled=1, fields_found=5)
        docker_logs = "2024-01-01 INFO some log line\n"
        target_url = "https://jobs.lever.co/company/789"

        result = evaluate_dry_run(fill_result, docker_logs, target_url)

        assert result["passed"] is False
        assert result["failure_category"] == "low_fill_count"

    def test_evaluate_dry_run_relevant_logs_filtered(self):
        """Only log lines containing the target URL domain should be in relevant_logs."""
        fill_result = FillResult(ok=True, fields_filled=5, fields_found=5, reason=None)
        docker_logs = (
            "2024-01-01 INFO boards.greenhouse.io page loaded\n"
            "2024-01-01 INFO unrelated line about lever\n"
            "2024-01-01 INFO navigating to boards.greenhouse.io/company\n"
            "2024-01-01 DEBUG something else entirely\n"
        )
        target_url = "https://boards.greenhouse.io/company/jobs/123"

        result = evaluate_dry_run(fill_result, docker_logs, target_url)

        # Only lines containing "boards.greenhouse.io" should be included
        assert len(result["relevant_logs"]) == 2
        for line in result["relevant_logs"]:
            assert "boards.greenhouse.io" in line


class TestPrerequisiteCheckDockerFailure:
    """Tests for check_docker_healthy() failure scenarios."""

    @patch("src.pipeline.validation_engine.subprocess.run")
    def test_prerequisite_check_docker_failure(self, mock_run: MagicMock):
        """Docker compose ps returning exited status should report failure."""
        mock_run.return_value = MagicMock(
            stdout="automator  exited (1)",
            returncode=0,
        )

        ok, message = check_docker_healthy()

        assert ok is False
        assert "not healthy" in message


class TestPrerequisiteCheckCdpFailure:
    """Tests for check_cdp_accessible() failure scenarios."""

    @patch("src.pipeline.validation_engine.subprocess.run")
    def test_prerequisite_check_cdp_failure(self, mock_run: MagicMock):
        """Curl failing should report CDP not accessible."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=7,  # curl connection refused
        )

        ok, message = check_cdp_accessible()

        assert ok is False
        assert message  # Non-empty failure message


class TestPrerequisiteCheckBranchFailure:
    """Tests for check_branch_deployed() failure scenarios."""

    @patch("src.pipeline.validation_engine.subprocess.run")
    def test_prerequisite_check_branch_failure(self, mock_run: MagicMock):
        """ls returning non-zero should report branch not deployed."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=1,
        )

        ok, message = check_branch_deployed()

        assert ok is False
        assert "not found" in message


class TestRunPrerequisiteChecks:
    """Tests for run_prerequisite_checks() stopping at first failure."""

    @patch("src.pipeline.validation_engine.check_docker_healthy")
    def test_run_prerequisite_checks_stops_at_first_failure(self, mock_docker: MagicMock):
        """When Docker health fails, subsequent checks are not run."""
        mock_docker.return_value = (False, "Docker automator service is not healthy. Output: exited")

        ok, message = run_prerequisite_checks()

        assert ok is False
        assert "Docker health" in message


class TestWorkflowStateTransitions:
    """Tests for workflow state transitions using validation models."""

    def test_workflow_state_pending_to_pass(self):
        """A platform transitioning from pending to pass should be reflected in the report."""
        state = PlatformValidationState(
            platform="greenhouse",
            status="pending",
            active_url="https://boards.greenhouse.io/company/jobs/123",
            fields_filled=5,
        )

        # Transition to pass
        state.status = "pass"

        session = ValidationSession(
            platforms={"greenhouse": state},
            overall_status="complete",
            start_time="2024-01-01T00:00:00",
            end_time="2024-01-01T01:00:00",
        )

        report = generate_report(session)

        # Find the greenhouse entry
        gh_report = next(p for p in report.platforms if p.platform == "greenhouse")
        assert gh_report.status == "pass"
        assert gh_report.fields_filled == 5
        assert gh_report.target_url == "https://boards.greenhouse.io/company/jobs/123"

    def test_workflow_state_pending_to_fail_after_5_cycles(self):
        """After 5 fix cycles, is_exhausted returns True."""
        manager = FixCycleManager()
        platform = "workday"

        # Consume all 5 cycles
        for _ in range(5):
            result = manager.consume_cycle(platform)
            assert result is True

        # 6th attempt should fail
        assert manager.is_exhausted(platform) is True
        assert manager.consume_cycle(platform) is False
