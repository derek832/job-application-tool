"""Unit tests for Escalation API endpoints.

Focuses on the GET /escalations/{id} detail endpoint (task 10.3).
Also covers the list endpoint for completeness.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.escalation_routes import router
from src.db.database import get_session
from src.db.models import Base, EscalationRecord, JobRecord

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite database and yield a session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def app(db_session: AsyncSession) -> FastAPI:
    """Create a FastAPI app with escalation routes and overridden dependencies."""
    from src.api.system_routes import verify_token

    test_app = FastAPI()
    test_app.include_router(router)

    async def _no_auth() -> None:
        pass

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


def _make_job_record(
    job_id: str = "job-001",
    job_title: str = "Senior Engineer",
    company: str = "Acme Corp",
    fit_score: int = 90,
) -> JobRecord:
    """Create a JobRecord instance for testing."""
    now = datetime.now(UTC).isoformat()
    return JobRecord(
        id=job_id,
        job_title=job_title,
        company=company,
        location="Remote",
        linkedin_url=f"https://linkedin.com/jobs/view/{job_id}",
        external_url="https://boards.greenhouse.io/acme/jobs/123",
        apply_type="external_apply",
        status="applying",
        fit_score=fit_score,
        discovered_at=now,
        updated_at=now,
    )


def _make_escalation_record(
    escalation_id: str = "esc-001",
    job_id: str = "job-001",
    tier: str = "human_review",
    status: str = "pending",
    form_state: dict | None = None,
    draft_answers: list[dict] | None = None,
    timeout_deadline: str | None = "2025-01-15T12:00:00+00:00",
    freshness_tier: str | None = "fresh",
) -> EscalationRecord:
    """Create an EscalationRecord instance for testing."""
    now = datetime.now(UTC).isoformat()

    if form_state is None:
        form_state = {
            "external_url": "https://boards.greenhouse.io/acme/jobs/123",
            "fields": [
                {
                    "field_id": "field_1",
                    "label": "Full Name",
                    "value": "Derek Smith",
                    "type": "text",
                    "selector": "#first_name",
                }
            ],
            "screenshot_path": "/data/screenshots/esc-001.png",
            "page_title": "Apply - Senior Engineer at Acme Corp",
        }

    if draft_answers is None and tier == "human_review":
        draft_answers = [
            {
                "field_id": "field_5",
                "question_text": "Why are you interested in this role?",
                "draft_answer": "I'm drawn to Acme's mission...",
                "edited_answer": None,
            }
        ]

    return EscalationRecord(
        id=escalation_id,
        job_id=job_id,
        tier=tier,
        form_state_snapshot=json.dumps(form_state),
        draft_answers=json.dumps(draft_answers) if draft_answers else None,
        timeout_deadline=timeout_deadline,
        freshness_tier=freshness_tier,
        status=status,
        resolution_method=None,
        created_at=now,
        resolved_at=None,
    )


# ---------------------------------------------------------------------------
# GET /escalations/{id} tests
# ---------------------------------------------------------------------------


class TestGetEscalation:
    """Tests for GET /escalations/{id}."""

    @pytest.mark.asyncio
    async def test_returns_escalation_with_full_details(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /escalations/{id} returns the full escalation record with parsed JSON."""
        job = _make_job_record()
        escalation = _make_escalation_record()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.get("/escalations/esc-001")
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == "esc-001"
        assert data["job_id"] == "job-001"
        assert data["tier"] == "human_review"
        assert data["status"] == "pending"
        assert data["freshness_tier"] == "fresh"
        assert data["timeout_deadline"] == "2025-01-15T12:00:00+00:00"

        # form_state_snapshot should be parsed dict, not a string
        assert isinstance(data["form_state_snapshot"], dict)
        assert data["form_state_snapshot"]["external_url"] == "https://boards.greenhouse.io/acme/jobs/123"
        assert len(data["form_state_snapshot"]["fields"]) == 1

        # draft_answers should be parsed list
        assert isinstance(data["draft_answers"], list)
        assert len(data["draft_answers"]) == 1
        assert data["draft_answers"][0]["question_text"] == "Why are you interested in this role?"

    @pytest.mark.asyncio
    async def test_returns_denormalized_job_info(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /escalations/{id} includes job_title, company, fit_score from job record."""
        job = _make_job_record(job_title="Staff Engineer", company="BigCo", fit_score=95)
        escalation = _make_escalation_record()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.get("/escalations/esc-001")
        assert resp.status_code == 200

        data = resp.json()
        assert data["job_title"] == "Staff Engineer"
        assert data["company"] == "BigCo"
        assert data["fit_score"] == 95

    @pytest.mark.asyncio
    async def test_returns_404_for_nonexistent_id(self, client: AsyncClient) -> None:
        """GET /escalations/{id} returns 404 when escalation doesn't exist."""
        resp = await client.get("/escalations/nonexistent-id")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_returns_captcha_escalation_with_null_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /escalations/{id} handles CAPTCHA tier with null timeout and draft_answers."""
        job = _make_job_record()
        escalation = _make_escalation_record(
            tier="captcha",
            timeout_deadline=None,
            freshness_tier=None,
            draft_answers=None,
        )
        # Override draft_answers to None for captcha
        escalation.draft_answers = None
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.get("/escalations/esc-001")
        assert resp.status_code == 200

        data = resp.json()
        assert data["tier"] == "captcha"
        assert data["timeout_deadline"] is None
        assert data["freshness_tier"] is None
        assert data["draft_answers"] is None

    @pytest.mark.asyncio
    async def test_returns_resolved_escalation(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /escalations/{id} returns resolved escalations (not just pending)."""
        job = _make_job_record()
        escalation = _make_escalation_record(status="resolved")
        escalation.resolution_method = "user_submit"
        escalation.resolved_at = datetime.now(UTC).isoformat()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.get("/escalations/esc-001")
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolution_method"] == "user_submit"
        assert data["resolved_at"] is not None


# ---------------------------------------------------------------------------
# GET /escalations (list) tests — basic coverage
# ---------------------------------------------------------------------------


class TestListEscalations:
    """Tests for GET /escalations."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_records(self, client: AsyncClient) -> None:
        """GET /escalations returns empty list when no escalations exist."""
        resp = await client.get("/escalations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["escalations"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_returns_only_pending_by_default(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /escalations returns only pending records by default."""
        job = _make_job_record()
        pending = _make_escalation_record(escalation_id="esc-pending", status="pending")
        resolved = _make_escalation_record(escalation_id="esc-resolved", status="resolved")
        resolved.resolution_method = "user_submit"
        resolved.resolved_at = datetime.now(UTC).isoformat()

        db_session.add(job)
        db_session.add(pending)
        db_session.add(resolved)
        await db_session.commit()

        resp = await client.get("/escalations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["escalations"][0]["id"] == "esc-pending"

    @pytest.mark.asyncio
    async def test_include_resolved_returns_all(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """GET /escalations?include_resolved=true returns all records."""
        job = _make_job_record()
        pending = _make_escalation_record(escalation_id="esc-pending", status="pending")
        resolved = _make_escalation_record(escalation_id="esc-resolved", status="resolved")
        resolved.resolution_method = "user_submit"
        resolved.resolved_at = datetime.now(UTC).isoformat()

        db_session.add(job)
        db_session.add(pending)
        db_session.add(resolved)
        await db_session.commit()

        resp = await client.get("/escalations", params={"include_resolved": "true"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2



# ---------------------------------------------------------------------------
# POST /escalations/{id}/submit tests
# ---------------------------------------------------------------------------


class TestSubmitEscalation:
    """Tests for POST /escalations/{id}/submit."""

    @pytest.mark.asyncio
    async def test_submit_resolves_pending_escalation(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /escalations/{id}/submit resolves a pending escalation with edited answers."""
        job = _make_job_record()
        escalation = _make_escalation_record()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        edited_answers = [
            {
                "field_id": "field_5",
                "edited_answer": "My personalized answer about Acme Corp.",
            }
        ]

        resp = await client.post(
            "/escalations/esc-001/submit",
            json={"edited_answers": edited_answers},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == "esc-001"
        assert data["status"] == "resolved"
        assert data["resolution_method"] == "user_submit"
        assert data["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_submit_returns_denormalized_job_info(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /escalations/{id}/submit includes job_title, company, fit_score."""
        job = _make_job_record(job_title="Lead Dev", company="TechCo", fit_score=92)
        escalation = _make_escalation_record()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.post(
            "/escalations/esc-001/submit",
            json={"edited_answers": [{"field_id": "f1", "edited_answer": "answer"}]},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["job_title"] == "Lead Dev"
        assert data["company"] == "TechCo"
        assert data["fit_score"] == 92

    @pytest.mark.asyncio
    async def test_submit_returns_404_for_nonexistent_id(
        self, client: AsyncClient
    ) -> None:
        """POST /escalations/{id}/submit returns 404 when escalation doesn't exist."""
        resp = await client.post(
            "/escalations/nonexistent-id/submit",
            json={"edited_answers": [{"field_id": "f1", "edited_answer": "x"}]},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_submit_returns_409_for_already_resolved(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /escalations/{id}/submit returns 409 when escalation already resolved."""
        job = _make_job_record()
        escalation = _make_escalation_record(status="resolved")
        escalation.resolution_method = "user_submit"
        escalation.resolved_at = datetime.now(UTC).isoformat()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.post(
            "/escalations/esc-001/submit",
            json={"edited_answers": [{"field_id": "f1", "edited_answer": "x"}]},
        )
        assert resp.status_code == 409
        assert "already resolved" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /escalations/{id}/skip tests
# ---------------------------------------------------------------------------


class TestSkipEscalation:
    """Tests for POST /escalations/{id}/skip."""

    @pytest.mark.asyncio
    async def test_skip_resolves_pending_escalation(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /escalations/{id}/skip marks escalation as skipped."""
        job = _make_job_record()
        escalation = _make_escalation_record()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.post("/escalations/esc-001/skip")
        assert resp.status_code == 200

        data = resp.json()
        assert data["id"] == "esc-001"
        assert data["status"] == "skipped"
        assert data["resolution_method"] == "user_skip"
        assert data["resolved_at"] is not None

    @pytest.mark.asyncio
    async def test_skip_returns_denormalized_job_info(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /escalations/{id}/skip includes job_title, company, fit_score."""
        job = _make_job_record(job_title="PM Role", company="StartupX", fit_score=88)
        escalation = _make_escalation_record()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.post("/escalations/esc-001/skip")
        assert resp.status_code == 200

        data = resp.json()
        assert data["job_title"] == "PM Role"
        assert data["company"] == "StartupX"
        assert data["fit_score"] == 88

    @pytest.mark.asyncio
    async def test_skip_returns_404_for_nonexistent_id(
        self, client: AsyncClient
    ) -> None:
        """POST /escalations/{id}/skip returns 404 when escalation doesn't exist."""
        resp = await client.post("/escalations/nonexistent-id/skip")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_skip_returns_409_for_already_resolved(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /escalations/{id}/skip returns 409 when escalation already resolved."""
        job = _make_job_record()
        escalation = _make_escalation_record(status="auto_submitted")
        escalation.resolution_method = "auto_submit"
        escalation.resolved_at = datetime.now(UTC).isoformat()
        db_session.add(job)
        db_session.add(escalation)
        await db_session.commit()

        resp = await client.post("/escalations/esc-001/skip")
        assert resp.status_code == 409
        assert "already resolved" in resp.json()["detail"].lower()
