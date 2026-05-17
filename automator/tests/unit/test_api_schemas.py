"""Unit tests for API Pydantic v2 schemas."""

from __future__ import annotations

from src.api.schemas import (
    GoalsProfile,
    GoalsProfileUpdate,
    HealthResponse,
    JobRecordOut,
    QueueItemOut,
    SearchConfig,
    SearchConfigUpdate,
    Settings,
    SettingsUpdate,
    StatsOut,
    StatusResponse,
    SystemState,
    UserProfile,
    UserProfileUpdate,
)


class TestSearchConfig:
    """Tests for SearchConfig schema."""

    def test_defaults_to_none(self) -> None:
        config = SearchConfig()
        assert config.keywords is None
        assert config.location is None
        assert config.job_type is None
        assert config.experience_level is None
        assert config.remote_pref is None

    def test_all_fields_populated(self) -> None:
        config = SearchConfig(
            keywords="python,fastapi",
            location="San Francisco",
            job_type="full-time",
            experience_level="mid-senior",
            remote_pref="remote",
        )
        assert config.keywords == "python,fastapi"
        assert config.location == "San Francisco"


class TestGoalsProfile:
    """Tests for GoalsProfile schema."""

    def test_defaults(self) -> None:
        profile = GoalsProfile()
        assert profile.target_titles == []
        assert profile.deal_breakers == []
        assert profile.open_to_stretch is True
        assert profile.min_salary is None

    def test_full_profile(self) -> None:
        profile = GoalsProfile(
            target_titles=["Senior Engineer", "Staff Engineer"],
            industries=["Tech", "Finance"],
            company_sizes=["startup", "mid"],
            geo_prefs=["Bay Area"],
            min_salary=150000,
            deal_breakers=["clearance required"],
            open_to_stretch=False,
            career_objective="Lead a platform team.",
        )
        assert len(profile.target_titles) == 2
        assert profile.min_salary == 150000
        assert profile.open_to_stretch is False


class TestUserProfile:
    """Tests for UserProfile schema."""

    def test_defaults(self) -> None:
        profile = UserProfile()
        assert profile.full_name is None
        assert profile.common_answers == {}

    def test_with_common_answers(self) -> None:
        profile = UserProfile(
            full_name="Jane Doe",
            email="jane@example.com",
            common_answers={"willing_to_relocate": "yes"},
        )
        assert profile.common_answers["willing_to_relocate"] == "yes"


class TestSettings:
    """Tests for Settings schema with secret redaction."""

    def test_secret_fields_redacted_on_serialization(self) -> None:
        settings = Settings(
            claude_api_key="sk-ant-real-key-12345",
            gmail_user="user@gmail.com",
            sms_gateway="5551234567@txt.att.net",
            good_fit_threshold=80,
            stretch_threshold=55,
        )
        data = settings.model_dump()
        assert data["claude_api_key"] == "***"
        # Non-secret fields are NOT redacted
        assert data["gmail_user"] == "user@gmail.com"
        assert data["sms_gateway"] == "5551234567@txt.att.net"
        assert data["good_fit_threshold"] == 80
        assert data["stretch_threshold"] == 55

    def test_secret_fields_redacted_in_json(self) -> None:
        settings = Settings(
            claude_api_key="sk-ant-real-key",
            gmail_user="user@gmail.com",
        )
        json_str = settings.model_dump_json()
        assert '"claude_api_key":"***"' in json_str
        assert "sk-ant-real-key" not in json_str

    def test_none_secrets_still_redacted(self) -> None:
        settings = Settings()
        data = settings.model_dump()
        assert data["claude_api_key"] == "***"

    def test_defaults(self) -> None:
        settings = Settings()
        assert settings.good_fit_threshold == 75
        assert settings.stretch_threshold == 50


class TestSystemState:
    """Tests for SystemState schema."""

    def test_defaults(self) -> None:
        state = SystemState()
        assert state.status == "idle"
        assert state.last_run_at is None
        assert state.last_error is None

    def test_valid_statuses(self) -> None:
        for status in ("running", "paused", "idle", "error"):
            state = SystemState(status=status)
            assert state.status == status


