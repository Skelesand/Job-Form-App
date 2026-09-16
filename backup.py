import datetime as dt
import sqlite3
from pathlib import Path


def sqlite_path(database_url):
    """Convert a SQLite database URL into a local file path."""
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Backup operations currently support SQLite databases only.")
    return Path(database_url.removeprefix("sqlite:///"))


def backup_database(database_url, backup_path):
    """Copy a SQLite database to a backup file and check its integrity."""
    source_path = sqlite_path(database_url)
    destination = Path(backup_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Backup integrity check failed: {result}")
    return destination


def restore_database(backup_path, database_url):
    """Restore a SQLite backup into the database file and check its integrity."""
    source_path = Path(backup_path)
    destination = sqlite_path(database_url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source_path) as source, sqlite3.connect(destination) as target:
        source.backup(target)
        result = target.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"Restore integrity check failed: {result}")
    return destination


def create_timestamped_backup(database_url, backup_directory):
    """Create a timestamped database backup in the requested directory."""
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    return backup_database(database_url, Path(backup_directory) / f"scan_jobs-{timestamp}.db")


def prune_backups(backup_directory, keep=14):
    """Remove older backup files while keeping the requested number of recent files."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    backups = sorted(Path(backup_directory).glob("scan_jobs-*.db"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old_backup in backups[keep:]:
        old_backup.unlink()
    return backups[:keep]
