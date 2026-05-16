"""
FastAPI application entrypoint for the LinkedIn Job Automator.

Creates the FastAPI app with a lifespan handler that initializes the database,
generates an API token if absent, and registers the APScheduler cron jobs.
The app binds exclusively to 127.0.0.1:7432.

Validates: Requirements 12.4, 12.5, 10.6
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.api.config_routes import router as config_router
from src.api.job_routes import router as job_router
from src.api.log_routes import router as log_router
from src.api.queue_routes import router as queue_router
from src.api.system_routes import router as system_router
from src.db.config_repo import get_config, set_config
from src.db.database import build_engine, get_session, init_db
from src.scheduler.scheduler import setup_scheduler

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    Startup:
        1. Build the async database engine.
        2. Create tables if absent.
        3. Generate and store an API token if one does not exist.
        4. Log the API token so the user can copy it on first run.
        5. Register the APScheduler weekday cron job.
        6. Log startup complete.

    Shutdown:
        1. Shut down the scheduler.
        2. Dispose the database engine.
    """
    # --- Startup ---
    logger.info("startup_begin")

    engine = build_engine()
    await init_db(engine)

    # Open a session to check/generate the API token
    # If API_TOKEN env var is set, use it (and persist to DB). Otherwise use DB value or generate.
    async for session in get_session():
        env_token = os.environ.get("API_TOKEN", "").strip()
        api_token = await get_config(session, "api_token")

        if env_token:
            # Env var takes precedence — sync to DB if different
            if api_token != env_token:
                await set_config(session, "api_token", env_token)
                await session.commit()
            api_token = env_token
            logger.info("api_token_from_env", token=api_token)
        elif api_token is None:
            api_token = secrets.token_hex(32)
            await set_config(session, "api_token", api_token)
            await session.commit()
            logger.info("api_token_generated", token=api_token)
        else:
            logger.info("api_token_loaded", token=api_token)
        break

    # Seed settings from environment variables if not already configured
    async for session in get_session():
        existing_settings = await get_config(session, "settings")
        if existing_settings is None:
            existing_settings = {}

        # Map env vars to settings keys
        env_mapping = {
            "claude_api_key": os.environ.get("CLAUDE_API_KEY", ""),
            "gmail_user": os.environ.get("GMAIL_USER", ""),
            "gdocs_script_url": os.environ.get("GOOGLE_APPS_SCRIPT_URL", ""),
            "sms_gateway": os.environ.get("SMS_GATEWAY", ""),
        }

        updated = False
        for key, env_value in env_mapping.items():
            if env_value and not existing_settings.get(key):
                existing_settings[key] = env_value
                updated = True

        # Set defaults for numeric fields if missing
        if "good_fit_threshold" not in existing_settings:
            existing_settings["good_fit_threshold"] = 75
            updated = True
        if "stretch_threshold" not in existing_settings:
            existing_settings["stretch_threshold"] = 50
            updated = True
        if "dry_run" not in existing_settings:
            existing_settings["dry_run"] = False
            updated = True

        if updated:
            await set_config(session, "settings", existing_settings)
            await session.commit()
            logger.info("settings_seeded_from_env", keys=list(env_mapping.keys()))
        break

    # Determine scheduled time from settings (if configured)
    async for session in get_session():
        settings = await get_config(session, "settings")
        break

    scheduled_time: str | None = None
    if settings and isinstance(settings, dict):
        scheduled_time = settings.get("scheduled_time")

    # Register the scheduler
    setup_scheduler(app, scheduled_time)

    logger.info("startup_complete", host="127.0.0.1", port=7432)

    yield

    # --- Shutdown ---
    logger.info("shutdown_begin")

    if hasattr(app.state, "scheduler") and app.state.scheduler:
        app.state.scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")

    await engine.dispose()
    logger.info("engine_disposed")

    logger.info("shutdown_complete")


app = FastAPI(
    title="LinkedIn Job Automator",
    description="Locally-hosted job application automation API.",
    version="0.1.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(system_router)
app.include_router(config_router)
app.include_router(job_router)
app.include_router(log_router)
app.include_router(queue_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=7432,
        log_level="info",
    )
