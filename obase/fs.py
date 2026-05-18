from __future__ import annotations

import hashlib
import os
import platform
import shutil
import time
from pathlib import Path

import structlog

from obase.exceptions import FSError

log = structlog.get_logger()

_DEFAULT_WORKING_DIR = Path.home() / ".obase" / "work"
_working_dir: Path | None = None


class FS:
    """Filesystem utilities for obase pipelines."""

    @classmethod
    def set_default_working_dir(cls, path: Path) -> None:
        """Override the default working directory."""
        global _working_dir
        _working_dir = path

    @classmethod
    def working_dir(cls) -> Path:
        """Return the active working directory, creating it if absent."""
        base = _working_dir if _working_dir is not None else _DEFAULT_WORKING_DIR
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FSError(f"Cannot create working dir {base}: {exc}") from exc
        return base

    @classmethod
    def run_dir(cls, run_id: str) -> Path:
        """Return (and create) a per-run subdirectory."""
        d = cls.working_dir() / run_id
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FSError(f"Cannot create run dir {d}: {exc}") from exc
        return d

    @classmethod
    def hash_file(cls, path: Path, algorithm: str = "sha256") -> str:
        """Return hex digest of a file's contents."""
        if not path.exists():
            raise FSError(f"File not found: {path}")
        h = hashlib.new(algorithm)
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def cleanup_old_runs(cls, max_age_seconds: float = 7 * 86400) -> list[Path]:
        """Remove run subdirectories older than *max_age_seconds*. Returns removed paths."""
        removed: list[Path] = []
        base = cls.working_dir()
        now = time.time()
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            age = now - entry.stat().st_mtime
            if age > max_age_seconds:
                try:
                    shutil.rmtree(entry)
                    removed.append(entry)
                    log.info("obase.fs.removed_old_run", path=str(entry), age_s=age)
                except OSError as exc:
                    log.warning("obase.fs.cleanup_error", path=str(entry), error=str(exc))
        return removed

    @classmethod
    def to_wsl_path(cls, windows_path: str) -> Path:
        """Convert a Windows path to its WSL /mnt/ equivalent."""
        if platform.system() != "Linux":
            raise FSError("WSL path conversion only supported on Linux/WSL")
        p = windows_path.replace("\\", "/")
        if len(p) >= 2 and p[1] == ":":
            drive = p[0].lower()
            rest = p[2:]
            return Path(f"/mnt/{drive}{rest}")
        raise FSError(f"Not a Windows path: {windows_path!r}")

    @classmethod
    def from_wsl_path(cls, wsl_path: Path | str) -> str:
        """Convert a WSL /mnt/<drive>/... path to Windows format."""
        p = str(wsl_path)
        if p.startswith("/mnt/") and len(p) > 6:
            drive = p[5].upper()
            rest = p[6:].replace("/", "\\")
            return f"{drive}:{rest}"
        raise FSError(f"Not a /mnt/ WSL path: {wsl_path!r}")

    @classmethod
    def reset_working_dir(cls) -> None:
        """Reset to default (used in tests)."""
        global _working_dir
        _working_dir = None

    @classmethod
    def ensure_dir(cls, path: Path) -> Path:
        """Create a directory (and parents) if it does not exist."""
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FSError(f"Cannot create directory {path}: {exc}") from exc
        return path

    @classmethod
    def safe_write(cls, path: Path, data: bytes | str) -> None:
        """Atomic-ish write via a temp file."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            if isinstance(data, str):
                tmp.write_text(data, encoding="utf-8")
            else:
                tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise FSError(f"Write failed for {path}: {exc}") from exc
