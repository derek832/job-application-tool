"""
Property-based tests for Resume Error Handling.

Uses Hypothesis to verify that for any escalation where the resume process
encounters an error (page load failure, form structure mismatch, navigation
failure, or submission error), the escalation is marked status="expired" with
resolution_method="form_expired", resolved_at is non-null, and the resume
result indicates failure (ok=False).

Properties tested:
- Property 15: Resume Error Handling

Feature: human-in-the-loop-escalation, Property 15: Resume Error Handling
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base, EscalationRecord, JobRecord
from src.pipeline.escalation_resume import ResumeResult, resume_from_escalation


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Error types that can occur during resume
error_type_strategy = st.sampled_from([
    "navigation_timeout",
    "navigation_connection_refused",
    "page_load_http_error",
    "structure_mismatch",
    "fill_failed",
    "submission_failed",
    "unexpected_exception",
])

# Resolution methods that trigger _resume_with_answers (the error-prone path)
resolution_method_strategy = st.sampled_from(["user_submit", "auto_submit"])

# Generate form state snapshots with valid external URLs
form_state_strategy = st.fixed_dictionaries(
    {
        "external_url": st.from_regex(
            r"https://[a-z]+\.(greenhouse|lever|workday)\.(io|com)/jobs/[0-9]+",
            fullmatch=True,
        ),
        "fields": st.lists(
            st.fixed_dictionaries(
                {
                    "field_id": st.text(
                        alphabet=st.characters(whitelist_categories=("L", "N")),
                        min_size=1,
                        max_size=20,
                    ),
                    "label": st.text(min_size=1, max_size=50),
                    "value": st.text(max_size=100),
                    "type": st.sampled_from(["text", "textarea", "select"]),
                    "selector": st.from_regex(r"#[a-z_]+[0-9]*", fullmatch=True),
                }
            ),
            min_size=1,
            max_size=5,
        ),
        "page_title": st.text(min_size=1, max_size=100),
    }
)

# Generate draft answers
draft_answers_strategy = st.lists(
    st.fixed_dictionaries(
        {
            "field_id": st.text(
                alphabet=st.characters(whitelist_categories=("L", "N")),
                min_size=1,
                max_size=20,
            ),
            "question_text": st.text(min_size=5, max_size=100),
            "draft_answer": st.text(min_size=10, max_size=200),
            "edited_answer": st.one_of(st.none(), st.text(min_size=10, max_size=200)),
        }
    ),
    min_size=1,
    max_size=3,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_mock_page_for_error(error_type: str) -> MagicMock:
    """Create a mock Playwright Page that simulates a specific error type.

    Args:
        error_type: The type of error to simulate.

    Returns:
        A MagicMock configured to raise the appropriate error.
    """
    page = MagicMock()

    if error_type == "navigation_timeout":
        # page.goto raises a timeout error
        page.goto = AsyncMock(side_effect=TimeoutError("Navigation timeout after 30000ms"))

    elif error_type == "navigation_connection_refused":
        # page.goto raises a connection error
        page.goto = AsyncMock(
            side_effect=ConnectionError("net::ERR_CONNECTION_REFUSED")
        )

    elif error_type == "page_load_http_error":
        # page.goto returns a response with HTTP 404/500
        mock_response = MagicMock()
        mock_response.status = 404
        page.goto = AsyncMock(return_value=mock_response)

    elif error_type == "structure_mismatch":
        # Navigation succeeds but form structure doesn't match
        mock_response = MagicMock()
        mock_response.status = 200
        page.goto = AsyncMock(return_value=mock_response)
        # Return empty fields list — no matching selectors
        page.evaluate = AsyncMock(return_value=[])

    elif error_type == "fill_failed":
        # Navigation and structure check pass, but filling fails
        mock_response = MagicMock()
        mock_response.status = 200
        page.goto = AsyncMock(return_value=mock_response)
        # Structure check passes (return fields matching snapshot)
        page.evaluate = AsyncMock(side_effect=Exception("Element detached from DOM"))

    elif error_type == "submission_failed":
        # Navigation, structure, and fill pass, but submission fails
        mock_response = MagicMock()
        mock_response.status = 200
        page.goto = AsyncMock(return_value=mock_response)
        # We'll need to patch _submit_form to raise
        page.evaluate = AsyncMock(return_value=[])

    elif error_type == "unexpected_exception":
        # page.goto raises an unexpected error
        page.goto = AsyncMock(
            side_effect=RuntimeError("Browser context was destroyed")
        )

    return page


async def _run_resume_error_test(
    error_type: str,
    resolution_method: str,
    form_state: dict,
    draft_answers: list[dict],
) -> tuple[str, str | None, str | None, bool, str]:
    """Create an in-memory DB, insert a job + resolved escalation, attempt resume.

    Returns:
        Tuple of (escalation_status, resolution_method_field, resolved_at,
                  result_ok, job_status)
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    now = datetime.now(tz=UTC)
    job_id = f"job-resume-err-{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as session:
        # Create a job record in "applying" status
        job = JobRecord(
            id=job_id,
            job_title="Software Engineer",
            company="TestCorp",
            location="Remote",
            linkedin_url=f"https://www.linkedin.com/jobs/view/{job_id}",
            apply_type="external_apply",
            status="applying",
            fit_score=90,
            discovered_at=(now - timedelta(hours=2)).isoformat(),
            updated_at=now.isoformat(),
        )
        session.add(job)
        await session.flush()

        # Create an escalation record (resolved, ready for resume)
        escalation_id = str(uuid.uuid4())
        escalation = EscalationRecord(
            id=escalation_id,
            job_id=job_id,
            tier="human_review",
            form_state_snapshot=json.dumps(form_state),
            draft_answers=json.dumps(draft_answers),
            timeout_deadline=(now + timedelta(minutes=45)).isoformat(),
            freshness_tier="fresh",
            status="resolved",
            resolution_method=resolution_method,
            created_at=(now - timedelta(minutes=30)).isoformat(),
            resolved_at=now.isoformat(),
        )
        session.add(escalation)
        await session.flush()

        # Create mock page that simulates the error
        mock_page = _create_mock_page_for_error(error_type)

        # For structure_mismatch: we need the evaluate to return empty fields
        # so the 50% threshold check fails
        if error_type == "structure_mismatch":
            # Return fields that don't match the snapshot selectors
            mock_page.evaluate = AsyncMock(return_value=[
                {"selector": "#nonexistent_field", "label": "Unrelated", "type": "text"}
            ])

        # For submission_failed: patch _submit_form to raise
        if error_type == "submission_failed":
            # Structure check needs to pass — return matching fields
            snapshot_fields = form_state.get("fields", [])
            matching_fields = [
                {"selector": f.get("selector", ""), "label": f.get("label", ""), "type": f.get("type", "text")}
                for f in snapshot_fields
            ]
            mock_page.evaluate = AsyncMock(return_value=matching_fields)
            # Fill succeeds
            mock_page.fill = AsyncMock(return_value=None)
            # query_selector for submit button raises
            mock_page.query_selector = AsyncMock(
                side_effect=Exception("Page crashed during submission")
            )

        # For fill_failed: structure check raises during evaluate
        if error_type == "fill_failed":
            # The evaluate call in _verify_form_structure will raise
            mock_page.evaluate = AsyncMock(
                side_effect=Exception("Element detached from DOM")
            )

        # Run resume_from_escalation
        result = await resume_from_escalation(
            session=session,
            escalation_record=escalation,
            page=mock_page,
        )

        # Refresh escalation to get updated fields
        await session.refresh(escalation)
        await session.refresh(job)

        output = (
            escalation.status,
            escalation.resolution_method,
            escalation.resolved_at,
            result.ok,
            job.status,
        )

    await engine.dispose()
    return output


