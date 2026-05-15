"""
Unit tests for the FastAPI application entrypoint.

Tests cover:
- Lifespan startup initializes the database engine and tables
- Lifespan startup generates an API token when absent
- Lifespan startup loads an existing API token without regenerating
- Lifespan startup registers the scheduler
- Lifespan shutdown disposes the engine and stops the scheduler
- All routers are registered on the app
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from src.main import app


class TestAppRouterRegistration:
    """Tests for router registration on the FastAPI app."""

    def test_system_routes_registered(self) -> None:
        """System routes (status, run, pause, resume, health) are registered."""
        paths = [route.path for route in app.routes]
        assert "/status" in paths or any("/status" in p for p in paths)

    def test_config_routes_registered(self) -> None:
        """Config routes are registered under /config prefix."""
        paths = [route.path for route in app.routes]
        assert any("/config" in p for p in paths)

    def test_job_routes_registered(self) -> None:
        """Job routes are registered under /jobs prefix."""
        paths = [route.path for route in app.routes]
        assert any("/jobs" in p for p in paths)

    def test_queue_routes_registered(self) -> None:
        """Queue routes are registered under /queue prefix."""
        paths = [route.path for route in app.routes]
        assert any("/queue" in p for p in paths)

    def test_app_title(self) -> None:
        """App has the correct title."""
        assert app.title == "LinkedIn Job Automator"


class TestLifespan:
    """Tests for the lifespan startup and shutdown logic."""

    async def test_startup_calls_build_engine_and_init_db(self) -> None:
        """Lifespan startup calls build_engine and init_db."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def fake_get_session():
            yield mock_session

        with (
            patch("src.main.build_engine", return_value=mock_engine) as mock_build,
            patch("src.main.init_db", new_callable=AsyncMock) as mock_init,
            patch("src.main.get_session", side_effect=[fake_get_session(), fake_get_session()]),
            patch("src.main.get_config", new_callable=AsyncMock, return_value="existing_token"),
            patch("src.main.setup_scheduler") as mock_sched,
        ):
            mock_sched.return_value = MagicMock(running=True, shutdown=MagicMock())

            from src.main import lifespan

            async with lifespan(app):
                mock_build.assert_called_once()
                mock_init.assert_called_once_with(mock_engine)

    async def test_startup_generates_token_when_absent(self) -> None:
        """Lifespan startup generates a 32-byte hex token when api_token is absent."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def fake_get_session():
            yield mock_session

        stored_token: list[str] = []

        async def fake_get_config(session: object, key: str) -> object:
            if key == "api_token":
                return None
            if key == "settings":
                return None
            return None

        async def fake_set_config(session: object, key: str, value: object) -> None:
            if key == "api_token":
                stored_token.append(value)  # type: ignore[arg-type]

        with (
            patch("src.main.build_engine", return_value=mock_engine),
            patch("src.main.init_db", new_callable=AsyncMock),
            patch("src.main.get_session", side_effect=[fake_get_session(), fake_get_session()]),
            patch("src.main.get_config", side_effect=fake_get_config),
            patch("src.main.set_config", side_effect=fake_set_config),
            patch("src.main.setup_scheduler") as mock_sched,
        ):
            mock_sched.return_value = MagicMock(running=True, shutdown=MagicMock())

            from src.main import lifespan

            async with lifespan(app):
                pass

        assert len(stored_token) == 1
        assert len(stored_token[0]) == 64  # 32 bytes = 64 hex chars

    async def test_startup_does_not_regenerate_existing_token(self) -> None:
        """Lifespan startup does not overwrite an existing API token."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def fake_get_session():
            yield mock_session

        set_config_called = []

        async def fake_get_config(session: object, key: str) -> object:
            if key == "api_token":
                return "existing_token_value"
            if key == "settings":
                return None
            return None

        async def fake_set_config(session: object, key: str, value: object) -> None:
            set_config_called.append(key)

        with (
            patch("src.main.build_engine", return_value=mock_engine),
            patch("src.main.init_db", new_callable=AsyncMock),
            patch("src.main.get_session", side_effect=[fake_get_session(), fake_get_session()]),
            patch("src.main.get_config", side_effect=fake_get_config),
            patch("src.main.set_config", side_effect=fake_set_config),
            patch("src.main.setup_scheduler") as mock_sched,
        ):
            mock_sched.return_value = MagicMock(running=True, shutdown=MagicMock())

            from src.main import lifespan

            async with lifespan(app):
                pass

        # set_config should NOT have been called for api_token
        assert "api_token" not in set_config_called

    async def test_startup_registers_scheduler(self) -> None:
        """Lifespan startup calls setup_scheduler with the app."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def fake_get_session():
            yield mock_session

        with (
            patch("src.main.build_engine", return_value=mock_engine),
            patch("src.main.init_db", new_callable=AsyncMock),
            patch("src.main.get_session", side_effect=[fake_get_session(), fake_get_session()]),
            patch("src.main.get_config", new_callable=AsyncMock, return_value=None),
            patch("src.main.set_config", new_callable=AsyncMock),
            patch("src.main.setup_scheduler") as mock_sched,
        ):
            mock_sched.return_value = MagicMock(running=True, shutdown=MagicMock())

            from src.main import lifespan

            async with lifespan(app):
                mock_sched.assert_called_once()
                assert mock_sched.call_args[0][0] is app

    async def test_shutdown_disposes_engine(self) -> None:
        """Lifespan shutdown disposes the database engine."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def fake_get_session():
            yield mock_session

        with (
            patch("src.main.build_engine", return_value=mock_engine),
            patch("src.main.init_db", new_callable=AsyncMock),
            patch("src.main.get_session", side_effect=[fake_get_session(), fake_get_session()]),
            patch("src.main.get_config", new_callable=AsyncMock, return_value="token"),
            patch("src.main.setup_scheduler") as mock_sched,
        ):
            mock_sched.return_value = MagicMock(running=True, shutdown=MagicMock())

            from src.main import lifespan

            async with lifespan(app):
                pass

        mock_engine.dispose.assert_called_once()

    async def test_shutdown_stops_scheduler(self) -> None:
        """Lifespan shutdown calls scheduler.shutdown."""
        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        async def fake_get_session():
            yield mock_session

        mock_scheduler_instance = MagicMock(running=True, shutdown=MagicMock())

        with (
            patch("src.main.build_engine", return_value=mock_engine),
            patch("src.main.init_db", new_callable=AsyncMock),
            patch("src.main.get_session", side_effect=[fake_get_session(), fake_get_session()]),
            patch("src.main.get_config", new_callable=AsyncMock, return_value="token"),
            patch("src.main.setup_scheduler") as mock_sched,
        ):
            mock_sched.return_value = mock_scheduler_instance

            # setup_scheduler stores on app.state.scheduler
            def side_effect_setup(a, t):
                a.state.scheduler = mock_scheduler_instance
                return mock_scheduler_instance

            mock_sched.side_effect = side_effect_setup

            from src.main import lifespan

            async with lifespan(app):
                pass

        mock_scheduler_instance.shutdown.assert_called_once_with(wait=False)
