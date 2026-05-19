"""Unit tests for configuration API endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.config_routes import router
from src.db.database import get_session
from src.db.models import Base

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
    """Create a FastAPI app with config routes and overridden dependencies."""
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
# Search Config tests
# ---------------------------------------------------------------------------


class TestSearchConfig:
    """Tests for GET/PUT /config/search."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/search returns default empty config when not set."""
        resp = await client.get("/config/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["keywords"] is None
        assert data["location"] is None
        assert data["job_type"] is None
        assert data["experience_level"] is None
        assert data["remote_pref"] is None

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/search persists data retrievable via GET."""
        payload = {
            "keywords": "python,fastapi",
            "location": "San Francisco",
            "job_type": "full-time",
            "experience_level": "mid-senior",
            "remote_pref": "remote",
        }
        put_resp = await client.put("/config/search", json=payload)
        assert put_resp.status_code == 200
        assert put_resp.json()["keywords"] == "python,fastapi"

        get_resp = await client.get("/config/search")
        assert get_resp.status_code == 200
        expected = {**payload, "search_queries": [], "time_range": None, "sort_by": None}
        assert get_resp.json() == expected

    @pytest.mark.asyncio
    async def test_put_partial_update(self, client: AsyncClient) -> None:
        """PUT /config/search with partial fields sets others to None."""
        payload = {"keywords": "react", "location": "NYC"}
        resp = await client.put("/config/search", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["keywords"] == "react"
        assert data["location"] == "NYC"
        assert data["job_type"] is None

    @pytest.mark.asyncio
    async def test_put_validates_body(self, client: AsyncClient) -> None:
        """PUT /config/search rejects invalid body types."""
        resp = await client.put("/config/search", json={"keywords": ["not", "a", "string"]})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Goals Profile tests
# ---------------------------------------------------------------------------


class TestGoalsProfile:
    """Tests for GET/PUT /config/goals."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/goals returns default empty profile when not set."""
        resp = await client.get("/config/goals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_titles"] == []
        assert data["deal_breakers"] == []
        assert data["open_to_stretch"] is True
        assert data["min_salary"] is None

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/goals persists data retrievable via GET."""
        payload = {
            "target_titles": ["Senior Engineer", "Staff Engineer"],
            "industries": ["Tech"],
            "company_sizes": ["startup"],
            "geo_prefs": ["Bay Area"],
            "min_salary": 150000,
            "deal_breakers": ["clearance required"],
            "open_to_stretch": False,
            "career_objective": "Lead a platform team.",
        }
        put_resp = await client.put("/config/goals", json=payload)
        assert put_resp.status_code == 200

        get_resp = await client.get("/config/goals")
        assert get_resp.status_code == 200
        expected = {**payload, "supplementary_context": None}
        assert get_resp.json() == expected

    @pytest.mark.asyncio
    async def test_put_with_empty_lists(self, client: AsyncClient) -> None:
        """PUT /config/goals accepts empty lists."""
        payload = {
            "target_titles": [],
            "industries": [],
            "company_sizes": [],
            "geo_prefs": [],
            "deal_breakers": [],
            "open_to_stretch": True,
        }
        resp = await client.put("/config/goals", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_titles"] == []


# ---------------------------------------------------------------------------
# User Profile tests
# ---------------------------------------------------------------------------


class TestUserProfile:
    """Tests for GET/PUT /config/profile."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/profile returns default empty profile when not set."""
        resp = await client.get("/config/profile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["full_name"] is None
        assert data["email"] is None
        assert data["common_answers"] == {}

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/profile persists data retrievable via GET."""
        payload = {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "555-0100",
            "location": "San Francisco, CA",
            "work_auth": "US Citizen",
            "linkedin_url": "https://linkedin.com/in/janedoe",
            "common_answers": {"willing_to_relocate": "yes", "start_date": "immediately"},
        }
        put_resp = await client.put("/config/profile", json=payload)
        assert put_resp.status_code == 200

        get_resp = await client.get("/config/profile")
        assert get_resp.status_code == 200
        assert get_resp.json() == payload

    @pytest.mark.asyncio
    async def test_put_with_common_answers(self, client: AsyncClient) -> None:
        """PUT /config/profile stores common_answers dict correctly."""
        payload = {
            "full_name": "John",
            "common_answers": {"q1": "a1", "q2": "a2"},
        }
        resp = await client.put("/config/profile", json=payload)
        assert resp.status_code == 200
        assert resp.json()["common_answers"] == {"q1": "a1", "q2": "a2"}


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------


class TestSettings:
    """Tests for GET/PUT /config/settings."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_with_redacted_secrets(self, client: AsyncClient) -> None:
        """GET /config/settings returns defaults with secrets redacted."""
        resp = await client.get("/config/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["claude_api_key"] == "***"
        assert data["good_fit_threshold"] == 75
        assert data["stretch_threshold"] == 50

    @pytest.mark.asyncio
    async def test_put_stores_secrets_but_get_redacts(self, client: AsyncClient) -> None:
        """PUT /config/settings stores real values; GET redacts secrets."""
        payload = {
            "claude_api_key": "sk-ant-real-key-12345",
            "gmail_user": "user@gmail.com",
            "sms_gateway": "5551234567@txt.att.net",
            "good_fit_threshold": 80,
            "stretch_threshold": 55,
        }
        put_resp = await client.put("/config/settings", json=payload)
        assert put_resp.status_code == 200
        put_data = put_resp.json()
        # PUT response also redacts secrets
        assert put_data["claude_api_key"] == "***"
        # Non-secret fields are returned as-is
        assert put_data["gmail_user"] == "user@gmail.com"
        assert put_data["sms_gateway"] == "5551234567@txt.att.net"
        assert put_data["good_fit_threshold"] == 80

        get_resp = await client.get("/config/settings")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["claude_api_key"] == "***"
        assert get_data["sms_gateway"] == "5551234567@txt.att.net"
        assert get_data["good_fit_threshold"] == 80

    @pytest.mark.asyncio
    async def test_put_merges_with_existing(self, client: AsyncClient) -> None:
        """PUT /config/settings merges partial updates with existing values."""
        # First PUT sets some values
        await client.put(
            "/config/settings",
            json={"claude_api_key": "key1", "good_fit_threshold": 80},
        )

        # Second PUT updates only threshold
        resp = await client.put(
            "/config/settings",
            json={"good_fit_threshold": 90},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Threshold updated
        assert data["good_fit_threshold"] == 90
        # Secret still redacted (but was preserved in storage)
        assert data["claude_api_key"] == "***"

    @pytest.mark.asyncio
    async def test_put_with_all_none_is_noop(self, client: AsyncClient) -> None:
        """PUT /config/settings with all None fields preserves existing."""
        await client.put(
            "/config/settings",
            json={"sms_gateway": "5551234567@txt.att.net", "good_fit_threshold": 85},
        )

        # PUT with empty body (all None)
        resp = await client.put("/config/settings", json={})
        assert resp.status_code == 200
        data = resp.json()
        # Existing values preserved
        assert data["sms_gateway"] == "5551234567@txt.att.net"
        assert data["good_fit_threshold"] == 85


# ---------------------------------------------------------------------------
# Ntfy Config tests
# ---------------------------------------------------------------------------


class TestNtfyConfig:
    """Tests for GET/PUT /config/ntfy."""

    @pytest.mark.asyncio
    async def test_get_returns_defaults_when_empty(self, client: AsyncClient) -> None:
        """GET /config/ntfy returns default config when nothing is stored."""
        resp = await client.get("/config/ntfy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ntfy_enabled"] is False
        assert data["ntfy_server_url"] == "https://ntfy.sh"
        assert data["urgent_topic"] is None
        assert data["info_topic"] is None
        assert data["lan_base_url"] is None

    @pytest.mark.asyncio
    async def test_get_does_not_return_api_token(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """GET /config/ntfy never includes the api_token field."""
        from src.db.config_repo import set_config

        await set_config(db_session, "api_token", "secret-token-123")
        await db_session.commit()

        resp = await client.get("/config/ntfy")
        assert resp.status_code == 200
        data = resp.json()
        assert "api_token" not in data

    @pytest.mark.asyncio
    async def test_get_returns_stored_values(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """GET /config/ntfy returns values previously stored in config."""
        from src.db.config_repo import set_config

        await set_config(db_session, "ntfy_enabled", True)
        await set_config(db_session, "ntfy_server_url", "https://custom.ntfy.example.com")
        await set_config(db_session, "ntfy_urgent_topic", "abc123def456gh78")
        await set_config(db_session, "ntfy_info_topic", "ij90kl12mn34op56")
        await set_config(db_session, "lan_base_url", "http://192.168.1.50:7432")
        await db_session.commit()

        resp = await client.get("/config/ntfy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ntfy_enabled"] is True
        assert data["ntfy_server_url"] == "https://custom.ntfy.example.com"
        assert data["urgent_topic"] == "abc123def456gh78"
        assert data["info_topic"] == "ij90kl12mn34op56"
        assert data["lan_base_url"] == "http://192.168.1.50:7432"

    @pytest.mark.asyncio
    async def test_put_and_get_round_trip(self, client: AsyncClient) -> None:
        """PUT /config/ntfy persists data retrievable via GET."""
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "https://ntfy.sh",
            "lan_base_url": "http://192.168.1.100:7432",
        }
        put_resp = await client.put("/config/ntfy", json=payload)
        assert put_resp.status_code == 200
        put_data = put_resp.json()
        assert put_data["ntfy_enabled"] is True
        assert put_data["ntfy_server_url"] == "https://ntfy.sh"
        assert put_data["lan_base_url"] == "http://192.168.1.100:7432"

        get_resp = await client.get("/config/ntfy")
        assert get_resp.status_code == 200
        get_data = get_resp.json()
        assert get_data["ntfy_enabled"] is True
        assert get_data["ntfy_server_url"] == "https://ntfy.sh"
        assert get_data["lan_base_url"] == "http://192.168.1.100:7432"

    @pytest.mark.asyncio
    async def test_put_with_null_lan_base_url(self, client: AsyncClient) -> None:
        """PUT /config/ntfy accepts null lan_base_url."""
        payload = {
            "ntfy_enabled": False,
            "ntfy_server_url": "https://ntfy.sh",
            "lan_base_url": None,
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["lan_base_url"] is None

    @pytest.mark.asyncio
    async def test_put_rejects_invalid_server_url(self, client: AsyncClient) -> None:
        """PUT /config/ntfy rejects server URLs not starting with http:// or https://."""
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "ftp://invalid.example.com",
            "lan_base_url": None,
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_put_rejects_server_url_without_protocol(self, client: AsyncClient) -> None:
        """PUT /config/ntfy rejects server URLs without a protocol."""
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "ntfy.sh",
            "lan_base_url": None,
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_put_accepts_http_server_url(self, client: AsyncClient) -> None:
        """PUT /config/ntfy accepts http:// server URLs."""
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "http://my-local-ntfy:8080",
            "lan_base_url": None,
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 200
        assert resp.json()["ntfy_server_url"] == "http://my-local-ntfy:8080"

    @pytest.mark.asyncio
    async def test_put_rejects_invalid_lan_address(self, client: AsyncClient) -> None:
        """PUT /config/ntfy rejects invalid LAN addresses."""
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "https://ntfy.sh",
            "lan_base_url": "not a valid address!!!",
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_put_accepts_valid_lan_ipv4_with_port(self, client: AsyncClient) -> None:
        """PUT /config/ntfy accepts valid IPv4 with port as LAN address."""
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "https://ntfy.sh",
            "lan_base_url": "http://10.0.0.5:7432",
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 200
        assert resp.json()["lan_base_url"] == "http://10.0.0.5:7432"

    @pytest.mark.asyncio
    async def test_put_accepts_valid_lan_hostname(self, client: AsyncClient) -> None:
        """PUT /config/ntfy accepts valid hostname as LAN address."""
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "https://ntfy.sh",
            "lan_base_url": "http://my-desktop:7432",
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 200
        assert resp.json()["lan_base_url"] == "http://my-desktop:7432"

    @pytest.mark.asyncio
    async def test_put_does_not_modify_topics(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """PUT /config/ntfy does not allow modifying read-only topics."""
        from src.db.config_repo import get_config, set_config

        # Pre-seed topics
        await set_config(db_session, "ntfy_urgent_topic", "original_urgent_1")
        await set_config(db_session, "ntfy_info_topic", "original_info_123")
        await db_session.commit()

        # PUT with different values (topics not in the schema)
        payload = {
            "ntfy_enabled": True,
            "ntfy_server_url": "https://ntfy.sh",
            "lan_base_url": None,
        }
        resp = await client.put("/config/ntfy", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # Topics remain unchanged
        assert data["urgent_topic"] == "original_urgent_1"
        assert data["info_topic"] == "original_info_123"

        # Verify in DB
        urgent = await get_config(db_session, "ntfy_urgent_topic")
        info = await get_config(db_session, "ntfy_info_topic")
        assert urgent == "original_urgent_1"
        assert info == "original_info_123"


# ---------------------------------------------------------------------------
# Auth dependency tests
# ---------------------------------------------------------------------------


class TestAuthDependency:
    """Tests verifying auth is enforced on config routes."""

    @pytest.mark.asyncio
    async def test_missing_auth_returns_401_or_403(self, db_session: AsyncSession) -> None:
        """Requests without auth header are rejected."""
        # Create app WITHOUT overriding auth
        app = FastAPI()
        app.include_router(router)

        async def _get_test_session():
            yield db_session

        app.dependency_overrides[get_session] = _get_test_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/config/search")
            # FastAPI HTTPBearer returns 403 when no credentials are provided
            assert resp.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_ntfy_endpoints_require_auth(self, db_session: AsyncSession) -> None:
        """Ntfy config endpoints require authentication."""
        # Create app WITHOUT overriding auth
        app = FastAPI()
        app.include_router(router)

        async def _get_test_session():
            yield db_session

        app.dependency_overrides[get_session] = _get_test_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            get_resp = await ac.get("/config/ntfy")
            assert get_resp.status_code in (401, 403)

            put_resp = await ac.put(
                "/config/ntfy",
                json={"ntfy_enabled": True, "ntfy_server_url": "https://ntfy.sh"},
            )
            assert put_resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Blacklist Config tests
# ---------------------------------------------------------------------------


class TestBlacklistConfig:
    """Tests for blacklist configuration endpoints."""

    @pytest.mark.asyncio
    async def test_get_returns_empty_when_no_entries(self, client: AsyncClient) -> None:
        """GET /config/blacklist returns empty lists when no entries exist."""
        resp = await client.get("/config/blacklist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["companies"] == []
        assert data["title_patterns"] == []

    @pytest.mark.asyncio
    async def test_put_replaces_blacklist_entirely(self, client: AsyncClient) -> None:
        """PUT /config/blacklist replaces all entries."""
        payload = {
            "companies": ["Revature", "Infosys"],
            "title_patterns": ["intern", "entry level"],
        }
        resp = await client.put("/config/blacklist", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["companies"]) == 2
        assert len(data["title_patterns"]) == 2
        assert data["companies"][0]["value"] == "Revature"
        assert data["companies"][0]["hit_count"] == 0
        assert data["title_patterns"][1]["value"] == "entry level"

    @pytest.mark.asyncio
    async def test_put_clears_existing_entries(self, client: AsyncClient) -> None:
        """PUT /config/blacklist clears old entries before adding new ones."""
        # First PUT
        await client.put(
            "/config/blacklist",
            json={"companies": ["OldCo"], "title_patterns": ["old pattern"]},
        )
        # Second PUT replaces entirely
        resp = await client.put(
            "/config/blacklist",
            json={"companies": ["NewCo"], "title_patterns": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["companies"]) == 1
        assert data["companies"][0]["value"] == "NewCo"
        assert data["title_patterns"] == []

        # Verify via GET
        get_resp = await client.get("/config/blacklist")
        get_data = get_resp.json()
        assert len(get_data["companies"]) == 1
        assert get_data["companies"][0]["value"] == "NewCo"
        assert get_data["title_patterns"] == []

    @pytest.mark.asyncio
    async def test_post_company_adds_entry(self, client: AsyncClient) -> None:
        """POST /config/blacklist/companies adds a new company entry."""
        resp = await client.post("/config/blacklist/companies", json={"value": "Wipro"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["value"] == "Wipro"
        assert data["hit_count"] == 0

    @pytest.mark.asyncio
    async def test_post_company_rejects_duplicate(self, client: AsyncClient) -> None:
        """POST /config/blacklist/companies returns 409 for duplicate entry."""
        await client.post("/config/blacklist/companies", json={"value": "Revature"})
        resp = await client.post("/config/blacklist/companies", json={"value": "revature"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_company_removes_entry(self, client: AsyncClient) -> None:
        """DELETE /config/blacklist/companies/{entry} removes the entry."""
        await client.post("/config/blacklist/companies", json={"value": "Infosys"})
        resp = await client.delete("/config/blacklist/companies/Infosys")
        assert resp.status_code == 200

        # Verify it's gone
        get_resp = await client.get("/config/blacklist")
        data = get_resp.json()
        assert all(c["value"] != "Infosys" for c in data["companies"])

    @pytest.mark.asyncio
    async def test_delete_company_returns_404_for_missing(self, client: AsyncClient) -> None:
        """DELETE /config/blacklist/companies/{entry} returns 404 if not found."""
        resp = await client.delete("/config/blacklist/companies/NonExistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_post_title_adds_entry(self, client: AsyncClient) -> None:
        """POST /config/blacklist/titles adds a new title pattern entry."""
        resp = await client.post("/config/blacklist/titles", json={"value": "intern"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["value"] == "intern"
        assert data["hit_count"] == 0

    @pytest.mark.asyncio
    async def test_post_title_rejects_duplicate(self, client: AsyncClient) -> None:
        """POST /config/blacklist/titles returns 409 for duplicate entry."""
        await client.post("/config/blacklist/titles", json={"value": "junior"})
        resp = await client.post("/config/blacklist/titles", json={"value": "Junior"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_delete_title_removes_entry(self, client: AsyncClient) -> None:
        """DELETE /config/blacklist/titles/{entry} removes the entry."""
        await client.post("/config/blacklist/titles", json={"value": "part-time"})
        resp = await client.delete("/config/blacklist/titles/part-time")
        assert resp.status_code == 200

        # Verify it's gone
        get_resp = await client.get("/config/blacklist")
        data = get_resp.json()
        assert all(t["value"] != "part-time" for t in data["title_patterns"])

    @pytest.mark.asyncio
    async def test_delete_title_returns_404_for_missing(self, client: AsyncClient) -> None:
        """DELETE /config/blacklist/titles/{entry} returns 404 if not found."""
        resp = await client.delete("/config/blacklist/titles/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_hit_counts(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """GET /config/blacklist returns hit counts for each entry."""
        from src.db.blacklist_repo import add_entry as repo_add_entry, increment_hit_count

        # Add entries directly via repo and increment hit counts
        entry = await repo_add_entry(db_session, "company", "TestCo")
        await increment_hit_count(db_session, entry.id)
        await increment_hit_count(db_session, entry.id)
        await db_session.commit()

        resp = await client.get("/config/blacklist")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["companies"]) == 1
        assert data["companies"][0]["value"] == "TestCo"
        assert data["companies"][0]["hit_count"] == 2