# ---------------------------------------------------------------------------
# Property 15: Resume Error Handling
# ---------------------------------------------------------------------------


@given(
    error_type=error_type_strategy,
    resolution_method=resolution_method_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answers_strategy,
)
@settings(max_examples=100)
def test_resume_error_sets_escalation_status_expired(
    error_type: str,
    resolution_method: str,
    form_state: dict,
    draft_answers: list[dict],
) -> None:
    """
    For any escalation where the resume process encounters an error,
    the escalation should be marked status="expired".

    **Validates: Requirements 8.3, 8.5**

    Feature: human-in-the-loop-escalation, Property 15: Resume Error Handling
    """
    (
        escalation_status,
        resolution_method_field,
        resolved_at,
        result_ok,
        job_status,
    ) = asyncio.run(
        _run_resume_error_test(
            error_type=error_type,
            resolution_method=resolution_method,
            form_state=form_state,
            draft_answers=draft_answers,
        )
    )

    assert escalation_status == "expired", (
        f"Expected escalation status='expired', got {escalation_status!r} "
        f"(error_type={error_type!r}, resolution_method={resolution_method!r})"
    )


@given(
    error_type=error_type_strategy,
    resolution_method=resolution_method_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answers_strategy,
)
@settings(max_examples=100)
def test_resume_error_sets_resolution_method_form_expired(
    error_type: str,
    resolution_method: str,
    form_state: dict,
    draft_answers: list[dict],
) -> None:
    """
    For any escalation where the resume process encounters an error,
    the resolution_method should be set to "form_expired".

    **Validates: Requirements 8.3, 8.5**

    Feature: human-in-the-loop-escalation, Property 15: Resume Error Handling
    """
    (
        escalation_status,
        resolution_method_field,
        resolved_at,
        result_ok,
        job_status,
    ) = asyncio.run(
        _run_resume_error_test(
            error_type=error_type,
            resolution_method=resolution_method,
            form_state=form_state,
            draft_answers=draft_answers,
        )
    )

    assert resolution_method_field == "form_expired", (
        f"Expected resolution_method='form_expired', got {resolution_method_field!r} "
        f"(error_type={error_type!r}, resolution_method={resolution_method!r})"
    )


