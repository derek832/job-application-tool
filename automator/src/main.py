"""
FastAPI application entrypoint for the LinkedIn Job Automator.

Creates the FastAPI app with a lifespan handler that initializes the database,
generates an API token if absent, and registers the APScheduler cron jobs.
The app binds exclusively to 127.0.0.1:7432.

Validates: Requirements 12.4, 12.5, 10.6
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.api.config_routes import router as config_router
from src.api.job_routes import router as job_router
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
    async for session in get_session():
        api_token = await get_config(session, "api_token")

        if api_token is None:
            api_token = secrets.token_hex(32)
            await set_config(session, "api_token", api_token)
            await session.commit()
            logger.info("api_token_generated", token=api_token)
        else:
            logger.info("api_token_loaded", token=api_token)
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
app.include_router(queue_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="127.0.0.1",
        port=7432,
        log_level="info",
    )
