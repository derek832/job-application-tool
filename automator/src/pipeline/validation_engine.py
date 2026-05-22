"""Validation engine orchestrating all visual apply validation components.

This module wires together the prerequisite checks, platform ordering,
and dry-run evaluation logic used by the agent-driven validation workflow.
It imports from all validation utility modules and provides a cohesive
interface for the validation loop.

Validates: Requirements 6.1, 7.1, 7.2, 7.3, 7.4
"""

from __future__ import annotations

import subprocess

from src.pipeline.cleanup_utils import remove_diagnostic_markers
from src.pipeline.failure_classifier import classify_failure
from src.pipeline.fix_cycle_manager import FixCycleManager, PatchRetryTracker
from src.pipeline.log_utils import filter_logs_by_url
from src.pipeline.submit_matcher import is_submit_button
from src.pipeline.url_validator import URLReplacementTracker, classify_url_status
from src.pipeline.validation_models import (
    FillResult,
    PlatformValidationState,
    ValidationSession,
    generate_report,
    meets_pass_criteria,
    should_retest_passing_platforms,
)

__all__ = [
    "FillResult",
    "FixCycleManager",
    "PatchRetryTracker",
    "PlatformValidationState",
    "URLReplacementTracker",
    "ValidationSession",
    "check_branch_deployed",
    "check_cdp_accessible",
    "check_docker_healthy",
    "check_user_profile",
    "classify_failure",
    "classify_url_status",
    "evaluate_dry_run",
    "filter_logs_by_url",
    "generate_report",
    "get_platform_order",
    "is_submit_button",
    "meets_pass_criteria",
    "remove_diagnostic_markers",
    "run_prerequisite_checks",
    "should_retest_passing_platforms",
]

# Fixed platform validation order per design document.
_PLATFORM_ORDER: list[str] = [
    "greenhouse",
    "lever",
    "workday",
    "icims",
    "bamboohr",
]


def get_platform_order() -> list[str]:
    """Return the fixed platform validation order.

    Platforms are validated sequentially: Greenhouse → Lever → Workday →
    iCIMS → BambooHR. This provides deterministic progress tracking.

    Returns:
        List of platform identifiers in validation order.
    """
    return list(_PLATFORM_ORDER)


# ---------------------------------------------------------------------------
# Prerequisite checks (Requirement 7)
# ---------------------------------------------------------------------------


def check_docker_healthy() -> tuple[bool, str]:
    """Verify Docker containers are running and healthy.

    Executes ``docker compose ps`` and checks that the automator service
    reports a "healthy" status.

    Returns:
        (True, "") if healthy, (False, description) if not.
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "ps"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout.lower()
        if "healthy" in output:
            return True, ""
        return False, f"Docker automator service is not healthy. Output: {result.stdout.strip()}"
    except FileNotFoundError:
        return False, "docker command not found"
    except subprocess.TimeoutExpired:
        return False, "docker compose ps timed out after 15 seconds"
    except OSError as exc:
        return False, f"Failed to run docker compose ps: {exc}"


def check_cdp_accessible() -> tuple[bool, str]:
    """Verify Chrome CDP endpoint is accessible.

    Executes a curl request to ``http://localhost:9222/json/version`` and
    checks for a valid JSON response within 10 seconds.

    Returns:
        (True, "") if accessible, (False, description) if not.
    """
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", "10", "http://localhost:9222/json/version"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            return True, ""
        return False, f"CDP endpoint did not return valid JSON. Exit code: {result.returncode}"
    except FileNotFoundError:
        return False, "curl command not found"
    except subprocess.TimeoutExpired:
        return False, "CDP accessibility check timed out after 15 seconds"
    except OSError as exc:
        return False, f"Failed to check CDP endpoint: {exc}"


def check_branch_deployed() -> tuple[bool, str]:
    """Verify the visual form filler code is deployed in the container.

    Checks that ``visual_form_filler.py`` exists in the automator container
    via ``docker compose exec``.

    Returns:
        (True, "") if deployed, (False, description) if not.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "automator",
                "ls",
                "src/pipeline/visual_form_filler.py",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True, ""
        return (
            False,
            "visual_form_filler.py not found in automator container. "
            "Ensure feat/visual-form-filling branch is deployed.",
        )
    except FileNotFoundError:
        return False, "docker command not found"
    except subprocess.TimeoutExpired:
        return False, "Branch deployment check timed out after 15 seconds"
    except OSError as exc:
        return False, f"Failed to check branch deployment: {exc}"


