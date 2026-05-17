"""
LAN server for the LinkedIn Job Automator.

Provides a restricted FastAPI application that exposes only queue endpoints
and a health check on the user's LAN IP. This allows ntfy action buttons
to reach the Automator from the user's phone without exposing sensitive
endpoints (config, jobs, system control) to the local network.

All LAN endpoints require the same bearer token authentication as localhost.

Validates: Requirements 4.1, 4.2, 4.3
"""

from __future__ import annotations

import asyncio

import structlog
import uvicorn
from fastapi import APIRouter, Depends, FastAPI

from src.api.queue_routes import router as queue_router
from src.api.system_routes import verify_token

logger = structlog.get_logger(__name__)


def _create_health_router() -> APIRouter:
    """Create a minimal health-check router for the LAN app."""
    health_router = APIRouter()

    @health_router.get("/health")
    async def health_check(
        _: None = Depends(verify_token),
    ) -> dict[str, str]:
        """Return a simple health status. Requires bearer token auth."""
        return {"status": "ok"}

    return health_router


def create_lan_app(main_app: FastAPI) -> FastAPI:
    """Create a restricted FastAPI app exposing only queue + health endpoints.

    The LAN app is intentionally limited to prevent exposure of sensitive
    configuration, job data, or system control endpoints on the local network.

    Args:
        main_app: The main FastAPI application instance. Passed for potential
            shared state access, but the LAN app is independent.

    Returns:
        A new FastAPI instance with only queue and health routes mounted.
    """
    lan_app = FastAPI(
        title="Job Automator LAN API",
        description="Restricted LAN-accessible API for queue actions and health checks.",
        version="0.1.0",
    )

    # Mount the queue router (already has verify_token on all endpoints)
    lan_app.include_router(queue_router)

    # Mount a health endpoint with auth
    lan_app.include_router(_create_health_router())

    logger.info("lan_app_created", routes=["queue", "health"])

    return lan_app


async def start_lan_server(lan_ip: str, port: int, app: FastAPI) -> None:
    """Start the LAN-bound uvicorn server as a background asyncio task.

    The server runs indefinitely until the event loop is cancelled or the
    application shuts down.

    Args:
        lan_ip: The LAN IP address or hostname to bind to.
        port: The port number to bind to.
        app: The FastAPI application to serve.
    """
    config = uvicorn.Config(
        app=app,
        host=lan_ip,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    logger.info(
        "lan_server_starting",
        host=lan_ip,
        port=port,
    )

    # Run the server as a background asyncio task so it doesn't block
    asyncio.create_task(server.serve(), name="lan_server")
