"""
FastAPI application entrypoint for the LinkedIn Job Automator.

Creates the FastAPI app with a lifespan handler that initializes the database,
generates an API token if absent, and registers the APScheduler cron jobs.
The app binds to 0.0.0.0:7432 so the LAN server accepts connections from any
interface inside the container.

Validates: Requirements 12.4, 12.5, 10.6
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import structlog
from fastapi import FastAPI

from src.api.chrome_routes import router as chrome_router
from src.api.config_routes import router as config_router
from src.api.config_routes import schedule_router
from src.api.escalation_routes import router as escalation_router
from src.api.health_routes import router as health_router
from src.api.job_routes import router as job_router
from src.api.lan_server import create_lan_app, start_lan_server
from src.api.log_routes import router as log_router
from src.api.preview_routes import router as preview_router
from src.api.queue_routes import router as queue_router
from src.api.run_routes import router as run_router
from src.api.scoring_trial_routes import router as scoring_trial_router
from src.api.system_routes import router as system_router
from src.db.config_repo import get_config, set_config
from src.db.database import build_engine, get_session, init_db
from src.integrations.ntfy_topic_gen import ensure_topics
from src.pipeline.quiet_hours import register_quiet_hours_flush_job
from src.scheduler.schedule_manager import (
    ScheduleConfig,
    apply_schedule,
    validate_schedule_config,
)
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

    # Seed ntfy configuration defaults if not already present
    async for session in get_session():
        ntfy_enabled = await get_config(session, "ntfy_enabled")
        if ntfy_enabled is None:
            await set_config(session, "ntfy_enabled", False)
            logger.info("ntfy_config_seeded", key="ntfy_enabled", value=False)

        ntfy_server_url = await get_config(session, "ntfy_server_url")
        if ntfy_server_url is None:
            await set_config(session, "ntfy_server_url", "https://ntfy.sh")
            logger.info("ntfy_config_seeded", key="ntfy_server_url", value="https://ntfy.sh")

        lan_base_url = await get_config(session, "lan_base_url")
        if lan_base_url is None:
            await set_config(session, "lan_base_url", None)
            logger.info("ntfy_config_seeded", key="lan_base_url", value=None)

        await session.commit()

        # Auto-generate ntfy topics if absent
        await ensure_topics(session)
        break

    # Start LAN server if lan_base_url is configured
    async for session in get_session():
        lan_base_url = await get_config(session, "lan_base_url")
        break

    if lan_base_url:
        parsed = urlparse(lan_base_url)
        lan_port = parsed.port or 7432
        # The main app already binds to 0.0.0.0:7432 and Docker maps it to
        # the LAN. The separate LAN server is only needed if running outside
        # Docker on a different port. Since we're in Docker with port mapping,
        # skip the LAN server — the main app handles LAN requests directly.
        if lan_port != 7432:
            lan_app = create_lan_app(app)
            await start_lan_server("0.0.0.0", lan_port, lan_app)
            logger.info(
                "lan_server_started",
                host="0.0.0.0",
                port=lan_port,
                base_url=lan_base_url,
            )
        else:
            logger.info(
                "lan_server_skipped_same_port",
                reason="main app already serves on 0.0.0.0:7432 via Docker port mapping",
                base_url=lan_base_url,
            )
    else:
        logger.warning(
            "lan_server_skipped",
            reason="lan_base_url not configured — ntfy action buttons are disabled",
        )

    # Determine scheduled time from settings (if configured)
    async for session in get_session():
        settings = await get_config(session, "settings")
        break

    scheduled_time: str | None = None
    if settings and isinstance(settings, dict):
        scheduled_time = settings.get("scheduled_time")

    # Register the scheduler
    setup_scheduler(app, scheduled_time)

    # Load schedule_config from database and apply APScheduler triggers
    async for session in get_session():
        schedule_config_data = await get_config(session, "schedule_config")
        break

    if schedule_config_data and isinstance(schedule_config_data, dict):
        try:
            config = ScheduleConfig(
                mode=schedule_config_data.get("mode", "specific_times"),
                times=schedule_config_data.get("times", []),
                interval_hours=schedule_config_data.get("interval_hours", 2),
                window_start=schedule_config_data.get("window_start", "08:00"),
                window_end=schedule_config_data.get("window_end", "20:00"),
                weekend_runs=schedule_config_data.get("weekend_runs", False),
                timezone=schedule_config_data.get("timezone", "America/New_York"),
                quiet_hours_start=schedule_config_data.get("quiet_hours_start"),
                quiet_hours_end=schedule_config_data.get("quiet_hours_end"),
            )
            validate_schedule_config(config)
            apply_schedule(app.state.scheduler, config)
            logger.info(
                "schedule_config_applied_on_startup",
                mode=config.mode,
                timezone=config.timezone,
            )

            # Register quiet hours flush job if quiet_hours_end is configured
            if config.quiet_hours_end:
                register_quiet_hours_flush_job(
                    app.state.scheduler,
                    config.quiet_hours_end,
                    config.timezone,
                )
                logger.info(
                    "quiet_hours_flush_registered_on_startup",
                    quiet_hours_end=config.quiet_hours_end,
                    timezone=config.timezone,
                )
        except (ValueError, KeyError) as exc:
            logger.warning(
                "schedule_config_invalid_on_startup",
                error=str(exc),
            )
    else:
        logger.info("schedule_config_not_found", reason="no schedule_config in database")

    # Recover pending escalation timeouts that may have expired during downtime
    from src.pipeline.escalation_scheduler import recover_pending_timeouts_on_startup

    async for session in get_session():
        await recover_pending_timeouts_on_startup(session)
        break

    # Eagerly load LocalScorer (embedding model + trained artifacts)
    import src.scoring.local_scorer as local_scorer_module
    from src.scoring.local_scorer import LocalScorer

    try:
        scorer = LocalScorer(data_dir="data/models")
        await scorer.initialize()
        app.state.local_scorer = scorer
        local_scorer_module._active_scorer = scorer
        logger.info(
            "local_scorer_initialized",
            is_ready=scorer.is_ready,
            version=scorer.model_version,
        )
    except Exception as exc:
        logger.info(
            "local_scorer_init_skipped",
            reason=str(exc),
            hint="Local scoring will be dormant until model/embeddings are available",
        )
        app.state.local_scorer = None
        local_scorer_module._active_scorer = None

    logger.info("startup_complete", host="0.0.0.0", port=7432)

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
app.include_router(schedule_router)
app.include_router(job_router)
app.include_router(log_router)
app.include_router(queue_router)
app.include_router(run_router)
app.include_router(preview_router)
app.include_router(health_router)
app.include_router(chrome_router)
app.include_router(escalation_router)
app.include_router(scoring_trial_router)


# ---------------------------------------------------------------------------
# Unauthenticated ntfy confirm endpoint (token validated via query param)
# ---------------------------------------------------------------------------


@app.get("/ntfy-confirm")
async def ntfy_confirm_via_browser(
    test_id: str | None = None,
    token: str | None = None,
):
    """Browser-accessible confirm endpoint for ntfy test action buttons.

    Validates the token from the query parameter (since browsers can't send
    Authorization headers). Records the confirmation so the UI detects it.
    """
    from datetime import UTC, datetime

    from fastapi.responses import HTMLResponse

    from src.db.config_repo import get_config, set_config
    from src.db.database import get_session

    # Validate token
    async for session in get_session():
        stored_token = await get_config(session, "api_token")
        if not token or token != stored_token:
            return HTMLResponse(
                content=(
                    "<html><body style='font-family:system-ui;text-align:center;"
                    "padding:60px 20px;'>"
                    "<h1 style='color:#dc2626;'>✗ Not Authorized</h1>"
                    "<p>Invalid or missing token.</p>"
                    "</body></html>"
                ),
                status_code=401,
            )

        # Record confirmation
        data = await get_config(session, "ntfy_test_pending")
        if data and isinstance(data, dict):
            data["confirmed"] = True
            data["confirmed_at"] = datetime.now(UTC).isoformat()
            if test_id:
                data["test_id"] = test_id
            await set_config(session, "ntfy_test_pending", data)
            await session.commit()

        return HTMLResponse(
            content=(
                "<html><body style='font-family:system-ui;text-align:center;"
                "padding:60px 20px;'>"
                "<h1 style='color:#16a34a;'>✓ Connection Confirmed</h1>"
                "<p>Ntfy notifications are working. You can close this tab.</p>"
                "</body></html>"
            ),
            status_code=200,
        )
    # Fallback (should never reach here)
    return HTMLResponse(content="Error", status_code=500)  # type: ignore[return-value]


@app.get("/ntfy-action")
async def ntfy_action_via_browser(
    action: str | None = None,
    job_id: str | None = None,
    token: str | None = None,
):
    """Browser-accessible approve/reject endpoint for ntfy action buttons.

    Validates the token from the query parameter and performs the queue
    action (approve or reject). Returns a user-friendly HTML page.
    """
    from datetime import UTC, datetime

    from fastapi.responses import HTMLResponse

    from src.db.config_repo import get_config
    from src.db.database import get_session
    from src.db.job_repo import get_job_record, update_job_status

    if not action or action not in ("approve", "reject"):
        return HTMLResponse(
            content=(
                "<html><body style='font-family:system-ui;text-align:center;"
                "padding:60px 20px;'>"
                "<h1 style='color:#dc2626;'>✗ Invalid Action</h1>"
                "<p>Missing or invalid action parameter.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    if not job_id:
        return HTMLResponse(
            content=(
                "<html><body style='font-family:system-ui;text-align:center;"
                "padding:60px 20px;'>"
                "<h1 style='color:#dc2626;'>✗ Missing Job ID</h1>"
                "<p>No job_id provided.</p>"
                "</body></html>"
            ),
            status_code=400,
        )

    async for session in get_session():
        # Validate token
        stored_token = await get_config(session, "api_token")
        if not token or token != stored_token:
            return HTMLResponse(
                content=(
                    "<html><body style='font-family:system-ui;text-align:center;"
                    "padding:60px 20px;'>"
                    "<h1 style='color:#dc2626;'>✗ Not Authorized</h1>"
                    "<p>Invalid or missing token.</p>"
                    "</body></html>"
                ),
                status_code=401,
            )

        # Find the job
        record = await get_job_record(session, job_id)
        if record is None:
            return HTMLResponse(
                content=(
                    "<html><body style='font-family:system-ui;text-align:center;"
                    "padding:60px 20px;'>"
                    f"<h1 style='color:#dc2626;'>✗ Job Not Found</h1>"
                    f"<p>No job record with ID: {job_id}</p>"
                    "</body></html>"
                ),
                status_code=404,
            )

        now = datetime.now(UTC).isoformat()

        if action == "approve":
            await update_job_status(session, job_id, "approved_for_apply", reason="user_approved")
            record.queue_reason = None
            record.approved_at = now
            record.updated_at = now
            await session.commit()
            return HTMLResponse(
                content=(
                    "<html><body style='font-family:system-ui;text-align:center;"
                    "padding:60px 20px;'>"
                    "<h1 style='color:#16a34a;'>✓ Approved</h1>"
                    f"<p><strong>{record.job_title}</strong> @ {record.company}</p>"
                    "<p>The job will be processed for application shortly.</p>"
                    "</body></html>"
                ),
                status_code=200,
            )
        else:  # reject
            await update_job_status(session, job_id, "rejected_by_user", reason="user_rejected")
            record.queue_reason = None
            record.updated_at = now
            await session.commit()
            return HTMLResponse(
                content=(
                    "<html><body style='font-family:system-ui;text-align:center;"
                    "padding:60px 20px;'>"
                    "<h1 style='color:#f59e0b;'>✗ Rejected</h1>"
                    f"<p><strong>{record.job_title}</strong> @ {record.company}</p>"
                    "<p>This job has been removed from the queue.</p>"
                    "</body></html>"
                ),
                status_code=200,
            )

    return HTMLResponse(content="Error", status_code=500)  # type: ignore[return-value]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=7432,
        log_level="info",
    )
