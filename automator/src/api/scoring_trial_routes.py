"""Scoring trial API endpoints for the local scoring trial dashboard.

Provides endpoints for viewing scoring comparisons, computing metrics,
checking model status, triggering retraining, and updating configuration.
All endpoints require bearer token authentication.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import verify_token
from src.db.config_repo import get_config, set_config
from src.db.database import get_session
from src.db.models import JobRecord, ScoringComparison
import src.scoring.local_scorer as local_scorer_module
from src.scoring.local_scorer import (
    InsufficientDataError,
    _load_training_data,
)
from src.scoring.metrics import compute_metrics

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Pydantic Response Schemas
# ---------------------------------------------------------------------------


class ScoringComparisonResponse(BaseModel):
    """A single scoring comparison record with job metadata."""

    id: int
    job_id: str
    job_title: str | None
    company: str | None
    local_score: int | None
    claude_score: int
    score_difference: int | None
    would_skip: bool
    scored_at: str


class PaginatedComparisons(BaseModel):
    """Paginated list of scoring comparison records."""

    items: list[ScoringComparisonResponse]
    total: int
    page: int
    page_size: int


class TrialMetricsResponse(BaseModel):
    """Aggregate accuracy metrics for the local scoring trial."""

    total_compared: int
    mean_absolute_error: float
    recall_at_cutoff: float
    false_positive_count: int
    cutoff: int


class ScoringTrialStatus(BaseModel):
    """Current state of the local scoring system."""

    model_trained: bool
    training_samples_count: int
    model_version: str | None
    shadow_mode_active: bool
    total_predictions_made: int


class RetrainResponse(BaseModel):
    """Result of a retrain operation."""

    success: bool
    sample_count: int
    model_version: str
    duration_seconds: float


class ScoringTrialConfigUpdate(BaseModel):
    """Request body for updating scoring trial configuration."""

    shadow_mode_enabled: bool | None = None
    cutoff: int | None = None


class ScoringTrialConfig(BaseModel):
    """Current scoring trial configuration."""

    shadow_mode_enabled: bool
    cutoff: int


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/scoring-trial", tags=["scoring-trial"])


# ---------------------------------------------------------------------------
# GET /scoring-trial/comparisons
# ---------------------------------------------------------------------------


@router.get("/comparisons")
async def get_comparisons(
    date_from: str | None = None,
    date_to: str | None = None,
    min_claude_score: int | None = None,
    page: int = 1,
    page_size: int = 50,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> PaginatedComparisons:
    """Return a paginated list of scoring comparison records.

    Joins with job_records to include job_title and company. Supports
    optional filtering by date range and minimum Claude score.
    """
    logger.info(
        "get_scoring_comparisons",
        date_from=date_from,
        date_to=date_to,
        min_claude_score=min_claude_score,
        page=page,
        page_size=page_size,
    )

    # Build filtered query with join to job_records for title/company
    query = select(ScoringComparison, JobRecord.job_title, JobRecord.company).outerjoin(
        JobRecord, ScoringComparison.job_id == JobRecord.id
    )

    if date_from is not None:
        query = query.where(ScoringComparison.scored_at >= date_from)
    if date_to is not None:
        query = query.where(ScoringComparison.scored_at <= date_to)
    if min_claude_score is not None:
        query = query.where(ScoringComparison.claude_score >= min_claude_score)

    # Count total matching records
    count_query = select(func.count(ScoringComparison.id))
    if date_from is not None:
        count_query = count_query.where(ScoringComparison.scored_at >= date_from)
    if date_to is not None:
        count_query = count_query.where(ScoringComparison.scored_at <= date_to)
    if min_claude_score is not None:
        count_query = count_query.where(ScoringComparison.claude_score >= min_claude_score)

    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # Paginate
    offset = (page - 1) * page_size
    query = query.order_by(ScoringComparison.scored_at.desc()).offset(offset).limit(page_size)

    result = await session.execute(query)
    rows = result.all()

    items: list[ScoringComparisonResponse] = []
    for row in rows:
        comparison = row[0]
        job_title = row[1]
        company = row[2]
        items.append(
            ScoringComparisonResponse(
                id=comparison.id,
                job_id=comparison.job_id,
                job_title=job_title,
                company=company,
                local_score=comparison.local_score,
                claude_score=comparison.claude_score,
                score_difference=comparison.score_difference,
                would_skip=bool(comparison.would_skip),
                scored_at=comparison.scored_at,
            )
        )

    return PaginatedComparisons(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /scoring-trial/metrics
# ---------------------------------------------------------------------------


@router.get("/metrics")
async def get_metrics(
    cutoff: int = 40,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> TrialMetricsResponse:
    """Return aggregate accuracy metrics for the local scoring trial.

    Accepts an optional cutoff parameter (default 40) for recall and
    false positive calculations.
    """
    logger.info("get_scoring_metrics", cutoff=cutoff)

    # Get all comparisons with non-null local_score for metrics computation
    query = select(ScoringComparison).where(ScoringComparison.local_score.isnot(None))
    result = await session.execute(query)
    comparisons = list(result.scalars().all())

    metrics = compute_metrics(comparisons, cutoff=cutoff)

    return TrialMetricsResponse(
        total_compared=metrics.total_compared,
        mean_absolute_error=metrics.mean_absolute_error,
        recall_at_cutoff=metrics.recall_at_cutoff,
        false_positive_count=metrics.false_positive_count,
        cutoff=metrics.cutoff,
    )


# ---------------------------------------------------------------------------
# GET /scoring-trial/status
# ---------------------------------------------------------------------------


@router.get("/status")
async def get_status(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> ScoringTrialStatus:
    """Return the current state of the local scoring system.

    Includes model readiness, training sample count, version, shadow mode
    state, and total predictions made (comparisons with non-null local_score).
    """
    logger.info("get_scoring_trial_status")

    scorer = local_scorer_module._active_scorer
    model_trained = scorer.is_ready if scorer else False
    model_version = scorer.model_version if scorer else None

    # Training samples count from model data
    training_samples_count = 0
    if scorer and scorer.is_ready and scorer._model_data:
        training_samples_count = scorer._model_data.get("sample_count", 0)

    # Shadow mode from config
    shadow_mode_raw = await get_config(session, "shadow_mode_enabled")
    shadow_mode_active = bool(shadow_mode_raw) if shadow_mode_raw is not None else False

    # Total predictions made = count of comparisons where local_score is not null
    predictions_query = select(func.count(ScoringComparison.id)).where(
        ScoringComparison.local_score.isnot(None)
    )
    predictions_result = await session.execute(predictions_query)
    total_predictions_made = predictions_result.scalar_one()

    return ScoringTrialStatus(
        model_trained=model_trained,
        training_samples_count=training_samples_count,
        model_version=model_version,
        shadow_mode_active=shadow_mode_active,
        total_predictions_made=total_predictions_made,
    )


# ---------------------------------------------------------------------------
# POST /scoring-trial/retrain
# ---------------------------------------------------------------------------


@router.post("/retrain")
async def trigger_retrain(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> RetrainResponse:
    """Trigger a full retraining of the local scorer using all eligible records.

    Loads training data from the database, constructs the profile text from
    SKILLS_AND_CONTEXT.md and the goals_profile supplementary_context, then
    calls retrain_atomic on the active scorer.

    Returns HTTP 500 if insufficient data or retraining fails.
    """
    logger.info("trigger_scoring_retrain")

    scorer = local_scorer_module._active_scorer
    if scorer is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Local scorer not initialized. Service may need restart.",
        )

    # Load training data from database
    descriptions, scores = await _load_training_data(session)

    # Build profile text from SKILLS_AND_CONTEXT.md + supplementary_context
    profile_text = await _build_profile_text(session)

    try:
        result = await scorer.retrain_atomic(
            job_descriptions=descriptions,
            fit_scores=scores,
            profile_text=profile_text,
        )
    except InsufficientDataError as exc:
        logger.warning("retrain_insufficient_data", sample_count=exc.sample_count)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Insufficient training data: {exc.sample_count} samples (minimum 50 required)",
        )
    except Exception as exc:
        logger.error("retrain_failed", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Retraining failed: {exc}",
        )

    return RetrainResponse(
        success=True,
        sample_count=result.sample_count,
        model_version=result.version,
        duration_seconds=result.duration_seconds,
    )


# ---------------------------------------------------------------------------
# PUT /scoring-trial/config
# ---------------------------------------------------------------------------


@router.put("/config")
async def update_config(
    body: ScoringTrialConfigUpdate,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(verify_token),
) -> ScoringTrialConfig:
    """Update shadow_mode_enabled and/or cutoff configuration.

    Returns HTTP 409 if attempting to enable shadow mode without a trained model.
    """
    logger.info(
        "update_scoring_trial_config",
        shadow_mode_enabled=body.shadow_mode_enabled,
        cutoff=body.cutoff,
    )

    # If enabling shadow mode, verify model is trained
    if body.shadow_mode_enabled is True:
        scorer = local_scorer_module._active_scorer
        if scorer is None or not scorer.is_ready:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot enable shadow mode: no trained model available. "
                "Train the model first via POST /scoring-trial/retrain.",
            )

    # Apply updates
    if body.shadow_mode_enabled is not None:
        await set_config(session, "shadow_mode_enabled", body.shadow_mode_enabled)

    if body.cutoff is not None:
        await set_config(session, "local_score_cutoff", body.cutoff)

    # Read back current state
    shadow_enabled_raw = await get_config(session, "shadow_mode_enabled")
    shadow_enabled = bool(shadow_enabled_raw) if shadow_enabled_raw is not None else False

    cutoff_raw = await get_config(session, "local_score_cutoff")
    cutoff = int(cutoff_raw) if cutoff_raw is not None else 40

    return ScoringTrialConfig(
        shadow_mode_enabled=shadow_enabled,
        cutoff=cutoff,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _build_profile_text(session: AsyncSession) -> str:
    """Build the profile text for training from SKILLS_AND_CONTEXT.md and goals_profile.

    Concatenates the contents of the SKILLS_AND_CONTEXT.md file with the
    supplementary_context from the goals_profile config.
    """
    parts: list[str] = []

    # Load SKILLS_AND_CONTEXT.md from the project root
    skills_path = Path("SKILLS_AND_CONTEXT.md")
    if skills_path.exists():
        parts.append(skills_path.read_text(encoding="utf-8"))

    # Load supplementary_context from goals_profile config
    goals_profile = await get_config(session, "goals_profile")
    if goals_profile and isinstance(goals_profile, dict):
        supplementary = goals_profile.get("supplementary_context")
        if supplementary:
            parts.append(supplementary)

    return "\n\n".join(parts) if parts else ""
