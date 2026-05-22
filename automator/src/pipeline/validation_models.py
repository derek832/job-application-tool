"""Validation data models and state tracking for visual apply validation.

Defines the dataclasses and evaluation logic used by the agent-driven
validation workflow to track platform state, evaluate pass criteria,
and generate final reports.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from src.agents.visual_form_filler import FillResult

__all__ = [
    "FillResult",
    "PlatformReport",
    "PlatformValidationState",
    "ValidationReport",
    "ValidationSession",
    "generate_report",
    "meets_pass_criteria",
    "should_retest_passing_platforms",
]


@dataclass
class PlatformValidationState:
    """Tracks validation state for a single ATS platform.

    Attributes:
        platform: Platform identifier (greenhouse, lever, workday, icims, bamboohr).
        status: Current validation status (pending, pass, fail, unavailable).
        target_urls_tried: URLs attempted during validation.
        active_url: Current URL being validated.
        fix_cycles_used: Number of fix cycles consumed (0-5).
        fields_filled: Fields filled in last successful run.
        pages_completed: Pages completed in last successful run.
        last_fill_result: Last FillResult serialized as dict.
        last_failure_category: Most recent failure classification.
        patches_applied: Descriptions of each patch applied.
        diagnosed_issues: Root causes identified during diagnosis.
    """

    platform: str
    status: str = "pending"
    target_urls_tried: list[str] = field(default_factory=list)
    active_url: str | None = None
    fix_cycles_used: int = 0
    fields_filled: int = 0
    pages_completed: int = 0
    last_fill_result: dict | None = None
    last_failure_category: str | None = None
    patches_applied: list[str] = field(default_factory=list)
    diagnosed_issues: list[str] = field(default_factory=list)


@dataclass
class ValidationSession:
    """Tracks the overall validation session across all platforms.

    Attributes:
        platforms: Map of platform name to its validation state.
        overall_status: Session status (in_progress, complete).
        modified_files: Files patched during validation.
        start_time: ISO 8601 timestamp when session started.
        end_time: ISO 8601 timestamp when session ended, or None if in progress.
    """

    platforms: dict[str, PlatformValidationState] = field(default_factory=dict)
    overall_status: str = "in_progress"
    modified_files: list[str] = field(default_factory=list)
    start_time: str = ""
    end_time: str | None = None


@dataclass
class PlatformReport:
    """Summary report for a single platform's validation outcome.

    Attributes:
        platform: Platform identifier.
        status: Final status (pass or fail).
        target_url: URL that achieved pass, or last URL tried.
        fields_filled: Number of fields filled in the passing run.
        fix_cycles_consumed: Total fix cycles used for this platform.
        outstanding_issues: Unresolved issues for failing platforms.
    """

    platform: str
    status: str
    target_url: str | None
    fields_filled: int
    fix_cycles_consumed: int
    outstanding_issues: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Final report summarizing the entire validation session.

    Attributes:
        overall_pass: True iff all 5 platforms achieved pass status.
        platforms: Per-platform report entries.
        total_fix_cycles: Sum of fix cycles across all platforms.
        modified_files: All files modified during validation.
        duration_minutes: Total validation duration in minutes.
    """

    overall_pass: bool
    platforms: list[PlatformReport]
    total_fix_cycles: int
    modified_files: list[str]
    duration_minutes: float


def meets_pass_criteria(result: FillResult) -> bool:
    """Evaluate whether a FillResult meets the validation pass criteria.

    A dry-run passes when all three conditions hold:
    - result.ok is True
    - result.fields_filled >= 3
    - result.reason is not "captcha_detected" or "vision_api_error"

    Args:
        result: The FillResult from a dry-run invocation.

    Returns:
        True if the result meets all pass criteria, False otherwise.
    """
    return (
        result.ok is True
        and result.fields_filled >= 3
        and result.reason not in ("captcha_detected", "vision_api_error")
    )


def should_retest_passing_platforms(modified_files: list[str]) -> bool:
    """Determine if passing platforms need re-testing after a code patch.

    If modified files include shared code paths (visual_form_filler.py or
    vision_agent.py), previously passing platforms may regress and should
    be re-tested.

    Args:
        modified_files: List of file paths modified by a patch.

    Returns:
        True if passing platforms should be re-tested.
    """
    shared_filenames = {"visual_form_filler.py", "vision_agent.py"}
    return any(os.path.basename(f) in shared_filenames for f in modified_files)


def generate_report(session: ValidationSession) -> ValidationReport:
    """Generate a final validation report from the session state.

    Sets overall_pass to True iff all 5 platforms have status "pass".
    Includes an entry for every platform with status, target URL,
    fields_filled, fix_cycles consumed, and outstanding issues for
    failing platforms.

    Args:
        session: The completed ValidationSession with platform states.

    Returns:
        A ValidationReport summarizing outcomes across all platforms.
    """
    from datetime import datetime

    platform_reports: list[PlatformReport] = []
    total_fix_cycles = 0

    for platform_name, state in session.platforms.items():
        report_status = "pass" if state.status == "pass" else "fail"
        outstanding = list(state.diagnosed_issues) if state.status != "pass" else []
        platform_reports.append(
            PlatformReport(
                platform=platform_name,
                status=report_status,
                target_url=state.active_url,
                fields_filled=state.fields_filled,
                fix_cycles_consumed=state.fix_cycles_used,
                outstanding_issues=outstanding,
            )
        )
        total_fix_cycles += state.fix_cycles_used

    # overall_pass is True only when all 5 platforms are present and pass
    all_pass = all(state.status == "pass" for state in session.platforms.values())
    overall_pass = all_pass and len(session.platforms) == 5

    # Calculate duration from ISO 8601 timestamps
    duration_minutes = 0.0
    if session.start_time and session.end_time:
        try:
            start = datetime.fromisoformat(session.start_time)
            end = datetime.fromisoformat(session.end_time)
            duration_minutes = (end - start).total_seconds() / 60.0
        except (ValueError, TypeError):
            duration_minutes = 0.0

    return ValidationReport(
        overall_pass=overall_pass,
        platforms=platform_reports,
        total_fix_cycles=total_fix_cycles,
        modified_files=list(session.modified_files),
        duration_minutes=duration_minutes,
    )