class TestJobRecordOut:
    """Tests for JobRecordOut schema."""

    def test_from_dict(self) -> None:
        record = JobRecordOut(
            id="3987654321",
            job_title="Senior Software Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/3987654321",
            apply_type="easy_apply",
            status="discovered",
            discovered_at="2024-01-15T09:00:00Z",
            updated_at="2024-01-15T09:00:00Z",
        )
        assert record.id == "3987654321"
        assert record.fit_score is None
        assert record.external_url is None

    def test_from_attributes_mode(self) -> None:
        """Verify from_attributes=True allows ORM model conversion."""

        class FakeORM:
            id = "123"
            job_title = "Engineer"
            company = "Corp"
            location = None
            linkedin_url = "https://linkedin.com/jobs/view/123"
            external_url = None
            apply_type = "easy_apply"
            status = "applied"
            fit_score = 85
            fit_rationale = "Great match."
            description_text = "Job description here."
            resume_snapshot = None
            tailored_resume_pdf = "/app/data/pdfs/123.pdf"
            cover_letter_text = None
            error_message = None
            queue_reason = None
            discovered_at = "2024-01-15T09:00:00Z"
            extracted_at = "2024-01-15T09:01:00Z"
            scored_at = "2024-01-15T09:02:00Z"
            approved_at = "2024-01-15T09:03:00Z"
            applied_at = "2024-01-15T09:10:00Z"
            updated_at = "2024-01-15T09:10:00Z"

        record = JobRecordOut.model_validate(FakeORM(), from_attributes=True)
        assert record.id == "123"
        assert record.fit_score == 85
        assert record.tailored_resume_pdf == "/app/data/pdfs/123.pdf"


class TestQueueItemOut:
    """Tests for QueueItemOut schema."""

    def test_queue_item(self) -> None:
        item = QueueItemOut(
            job_id="3987654321",
            job_title="Senior Software Engineer",
            company="Acme Corp",
            linkedin_url="https://linkedin.com/jobs/view/3987654321",
            queue_reason="stretch_role",
            fit_score=68,
            fit_rationale="Strong Python match but lacks Kubernetes.",
            added_at="2024-01-15T09:14:22Z",
        )
        assert item.job_id == "3987654321"
        assert item.fit_score == 68


class TestStatsOut:
    """Tests for StatsOut schema."""

    def test_defaults(self) -> None:
        stats = StatsOut()
        assert stats.total_discovered == 0
        assert stats.application_success_rate == 0.0

    def test_with_values(self) -> None:
        stats = StatsOut(
            total_discovered=142,
            total_applied=28,
            total_skipped=89,
            total_pending_review=3,
            application_success_rate=0.93,
        )
        assert stats.total_discovered == 142
        assert stats.application_success_rate == 0.93


class TestStatusResponse:
    """Tests for StatusResponse schema."""

    def test_full_response(self) -> None:
        response = StatusResponse(
            status="idle",
            last_run_at="2024-01-15T09:00:00Z",
            next_run_at="2024-01-16T09:00:00Z",
            queue_count=3,
            stats=StatsOut(
                total_discovered=142,
                total_applied=28,
                total_skipped=89,
                total_pending_review=3,
                application_success_rate=0.93,
            ),
            health=HealthResponse(claude_api=True, gmail=True, google_docs=True),
        )
        assert response.status == "idle"
        assert response.queue_count == 3
        assert response.stats.total_applied == 28
        assert response.health.claude_api is True


class TestHealthResponse:
    """Tests for HealthResponse schema."""

    def test_defaults_to_false(self) -> None:
        health = HealthResponse()
        assert health.claude_api is False
        assert health.gmail is False
        assert health.google_docs is False


class TestUpdateSchemas:
    """Tests for PUT request body schemas."""

    def test_search_config_update(self) -> None:
        update = SearchConfigUpdate(keywords="python", location="NYC")
        assert update.keywords == "python"

    def test_goals_profile_update(self) -> None:
        update = GoalsProfileUpdate(
            target_titles=["Engineer"],
            deal_breakers=["clearance"],
        )
        assert update.target_titles == ["Engineer"]

    def test_user_profile_update(self) -> None:
        update = UserProfileUpdate(full_name="John Doe", email="john@example.com")
        assert update.full_name == "John Doe"

    def test_settings_update_partial(self) -> None:
        update = SettingsUpdate(good_fit_threshold=80)
        assert update.good_fit_threshold == 80
        assert update.claude_api_key is None
