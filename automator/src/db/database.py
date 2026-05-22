"""
Async database engine factory, session dependency, and DB initialisation.

This module is the single entry point for all database connectivity in the
Automator service.  It provides:

- ``create_engine`` — builds an async SQLAlchemy engine backed by aiosqlite.
- ``get_session`` — FastAPI dependency that yields a scoped ``AsyncSession``.
- ``init_db`` — creates all tables (if absent) on startup; safe to call on
  every restart (idempotent via ``checkfirst=True``).

Usage::

    # In FastAPI lifespan:
    await init_db(engine)

    # In a route handler:
    async def my_route(session: AsyncSession = Depends(get_session)):
        ...
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.db.models import Base

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (populated by build_engine / init_db)
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = os.path.join("data", "state.db")


def build_engine(db_url: str | None = None, **engine_kwargs: Any) -> AsyncEngine:
    """Create and cache an async SQLAlchemy engine for the given database URL.

    If *db_url* is ``None`` the engine connects to the default SQLite file at
    ``data/state.db`` (relative to the working directory, which is the mounted
    Docker volume path inside the container).

    The engine is stored in a module-level singleton so that ``get_session``
    and ``init_db`` can use it without requiring callers to pass it around.
    Call this function once during application startup (e.g. in the FastAPI
    lifespan handler).

    Args:
        db_url: SQLAlchemy async database URL.  Defaults to
            ``sqlite+aiosqlite:///data/state.db``.
        **engine_kwargs: Additional keyword arguments forwarded to
            ``create_async_engine`` (e.g. ``echo=True`` for SQL logging).

    Returns:
        The newly created ``AsyncEngine`` instance.
    """
    global _engine, _session_factory

    resolved_url = db_url or f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}"

    logger.info("building_async_engine", db_url=resolved_url)

    _engine = create_async_engine(
        resolved_url,
        # SQLite does not support multiple concurrent writers; serialise access.
        connect_args={"check_same_thread": False},
        **engine_kwargs,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    return _engine


# ---------------------------------------------------------------------------
# Session dependency
# ---------------------------------------------------------------------------


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a transactional ``AsyncSession``.

    Opens a new session for each request, commits on success, and rolls back
    on any unhandled exception before closing.  The session is always closed
    in the ``finally`` block regardless of outcome.

    Yields:
        An ``AsyncSession`` bound to the module-level engine.

    Raises:
        RuntimeError: If ``build_engine`` has not been called before the first
            request arrives.

    Example::

        @router.get("/jobs")
        async def list_jobs(session: AsyncSession = Depends(get_session)):
            result = await session.execute(select(JobRecord))
            return result.scalars().all()
    """
    if _session_factory is None:
        raise RuntimeError(
            "Database engine has not been initialised. "
            "Call build_engine() during application startup."
        )

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# DB initialisation
# ---------------------------------------------------------------------------


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create all database tables if they do not already exist.

    This function is idempotent: calling it on a database that already has the
    correct schema is a no-op.  It should be called once during application
    startup, before the HTTP server begins accepting requests.

    The function uses SQLAlchemy's ``create_all`` with ``checkfirst=True``
    (the default) so that existing tables are never dropped or altered.

    After creating tables, runs lightweight migrations for columns added after
    the initial schema (e.g. ``run_id`` on ``job_records``).

    Args:
        engine: The ``AsyncEngine`` to use.  If ``None``, the module-level
            singleton created by ``build_engine`` is used.

    Raises:
        RuntimeError: If no engine has been provided and ``build_engine`` has
            not been called yet.

    Example::

        # In FastAPI lifespan:
        engine = build_engine()
        await init_db(engine)
    """
    resolved_engine = engine or _engine

    if resolved_engine is None:
        raise RuntimeError(
            "No engine available. Call build_engine() before init_db(), "
            "or pass an engine explicitly."
        )

    logger.info("initialising_database", engine_url=str(resolved_engine.url))

    async with resolved_engine.begin() as conn:
        # create_all is idempotent: tables that already exist are skipped.
        await conn.run_sync(Base.metadata.create_all)

    # Run lightweight migrations for columns added after initial schema.
    # SQLite supports ALTER TABLE ADD COLUMN — safe and idempotent.
    await _run_migrations(resolved_engine)

    logger.info("database_ready")


async def _run_migrations(engine: AsyncEngine) -> None:
    """Apply incremental schema migrations for columns added post-launch.

    Each migration checks whether the column already exists before attempting
    to add it, making this function fully idempotent.

    Args:
        engine: The async engine to run migrations against.
    """
    from sqlalchemy import text as sa_text

    migrations: list[tuple[str, str, str]] = [
        # (table, column, SQL type)
        ("job_records", "run_id", "TEXT"),
        ("run_summaries", "jobs_applied_from_queue", "INTEGER DEFAULT 0"),
        ("job_records", "claude_cost_usd", "TEXT"),
        ("run_summaries", "claude_cost_usd", "TEXT"),
    ]

    async with engine.begin() as conn:
        for table, column, col_type in migrations:
            # Check if column exists by querying table_info
            result = await conn.execute(sa_text(f"PRAGMA table_info({table})"))
            columns = {row[1] for row in result.all()}
            if column not in columns:
                await conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                logger.info(
                    "migration_column_added",
                    table=table,
                    column=column,
                    col_type=col_type,
                )

        # Create partial index on escalation_records.timeout_deadline for
        # efficient lookup of pending escalations with active timeouts.
        # This is idempotent — CREATE INDEX IF NOT EXISTS is a no-op if it exists.
        await conn.execute(
            sa_text(
                "CREATE INDEX IF NOT EXISTS idx_escalation_records_timeout_pending "
                "ON escalation_records(timeout_deadline) "
                "WHERE status = 'pending' AND timeout_deadline IS NOT NULL"
            )
        )
