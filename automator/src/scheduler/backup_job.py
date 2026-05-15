"""
Daily database backup job.

Copies the SQLite state database to a user-configured backup directory with a
datestamped filename. Designed to be registered as a daily APScheduler job.

The backup uses ``shutil.copy2`` to preserve file metadata (timestamps, etc.).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import structlog

from src.api.schemas import Settings

logger = structlog.get_logger(__name__)

_DEFAULT_DB_PATH = Path("data") / "state.db"
_DEFAULT_BACKUP_DIR = Path("data") / "backups"


def run_backup(settings: Settings) -> None:
    """Copy the SQLite database to the backup directory with a datestamped filename.

    The backup file is named ``state_YYYY-MM-DD.db`` where the date is today's
    date. The backup directory is created if it does not already exist.

    Args:
        settings: Application settings containing the ``backup_dir`` path.
            Falls back to ``data/backups`` if ``backup_dir`` is not configured.
    """
    backup_dir = Path(settings.backup_dir) if settings.backup_dir else _DEFAULT_BACKUP_DIR
    db_path = _DEFAULT_DB_PATH

    if not db_path.exists():
        logger.warning("backup_skipped", reason="database_file_not_found", db_path=str(db_path))
        return

    backup_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    backup_filename = f"state_{today}.db"
    dest_path = backup_dir / backup_filename

    shutil.copy2(db_path, dest_path)

    logger.info(
        "backup_completed",
        source=str(db_path),
        destination=str(dest_path),
        date=today,
    )


def register_backup_job(scheduler: object) -> None:
    """Register the daily database backup as an APScheduler job.

    Adds a cron-triggered job that runs ``run_backup`` once per day at midnight.
    The job ID is ``daily_db_backup`` so it can be identified and managed.

    Args:
        scheduler: An APScheduler ``AsyncScheduler`` or ``BackgroundScheduler``
            instance. The function calls ``scheduler.add_job`` with a cron
            trigger set to fire daily at 00:00.
    """
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(  # type: ignore[attr-defined]
        run_backup,
        trigger=CronTrigger(hour=0, minute=0),
        id="daily_db_backup",
        name="Daily State DB Backup",
        replace_existing=True,
    )

    logger.info("backup_job_registered", job_id="daily_db_backup", schedule="daily at 00:00")