@given(
    error_type=error_type_strategy,
    resolution_method=resolution_method_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answers_strategy,
)
@settings(max_examples=100)
def test_resume_error_sets_resolved_at_non_null(
    error_type: str,
    resolution_method: str,
    form_state: dict,
    draft_answers: list[dict],
) -> None:
    """
    For any escalation where the resume process encounters an error,
    the resolved_at timestamp should be non-null.

    **Validates: Requirements 8.3, 8.5**

    Feature: human-in-the-loop-escalation, Property 15: Resume Error Handling
    """
    (
        escalation_status,
        resolution_method_field,
        resolved_at,
        result_ok,
        job_status,
    ) = asyncio.run(
        _run_resume_error_test(
            error_type=error_type,
            resolution_method=resolution_method,
            form_state=form_state,
            draft_answers=draft_answers,
        )
    )

    assert resolved_at is not None, (
        f"Expected resolved_at to be non-null after resume error, "
        f"got None (error_type={error_type!r}, resolution_method={resolution_method!r})"
    )
    # Verify it's a valid ISO 8601 timestamp
    parsed = datetime.fromisoformat(resolved_at)
    assert parsed.tzinfo is not None or "+" in resolved_at or "Z" in resolved_at, (
        f"Expected resolved_at to be a timezone-aware ISO 8601 timestamp, "
        f"got {resolved_at!r}"
    )


@given(
    error_type=error_type_strategy,
    resolution_method=resolution_method_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answers_strategy,
)
@settings(max_examples=100)
def test_resume_error_returns_result_ok_false(
    error_type: str,
    resolution_method: str,
    form_state: dict,
    draft_answers: list[dict],
) -> None:
    """
    For any escalation where the resume process encounters an error,
    the resume result should indicate failure (ok=False).

    **Validates: Requirements 8.3, 8.5**

    Feature: human-in-the-loop-escalation, Property 15: Resume Error Handling
    """
    (
        escalation_status,
        resolution_method_field,
        resolved_at,
        result_ok,
        job_status,
    ) = asyncio.run(
        _run_resume_error_test(
            error_type=error_type,
            resolution_method=resolution_method,
            form_state=form_state,
            draft_answers=draft_answers,
        )
    )

    assert result_ok is False, (
        f"Expected result.ok=False after resume error, got {result_ok!r} "
        f"(error_type={error_type!r}, resolution_method={resolution_method!r})"
    )


@given(
    error_type=error_type_strategy,
    resolution_method=resolution_method_strategy,
    form_state=form_state_strategy,
    draft_answers=draft_answers_strategy,
)
@settings(max_examples=100)
def test_resume_error_transitions_job_to_apply_failed(
    error_type: str,
    resolution_method: str,
    form_state: dict,
    draft_answers: list[dict],
) -> None:
    """
    For any escalation where the resume process encounters an error,
    the associated job should transition to status="apply_failed".

    **Validates: Requirements 8.3, 8.5**

    Feature: human-in-the-loop-escalation, Property 15: Resume Error Handling
    """
    (
        escalation_status,
        resolution_method_field,
        resolved_at,
        result_ok,
        job_status,
    ) = asyncio.run(
        _run_resume_error_test(
            error_type=error_type,
            resolution_method=resolution_method,
            form_state=form_state,
            draft_answers=draft_answers,
        )
    )

    assert job_status == "apply_failed", (
        f"Expected job status='apply_failed', got {job_status!r} "
        f"(error_type={error_type!r}, resolution_method={resolution_method!r})"
    )
