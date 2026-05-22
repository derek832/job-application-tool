"""
Escalation management API routes for the Human-in-the-Loop system.

Provides endpoints for listing, retrieving, submitting, and skipping
escalation records. All endpoints require Bearer token authentication.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 7.3, 7.4
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    EscalationListResponse,
    EscalationRecordOut,
    EscalationSubmitRequest,
)
from src.api.system_routes import verify_token
from src.db.database import get_session
from src.db.models import EscalationRecord, JobRecord

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/escalations", tags=["escalations"])


# ---------------------------------------------------------------------------
# Helper: build EscalationRecordOut with denormalized job fields
# ---------------------------------------------------------------------------


def _build_escalation_out(
    record: EscalationRecord,
    job: JobRecord | None = None,
) -> EscalationRecordOut:
    """Construct an EscalationRecordOut from a DB record with job denormalization.

    Args:
        record: The escalation record from the database.
        job: Optional associated job record for denormalized fields.

    Returns:
        Pydantic model ready for API serialization.
    """
    data = {
        "id": record.id,
        "job_id": record.job_id,
        "tier": record.tier,
        "form_state_snapshot": record.form_state_snapshot,
        "draft_answers": record.draft_answers,
        "timeout_deadline": record.timeout_deadline,
        "freshness_tier": record.freshness_tier,
        "status": record.status,
        "resolution_method": record.resolution_method,
        "created_at": record.created_at,
        "resolved_at": record.resolved_at,
        "job_title": job.job_title if job else None,
        "company": job.company if job else None,
        "fit_score": job.fit_score if job else None,
    }
    return EscalationRecordOut.model_validate(data)


# ---------------------------------------------------------------------------
# GET /escalations
# ---------------------------------------------------------------------------


@router.get("", response_model=EscalationListResponse)
async def list_escalations(
    include_resolved: bool = Query(
        default=False,
        description="Include resolved/non-pending escalations in the response",
    ),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> EscalationListResponse:
    """Return a list of escalation records, pending by default.

    Results are sorted by timeout_deadline ascending (most urgent first),
    with NULL deadlines sorted last. Each record includes denormalized job
    info (job_title, company, fit_score).

    Args:
        include_resolved: If True, include all statuses. If False (default),
            only return records with status="pending".
        session: Active async database session.

    Returns:
        EscalationListResponse with the list of escalation records and total count.

    Validates: Requirements 6.1, 7.3, 7.4
    """
    logger.info("list_escalations_requested", include_resolved=include_resolved)

    stmt = select(EscalationRecord)

    if not include_resolved:
        stmt = stmt.where(EscalationRecord.status == "pending")

    # Sort by timeout_deadline ascending, NULLs last.
    # SQLite sorts NULLs first by default with ASC, so we use a secondary
    # sort key: timeout_deadline IS NULL evaluates to 0 (False) for non-NULL
    # and 1 (True) for NULL, pushing NULLs to the end.
    stmt = stmt.order_by(
        EscalationRecord.timeout_deadline.is_(None),  # 0 before 1 -> NULLs last
        EscalationRecord.timeout_deadline.asc(),
    )

    result = await session.execute(stmt)
    records = list(result.scalars().all())

    # Denormalize job info for each record
    escalation_outs: list[EscalationRecordOut] = []
    for record in records:
        # Fetch the related job record
        job_stmt = select(JobRecord).where(JobRecord.id == record.job_id)
        job_result = await session.execute(job_stmt)
        job = job_result.scalars().first()

        escalation_outs.append(_build_escalation_out(record, job))

    logger.info(
        "list_escalations_response",
        total=len(escalation_outs),
        include_resolved=include_resolved,
    )

    return EscalationListResponse(
        escalations=escalation_outs,
        total=len(escalation_outs),
    )


# ---------------------------------------------------------------------------
# GET /escalations/{escalation_id}
# ---------------------------------------------------------------------------


@router.get("/{escalation_id}", response_model=EscalationRecordOut)
async def get_escalation(
    escalation_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> EscalationRecordOut:
    """Retrieve a single escalation record by ID with full form state and draft answers.

    Args:
        escalation_id: UUID of the escalation record.
        session: Active async database session.

    Returns:
        The full escalation record including parsed form_state_snapshot
        and draft_answers, with denormalized job info.

    Raises:
        HTTPException: 404 if no escalation record exists with the given ID.

    Validates: Requirements 6.2, 7.3
    """
    logger.info("get_escalation_requested", escalation_id=escalation_id)

    stmt = select(EscalationRecord).where(EscalationRecord.id == escalation_id)
    result = await session.execute(stmt)
    record = result.scalars().first()

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Escalation record not found: {escalation_id}",
        )

    # Fetch the related job record for denormalization
    job_stmt = select(JobRecord).where(JobRecord.id == record.job_id)
    job_result = await session.execute(job_stmt)
    job = job_result.scalars().first()

    return _build_escalation_out(record, job)


# ---------------------------------------------------------------------------
# POST /escalations/{escalation_id}/submit
# ---------------------------------------------------------------------------


@router.post("/{escalation_id}/submit", response_model=EscalationRecordOut)
async def submit_escalation(
    escalation_id: str,
    body: EscalationSubmitRequest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> EscalationRecordOut:
    """Submit an escalation with edited answers, resuming automation.

    Accepts the user's edited answers and resolves the escalation as
    "resolved" with resolution_method="user_submit". The edited answers
    are stored and will be used to resume the application.

    Args:
        escalation_id: UUID of the escalation record to resolve.
        body: Request body containing edited_answers list.
        session: Active async database session.

    Returns:
        The updated escalation record.

    Raises:
        HTTPException: 404 if escalation not found.
        HTTPException: 409 if escalation already resolved.

    Validates: Requirements 6.3, 6.5
    """
    logger.info(
        "escalation_submit_requested",
        escalation_id=escalation_id,
        edited_answers_count=len(body.edited_answers),
    )

    from src.pipeline.escalation_engine import resolve_escalation

    try:
        record = await resolve_escalation(
            session=session,
            escalation_id=escalation_id,
            resolution="resolved",
            edited_answers=body.edited_answers,
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        # Already resolved
        raise HTTPException(status_code=409, detail=error_msg)

    # Fetch job for denormalization
    job_stmt = select(JobRecord).where(JobRecord.id == record.job_id)
    job_result = await session.execute(job_stmt)
    job = job_result.scalars().first()

    return _build_escalation_out(record, job)


# ---------------------------------------------------------------------------
# POST /escalations/{escalation_id}/skip
# ---------------------------------------------------------------------------


@router.post("/{escalation_id}/skip", response_model=EscalationRecordOut)
async def skip_escalation(
    escalation_id: str,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> EscalationRecordOut:
    """Skip an escalation, cancelling the application.

    Resolves the escalation as "skipped" with resolution_method="user_skip"
    and transitions the associated job to status="skipped".

    Args:
        escalation_id: UUID of the escalation record to skip.
        session: Active async database session.

    Returns:
        The updated escalation record.

    Raises:
        HTTPException: 404 if escalation not found.
        HTTPException: 409 if escalation already resolved.

    Validates: Requirements 6.4, 6.5
    """
    logger.info("escalation_skip_requested", escalation_id=escalation_id)

    from src.pipeline.escalation_engine import resolve_escalation

    try:
        record = await resolve_escalation(
            session=session,
            escalation_id=escalation_id,
            resolution="skipped",
        )
    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        # Already resolved
        raise HTTPException(status_code=409, detail=error_msg)

    # Fetch job for denormalization
    job_stmt = select(JobRecord).where(JobRecord.id == record.job_id)
    job_result = await session.execute(job_stmt)
    job = job_result.scalars().first()

    return _build_escalation_out(record, job)
