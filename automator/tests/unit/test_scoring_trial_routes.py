"""Unit tests for scoring trial API endpoints.

Tests pagination on /comparisons, metrics with few comparisons,
retrain with insufficient data, and config toggle without trained model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.scoring_trial_routes import router
from src.db.database import get_session
from src.db.models import Base, JobRecord, ScoringComparison

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    """Create a FastAPI app with scoring trial routes and overridden dependencies."""
    from src.api.auth import verify_token

    test_app = FastAPI()
    test_app.include_router(router)

    # Override auth to be a no-op for testing
    async def _no_auth() -> None:
        pass

    # Override get_session to return our test session
    async def _get_test_session():
        yield db_session

    test_app.dependency_overrides[verify_token] = _no_auth
    test_app.dependency_overrides[get_session] = _get_test_session

    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job_record(job_id: str, title: str = "Engineer", company: str = "Acme") -> JobRecord:
    """Create a minimal JobRecord for FK satisfaction."""
    now = datetime.now(UTC).isoformat()
    return JobRecord(
        id=job_id,
        job_title=title,
        company=company,
        linkedin_url=f"https://linkedin.com/jobs/{job_id}",
        apply_type="easy_apply",
        status="scored",
        discovered_at=now,
        updated_at=now,
    )


def _make_comparison(
    job_id: str,
    local_score: int | None,
    claude_score: int,
    scored_at: str | None = None,
) -> ScoringComparison:
    """Create a ScoringComparison record."""
    now = scored_at or datetime.now(UTC).isoformat()
    score_diff = (claude_score - local_score) if local_score is not None else None
    would_skip = 1 if (local_score is not None and local_score < 40) else 0
    return ScoringComparison(
        job_id=job_id,
        local_score=local_score,
        claude_score=claude_score,
        score_difference=score_diff,
        would_skip=would_skip,
        model_version="v1_100samples",
        scored_at=now,
    )


# ---------------------------------------------------------------------------
# Test: Pagination on /comparisons
# ---------------------------------------------------------------------------


class TestComparisonsPagination:
    """Tests for GET /scoring-trial/comparisons pagination math."""

    @pytest.mark.asyncio
    async def test_comparisons_pagination(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Insert N records, request page 1 with page_size=5, verify items and total."""
        # Insert 12 job records and corresponding comparisons
        for i in range(1, 13):
            job = _make_job_record(f"job_{i:03d}", title=f"Role {i}", company=f"Co {i}")
            db_session.add(job)
        await db_session.flush()

        for i in range(1, 13):
            comparison = _make_comparison(
                job_id=f"job_{i:03d}",
                local_score=50 + i,
                claude_score=60 + i,
                scored_at=f"2024-06-{i:02d}T12:00:00Z",
            )
            db_session.add(comparison)
        await db_session.commit()

        # Request page 1 with page_size=5
        resp = await client.get("/scoring-trial/comparisons", params={"page": 1, "page_size": 5})
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 12
        assert data["page"] == 1
        assert data["page_size"] == 5
        assert len(data["items"]) == 5

    @pytest.mark.asyncio
    async def test_comparisons_pagination_last_page(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Last page returns remaining items when total is not evenly divisible."""
        # Insert 7 job records and comparisons
        for i in range(1, 8):
            job = _make_job_record(f"job_{i:03d}")
            db_session.add(job)
        await db_session.flush()

        for i in range(1, 8):
            comparison = _make_comparison(
                job_id=f"job_{i:03d}",
                local_score=45,
                claude_score=70,
                scored_at=f"2024-06-{i:02d}T12:00:00Z",
            )
            db_session.add(comparison)
        await db_session.commit()

        # Request page 2 with page_size=5 → should have 2 items
        resp = await client.get("/scoring-trial/comparisons", params={"page": 2, "page_size": 5})
        assert resp.status_code == 200

        data = resp.json()
        assert data["total"] == 7
        assert data["page"] == 2
        assert data["page_size"] == 5
        assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# Test: /metrics response with few comparisons
# ---------------------------------------------------------------------------


class TestMetricsWithFewComparisons:
    """Tests for GET /scoring-trial/metrics when < 10 comparisons exist."""

    @pytest.mark.asyncio
    async def test_metrics_response_with_few_comparisons(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When < 10 comparisons exist, endpoint still returns valid metrics response."""
        # Insert 5 comparisons (less than 10)
        for i in range(1, 6):
            job = _make_job_record(f"job_{i:03d}")
            db_session.add(job)
        await db_session.flush()

        for i in range(1, 6):
            comparison = _make_comparison(
                job_id=f"job_{i:03d}",
                local_score=40 + i * 5,
                claude_score=50 + i * 5,
            )
            db_session.add(comparison)
        await db_session.commit()

        resp = await client.get("/scoring-trial/metrics")
        assert resp.status_code == 200

        data = resp.json()
        # The endpoint returns a valid response with metrics computed
        assert data["total_compared"] == 5
        assert data["total_compared"] < 10
        assert "mean_absolute_error" in data
        assert "recall_at_cutoff" in data
        assert "false_positive_count" in data
        assert data["cutoff"] == 40
        # MAE should be 10 (each pair differs by 10)
        assert data["mean_absolute_error"] == 10.0

    @pytest.mark.asyncio
    async def test_metrics_response_with_zero_comparisons(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When zero comparisons exist, endpoint returns zeroed metrics."""
        resp = await client.get("/scoring-trial/metrics")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total_compared"] == 0
        assert data["mean_absolute_error"] == 0.0
        assert data["recall_at_cutoff"] == 1.0
        assert data["false_positive_count"] == 0


# ---------------------------------------------------------------------------
# Test: /retrain returns error when insufficient data
# ---------------------------------------------------------------------------


class TestRetrainInsufficientData:
    """Tests for POST /scoring-trial/retrain with insufficient training data."""

    @pytest.mark.asyncio
    async def test_retrain_insufficient_data(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Mock _load_training_data to return < 50 records, verify HTTP 500 with 'insufficient'."""
        # Create a mock scorer that will raise InsufficientDataError
        from src.scoring.local_scorer import InsufficientDataError

        mock_scorer = AsyncMock()
        mock_scorer.retrain_atomic = AsyncMock(
            side_effect=InsufficientDataError(sample_count=30)
        )

        with (
            patch(
                "src.api.scoring_trial_routes._load_training_data",
                new_callable=AsyncMock,
                return_value=(["desc"] * 30, [50] * 30),
            ),
            patch("src.api.scoring_trial_routes._active_scorer", mock_scorer),
            patch(
                "src.api.scoring_trial_routes._build_profile_text",
                new_callable=AsyncMock,
                return_value="profile text",
            ),
        ):
            resp = await client.post("/scoring-trial/retrain")

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "insufficient" in detail.lower() or "Insufficient" in detail

    @pytest.mark.asyncio
    async def test_retrain_scorer_not_initialized(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When _active_scorer is None, retrain returns HTTP 500."""
        with patch("src.api.scoring_trial_routes._active_scorer", None):
            resp = await client.post("/scoring-trial/retrain")

        assert resp.status_code == 500
        assert "not initialized" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test: /config returns 409 when enabling shadow mode without trained model
# ---------------------------------------------------------------------------


class TestConfigEnableShadowModeWithoutModel:
    """Tests for PUT /scoring-trial/config shadow mode validation."""

    @pytest.mark.asyncio
    async def test_config_enable_shadow_mode_without_model(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Mock _active_scorer as None, verify HTTP 409 when enabling shadow mode."""
        with patch("src.api.scoring_trial_routes._active_scorer", None):
            resp = await client.put(
                "/scoring-trial/config",
                json={"shadow_mode_enabled": True},
            )

        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "shadow mode" in detail.lower() or "trained model" in detail.lower()

    @pytest.mark.asyncio
    async def test_config_enable_shadow_mode_scorer_not_ready(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """When scorer exists but is_ready is False, returns HTTP 409."""
        mock_scorer = AsyncMock()
        mock_scorer.is_ready = False

        with patch("src.api.scoring_trial_routes._active_scorer", mock_scorer):
            resp = await client.put(
                "/scoring-trial/config",
                json={"shadow_mode_enabled": True},
            )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_config_disable_shadow_mode_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Disabling shadow mode does not require a trained model."""
        with patch("src.api.scoring_trial_routes._active_scorer", None):
            resp = await client.put(
                "/scoring-trial/config",
                json={"shadow_mode_enabled": False},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["shadow_mode_enabled"] is False