def check_user_profile() -> tuple[bool, str]:
    """Verify a complete user profile exists.

    Checks that the user profile contains non-empty name, email, phone,
    and a resume file path that resolves to an existing file.

    Returns:
        (True, "") if profile is complete, (False, description) if not.
    """
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "automator",
                "python",
                "-c",
                (
                    "import json, os; "
                    "from src.db.database import get_user_profile; "
                    "import asyncio; "
                    "p = asyncio.run(get_user_profile()); "
                    "missing = [f for f in ['name','email','phone'] if not getattr(p, f, None)]; "
                    "resume_ok = bool(getattr(p, 'resume_path', None) and "
                    "os.path.exists(getattr(p, 'resume_path', ''))); "
                    "print(json.dumps({'missing': missing, 'resume_ok': resume_ok}))"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return False, f"Failed to query user profile: {result.stderr.strip()}"

        import json

        try:
            data = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return False, f"Invalid profile check output: {result.stdout.strip()}"

        missing = data.get("missing", [])
        resume_ok = data.get("resume_ok", False)

        issues: list[str] = []
        if missing:
            issues.append(f"Missing fields: {', '.join(missing)}")
        if not resume_ok:
            issues.append("Resume file not found or path is empty")

        if issues:
            return False, f"User profile incomplete: {'; '.join(issues)}"
        return True, ""
    except FileNotFoundError:
        return False, "docker command not found"
    except subprocess.TimeoutExpired:
        return False, "User profile check timed out after 15 seconds"
    except OSError as exc:
        return False, f"Failed to check user profile: {exc}"


def run_prerequisite_checks() -> tuple[bool, str]:
    """Run all prerequisite checks before starting validation.

    Checks are run in order: Docker health, CDP accessibility, branch
    deployment, and user profile completeness. Stops at the first failure.

    Returns:
        (True, "") if all checks pass.
        (False, description) if any check fails, describing which check
        failed and the observed state.
    """
    checks = [
        ("Docker health", check_docker_healthy),
        ("CDP accessibility", check_cdp_accessible),
        ("Branch deployment", check_branch_deployed),
        ("User profile", check_user_profile),
    ]

    for check_name, check_fn in checks:
        ok, message = check_fn()
        if not ok:
            return False, f"{check_name} check failed: {message}"

    return True, ""


# ---------------------------------------------------------------------------
# Dry-run evaluation (Requirements 3.1, 3.3, 3.4)
# ---------------------------------------------------------------------------


def evaluate_dry_run(fill_result: FillResult, docker_logs: str, target_url: str) -> dict:
    """Evaluate a dry-run result combining pass criteria, failure classification, and log filtering.

    If the fill_result meets pass criteria, returns a passing evaluation dict.
    Otherwise, classifies the failure and filters relevant logs.

    Args:
        fill_result: The FillResult from the dry-run execution.
        docker_logs: Raw Docker log output as a single string.
        target_url: The target job posting URL being validated.

    Returns:
        A dict with evaluation results:
        - If passing: {"passed": True, "fields_filled": int, "relevant_logs": list[str]}
        - If failing: {"passed": False, "failure_category": str,
                       "relevant_logs": list[str], "fill_result": dict}
    """
    log_lines = docker_logs.splitlines()
    relevant_logs = filter_logs_by_url(log_lines, target_url)

    if meets_pass_criteria(fill_result):
        return {
            "passed": True,
            "fields_filled": fill_result.fields_filled,
            "relevant_logs": relevant_logs,
        }

    failure_category = classify_failure(fill_result, docker_logs)

    return {
        "passed": False,
        "failure_category": failure_category,
        "relevant_logs": relevant_logs,
        "fill_result": {
            "ok": fill_result.ok,
            "fields_filled": fill_result.fields_filled,
            "fields_found": fill_result.fields_found,
            "pages_completed": fill_result.pages_completed,
            "error": fill_result.error,
            "reason": fill_result.reason,
        },
    }
