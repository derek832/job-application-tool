"""
Unit tests for the daily database backup job.

Tests cover:
- Successful backup with configured backup_dir
- Successful backup with default backup_dir
- Backup skipped when DB file does not exist
- Datestamped filename format
- Backup directory creation
- register_backup_job adds a job to the scheduler
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.api.schemas import Settings
from src.scheduler.backup_job import register_backup_job, run_backup


@pytest.fixture
def settings_with_backup_dir(tmp_path: Path) -> Settings:
    """Settings with a configured backup directory."""
    return Settings(backup_dir=str(tmp_path / "backups"))


@pytest.fixture
def settings_without_backup_dir() -> Settings:
    """Settings with no backup directory configured."""
    return Settings(backup_dir=None)


@pytest.fixture
def fake_db(tmp_path: Path) -> Path:
    """Create a fake state.db file and patch the default path."""
    db_path = tmp_path / "state.db"
    db_path.write_text("fake database content")
    return db_path


class TestRunBackup:
    """Tests for run_backup function."""

    def test_backup_creates_file_with_datestamp(
        self, tmp_path: Path, fake_db: Path, settings_with_backup_dir: Settings
    ) -> None:
        """Backup creates a file named state_YYYY-MM-DD.db in the backup dir."""
        with patch("src.scheduler.backup_job._DEFAULT_DB_PATH", fake_db):
            run_backup(settings_with_backup_dir)

        today = date.today().isoformat()
        expected_file = Path(settings_with_backup_dir.backup_dir) / f"state_{today}.db"  # type: ignore[arg-type]
        assert expected_file.exists()
        assert expected_file.read_text() == "fake database content"

    def test_backup_creates_directory_if_missing(
        self, tmp_path: Path, fake_db: Path
    ) -> None:
        """Backup creates the backup directory if it does not exist."""
        backup_dir = tmp_path / "nested" / "backup" / "dir"
        settings = Settings(backup_dir=str(backup_dir))

        with patch("src.scheduler.backup_job._DEFAULT_DB_PATH", fake_db):
            run_backup(settings)

        assert backup_dir.exists()
        assert any(backup_dir.iterdir())

    def test_backup_uses_default_dir_when_not_configured(
        self, tmp_path: Path, fake_db: Path, settings_without_backup_dir: Settings
    ) -> None:
        """Backup falls back to data/backups when backup_dir is None."""
        default_backup_dir = tmp_path / "data" / "backups"

        with (
            patch("src.scheduler.backup_job._DEFAULT_DB_PATH", fake_db),
            patch("src.scheduler.backup_job._DEFAULT_BACKUP_DIR", default_backup_dir),
        ):
            run_backup(settings_without_backup_dir)

        today = date.today().isoformat()
        expected_file = default_backup_dir / f"state_{today}.db"
        assert expected_file.exists()

    def test_backup_skipped_when_db_missing(
        self, tmp_path: Path, settings_with_backup_dir: Settings
    ) -> None:
        """Backup is skipped gracefully when the database file does not exist."""
        nonexistent_db = tmp_path / "nonexistent.db"

        with patch("src.scheduler.backup_job._DEFAULT_DB_PATH", nonexistent_db):
            run_backup(settings_with_backup_dir)

        backup_dir = Path(settings_with_backup_dir.backup_dir)  # type: ignore[arg-type]
        assert not backup_dir.exists() or not any(backup_dir.iterdir())

    def test_backup_preserves_file_content(
        self, tmp_path: Path, fake_db: Path, settings_with_backup_dir: Settings
    ) -> None:
        """Backup file content matches the original database file."""
        with patch("src.scheduler.backup_job._DEFAULT_DB_PATH", fake_db):
            run_backup(settings_with_backup_dir)

        today = date.today().isoformat()
        backup_file = Path(settings_with_backup_dir.backup_dir) / f"state_{today}.db"  # type: ignore[arg-type]
        assert backup_file.read_bytes() == fake_db.read_bytes()


class TestRegisterBackupJob:
    """Tests for register_backup_job function."""

    @patch("src.scheduler.backup_job.CronTrigger", create=True)
    def test_registers_job_with_scheduler(self, mock_cron_trigger: MagicMock) -> None:
        """register_backup_job calls add_job on the scheduler with correct params."""
        mock_scheduler = MagicMock()

        with patch.dict("sys.modules", {"apscheduler": MagicMock(), "apscheduler.triggers": MagicMock(), "apscheduler.triggers.cron": MagicMock(CronTrigger=mock_cron_trigger)}):
            register_backup_job(mock_scheduler)

        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        assert call_kwargs[1]["id"] == "daily_db_backup"
        assert call_kwargs[1]["replace_existing"] is True

    @patch("src.scheduler.backup_job.CronTrigger", create=True)
    def test_registers_with_run_backup_function(self, mock_cron_trigger: MagicMock) -> None:
        """register_backup_job registers the run_backup function as the job target."""
        mock_scheduler = MagicMock()

        with patch.dict("sys.modules", {"apscheduler": MagicMock(), "apscheduler.triggers": MagicMock(), "apscheduler.triggers.cron": MagicMock(CronTrigger=mock_cron_trigger)}):
            register_backup_job(mock_scheduler)

        call_args = mock_scheduler.add_job.call_args
        assert call_args[0][0] is run_backup
