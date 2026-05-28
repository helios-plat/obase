"""db_backup — Database backup utilities."""
from __future__ import annotations
from pathlib import Path
import time

class DbBackupError(Exception):
    """Base error for db_backup."""

class DbBackup:
    """Manage database backup operations.

    Example:
        >>> b = DbBackup(backup_dir=Path("/tmp/backups"))
        >>> b.create(db_name="helios")
    """
    def __init__(self, *, backup_dir: Path) -> None:
        self._backup_dir = backup_dir
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def create(self, *, db_name: str, format: str = "custom") -> dict:
        """Create a backup record (actual pg_dump delegated to shell)."""
        ts = int(time.time())
        path = self._backup_dir / f"{db_name}_{ts}.backup"
        return {"db_name": db_name, "path": str(path), "timestamp": ts, "format": format}

    def list_backups(self) -> list[str]:
        return [f.name for f in self._backup_dir.glob("*.backup")]
